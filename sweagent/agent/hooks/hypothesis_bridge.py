from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import AgentInfo, StepOutput

if TYPE_CHECKING:
    from sweagent.agent.agents import DefaultAgent


class HypothesisBridgeHook(AbstractAgentHook):
    """Guides the agent through structured recon survey rounds using explicit markers."""

    PROMPT_DIR = Path("/mnt/d/Work_space/Memory_agent/VulnTree/prompts/sub_agent/bridges")

    def __init__(self):
        self._agent: DefaultAgent | None = None
        self._phase = "awaiting_blueprint"
        self._expected_marker: str | None = "BLUEPRINT_DONE"
        self._handled_markers: set[str] = set()
        self._steps_since_prompt = 0
        self._reminder_sent = False
        self._reminder_interval = 3

    # ------------------------------------------------------------------
    # Hook lifecycle
    # ------------------------------------------------------------------

    def on_init(self, *, agent: "DefaultAgent"):
        self._agent = agent

    def on_step_done(self, *, step: StepOutput, info: AgentInfo):
        agent = self._agent
        if agent is None or not getattr(agent, "hypothesis_config", None):
            return
        config = agent.hypothesis_config
        if not (config and config.enabled and config.enable_phase_guidance):
            return
        state = getattr(agent, "_hypothesis_state", None)
        marker = self._latest_marker(state)

        if self._phase == "awaiting_blueprint":
            if marker == "BLUEPRINT_DONE" and marker not in self._handled_markers and state is not None:
                ready, issues = self._blueprint_ready(state)
                if not ready:
                    self._send_blueprint_fixup(issues)
                    return
                self._handled_markers.add(marker)
                self._append_bridge("post_round0_guidance.prompt")
                self._set_phase("round12_pending", "ROUND12_DONE")
            else:
                self._steps_since_prompt += 1
                self._maybe_remind("BLUEPRINT_DONE")
            return

        if self._phase == "round12_pending":
            self._handle_phase(
                step,
                marker,
                "ROUND12_DONE",
                next_phase="round3a_pending",
                next_prompt="round3a_origin_validation.prompt",
                next_expected="ROUND3A_DONE",
                validator=self._round12_output_ready,
            )
            return

        if self._phase == "round3a_pending":
            self._handle_phase(
                step,
                marker,
                "ROUND3A_DONE",
                next_phase="round3b_pending",
                next_prompt="round3b_lifecycle_validation.prompt",
                next_expected="ROUND3B_DONE",
                validator=self._round3a_output_ready,
            )
            return

        if self._phase == "round3b_pending":
            self._handle_phase(
                step,
                marker,
                "ROUND3B_DONE",
                next_phase="decision_pending",
                next_prompt="round3_decision_prompt.prompt",
                next_expected=None,
                validator=self._round3b_output_ready,
            )
            return

        if self._phase == "decision_pending":
            if marker == "DECISION_A" and marker not in self._handled_markers:
                self._handled_markers.add(marker)
                self._append_bridge("round3b_lifecycle_validation.prompt")
                self._set_phase("round3b_pending", "ROUND3B_DONE")
                return
            if marker == "DECISION_B" and marker not in self._handled_markers:
                self._handled_markers.add(marker)
                self._append_bridge("final_gate.prompt")
                self._set_phase("final_gate_pending", "FINAL_REPORT")
                return
            self._steps_since_prompt += 1
            self._maybe_remind_decision()
            return

        if self._phase == "final_gate_pending":
            if marker == "FINAL_GATE_FAILED" and marker not in self._handled_markers:
                self._handled_markers.add(marker)
                self._append_bridge("validation_failed_guidance.prompt")
                self._set_phase("round3b_pending", "ROUND3B_DONE")
                return
            if marker == "FINAL_REPORT" and marker not in self._handled_markers:
                self._handled_markers.add(marker)
                self._phase = "completed"
                return
            self._steps_since_prompt += 1
            self._maybe_remind("FINAL_REPORT")
            
    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append_bridge(self, filename: str) -> None:
        agent = self._agent
        if agent is None:
            return
        prompt_path = self.PROMPT_DIR / filename
        if not prompt_path.exists():
            agent.logger.warning("Bridge prompt %s not found.", prompt_path)
            return
        content = prompt_path.read_text()
        marker_instructions = {
            "post_round0_guidance.prompt": "\nWhen you complete this round, call `hypothesis_update` and set `\"phase_marker\": \"ROUND12_DONE\"`.",
            "round3a_origin_validation.prompt": "\nUpon finishing Round 3a, call `hypothesis_update` with `\"phase_marker\": \"ROUND3A_DONE\"`.",
            "round3b_lifecycle_validation.prompt": "\nWhen Round 3b is complete, set `\"phase_marker\": \"ROUND3B_DONE\"` in your next `hypothesis_update`.",
            "round3_decision_prompt.prompt": "\nRespond with `\"phase_marker\": \"DECISION_A\"` to revisit lifecycle validation or `\"phase_marker\": \"DECISION_B\"` to proceed to the final gate.",
            "validation_failed_guidance.prompt": "\nAfter addressing the failure, call `hypothesis_update` with `\"phase_marker\": \"FINAL_GATE_FAILED\"` to record the conflict, then resume lifecycle validation with `\"phase_marker\": \"ROUND3B_DONE\"` once new evidence is gathered.",
            "final_gate.prompt": "\nWhen the final report is ready, submit it via `hypothesis_update` with `\"phase_marker\": \"FINAL_REPORT\"`. If validation fails, call `hypothesis_update` with `\"phase_marker\": \"FINAL_GATE_FAILED\"` and describe the logical conflict.",
        }
        if filename in marker_instructions:
            content = content + "\n" + marker_instructions[filename]
        agent.logger.info("📋 hypothesis bridge: injecting %s", filename)
        agent._append_history(
            {
                "role": "user",
                "content": content,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._steps_since_prompt = 0
        self._reminder_sent = False

    def _latest_marker(self, state) -> str | None:
        if state is None:
            return None
        for entry in reversed(state.update_log):
            marker = entry.get("phase_marker")
            if marker:
                return marker
        return None

    def _blueprint_ready(self, state) -> tuple[bool, list[str]]:
        issues: list[str] = []
        active = state.get_active_entry()
        if not active:
            issues.append("no primary hypothesis recorded")
        else:
            required_keyframes = {"crash", "propagation", "origin", "lifecycle"}
            keyframe_keys = {k.lower() for k in active.keyframes.keys()}
            if not required_keyframes.issubset(keyframe_keys):
                missing = required_keyframes - keyframe_keys
                issues.append("primary hypothesis missing keyframes: " + ", ".join(sorted(missing)))
            if not active.verification_plan:
                issues.append("primary hypothesis missing verification plan")

        fallbacks = [
            hyp for hyp in state.hypotheses.values() if active and hyp.hypothesis_id != active.hypothesis_id
        ]
        if not fallbacks:
            issues.append("add at least one fallback hypothesis")
        else:
            for hyp in fallbacks:
                if not hyp.keyframes:
                    issues.append(f"{hyp.hypothesis_id} missing keyframes")
                if not hyp.verification_plan:
                    issues.append(f"{hyp.hypothesis_id} missing verification plan")

        return (len(issues) == 0, issues)

    def _send_blueprint_fixup(self, issues: list[str]) -> None:
        agent = self._agent
        if agent is None:
            return
        message = "Blueprint still incomplete. Ensure your `hypothesis_update` includes:" + "\n- " + "\n- ".join(issues)
        agent._append_history(
            {
                "role": "user",
                "content": message + "\nRemember to set `\"phase_marker\": \"BLUEPRINT_DONE\"`.",
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._steps_since_prompt = 0
        self._reminder_sent = False

    def _round12_output_ready(self, step: StepOutput) -> tuple[bool, list[str]]:
        text = (step.output or "")
        requirements = [
            "## Immediate Cause",
            "## Origin Trace",
            "## Reasoning State Snapshot",
        ]
        missing = [f'missing section "{section}"' for section in requirements if section not in text]
        return (len(missing) == 0, missing)

    def _round3a_output_ready(self, step: StepOutput) -> tuple[bool, list[str]]:
        text = (step.output or "")
        requirements = [
            "### Question",
            "### Findings",
            "### Table Update",
            "### Hypothesis Impact",
            "### Reasoning State Update",
        ]
        missing = [f'missing section "{section}"' for section in requirements if section not in text]
        return (len(missing) == 0, missing)

    def _round3b_output_ready(self, step: StepOutput) -> tuple[bool, list[str]]:
        text = (step.output or "")
        requirements = [
            "### Primary Path Exploration",
            "### Pivot Checkpoint Results",
            "### Table Update",
            "### Hypothesis Impact",
            "### Reasoning State Update",
        ]
        missing = [f'missing section "{section}"' for section in requirements if section not in text]
        return (len(missing) == 0, missing)

    def _send_phase_fixup(self, marker: str, issues: list[str]) -> None:
        agent = self._agent
        if agent is None:
            return
        phase_description = {
            "ROUND12_DONE": "Round 1-2 output",
            "ROUND3A_DONE": "Round 3a output",
            "ROUND3B_DONE": "Round 3b output",
        }.get(marker, "Current round output")
        message = (
            f"{phase_description} is incomplete. Please include the missing sections before continuing:\n"
            + "\n- ".join([""] + issues)
            + "\nRemember to resend `hypothesis_update` with the same `phase_marker`."
        )
        agent._append_history(
            {
                "role": "user",
                "content": message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._steps_since_prompt = 0
        self._reminder_sent = False

    def _set_phase(self, phase: str, expected_marker: str | None):
        self._phase = phase
        self._expected_marker = expected_marker
        self._steps_since_prompt = 0
        self._reminder_sent = False

    def _handle_phase(
        self,
        step: StepOutput,
        marker: str | None,
        expected_marker: str,
        *,
        next_phase: str,
        next_prompt: str,
        next_expected: str | None,
        validator,
    ) -> None:
        if marker == expected_marker and marker not in self._handled_markers:
            ready, issues = validator(step)
            if not ready:
                self._send_phase_fixup(expected_marker, issues)
                return
            self._handled_markers.add(marker)
            self._append_bridge(next_prompt)
            self._set_phase(next_phase, next_expected)
            return
        self._steps_since_prompt += 1
        self._maybe_remind(expected_marker)

    def _maybe_remind(self, expected: str | None):
        if expected is None:
            return
        if self._reminder_sent:
            return
        if self._steps_since_prompt < self._reminder_interval:
            return
        agent = self._agent
        if agent is None:
            return
        agent.logger.info("🧭 hypothesis bridge reminder: waiting for marker %s", expected)
        agent._append_history(
            {
                "role": "user",
                "content": (
                    f"Reminder: include `\"phase_marker\": \"{expected}\"` in your next `hypothesis_update` payload "
                    "after completing the current recon survey round."
                ),
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._reminder_sent = True

    def _maybe_remind_decision(self):
        if self._reminder_sent:
            return
        if self._steps_since_prompt < self._reminder_interval:
            return
        agent = self._agent
        if agent is None:
            return
        agent.logger.info("🧭 hypothesis bridge reminder: waiting for decision marker")
        agent._append_history(
            {
                "role": "user",
                "content": (
                    "Reminder: choose the next path by calling `hypothesis_update` with either "
                    "`\"phase_marker\": \"DECISION_A\"` (revisit lifecycle validation) or "
                    "`\"phase_marker\": \"DECISION_B\"` (proceed to final gate)."
                ),
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._reminder_sent = True
