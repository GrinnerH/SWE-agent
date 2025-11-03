from __future__ import annotations

from typing import TYPE_CHECKING

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import AgentInfo, StepOutput

if TYPE_CHECKING:
    from sweagent.agent.agents import DefaultAgent

from .recon_templates import (
    RECON_SANITIZER_FIXUP,
    RECON_STACK_SCAN_FIXUP,
    RECON_STAGE_PROMPTS,
)


class HypothesisBridgeHook(AbstractAgentHook):
    """Guides the agent through the two-stage recon survey and PoC hand-off."""

    def __init__(self):
        self._agent: DefaultAgent | None = None
        self._phase = "sanitizer_pending"
        self._expected_marker: str | None = "RECON_SANITIZER"
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

        if self._phase == "sanitizer_pending":
            if marker == "RECON_SANITIZER" and marker not in self._handled_markers:
                ready, issues = self._sanitizer_stage_ready(state, step)
                if not ready:
                    self._send_fixup(RECON_SANITIZER_FIXUP, issues)
                    return
                self._handled_markers.add(marker)
                self._append_prompt("stack_scan_guidance")
                self._set_phase("stack_scan_pending", "RECON_STACK_SCAN")
                return
            self._steps_since_prompt += 1
            self._maybe_remind("RECON_SANITIZER")
            return

        if self._phase == "stack_scan_pending":
            if marker == "RECON_STACK_SCAN" and marker not in self._handled_markers:
                ready, issues = self._stack_scan_ready(step)
                if not ready:
                    self._send_fixup(RECON_STACK_SCAN_FIXUP, issues)
                    return
                self._handled_markers.add(marker)
                self._append_prompt("poc_transition")
                self._set_phase("poc_active", "FINAL_REPORT")
                return
            self._steps_since_prompt += 1
            self._maybe_remind("RECON_STACK_SCAN")
            return

        if self._phase == "poc_active":
            if marker == "FINAL_REPORT" and marker not in self._handled_markers:
                self._handled_markers.add(marker)
                self._phase = "completed"
                return
            self._steps_since_prompt += 1
            self._maybe_remind("FINAL_REPORT")
            return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sanitizer_stage_ready(self, state, step: StepOutput) -> tuple[bool, list[str]]:
        issues: list[str] = []
        if state is None:
            issues.append("hypothesis state unavailable")
        else:
            hypotheses = list(state.hypotheses.values())
            if len(hypotheses) < 3:
                issues.append("need at least three Stage-A hypotheses")
            annotated = sum(1 for hyp in hypotheses if hyp.suggested_steps or hyp.open_questions)
            if annotated < max(1, len(hypotheses) - 1):
                issues.append("missing quick probes/open questions for most hypotheses")
        text = (step.output or "") + "\n" + (step.observation or "")
        if "## Sanitizer Analysis" not in text:
            issues.append('missing heading "## Sanitizer Analysis"')
        if "## Candidate Hypotheses" not in text:
            issues.append('missing heading "## Candidate Hypotheses (unordered)"')
        return (len(issues) == 0, issues)

    @staticmethod
    def _stack_scan_ready(step: StepOutput) -> tuple[bool, list[str]]:
        issues: list[str] = []
        text = (step.output or "") + "\n" + (step.observation or "")
        if "## Hypothesis Ranking" not in text:
            issues.append('missing heading "## Hypothesis Ranking"')
        if "## Phenomena to Explain" not in text:
            issues.append('missing heading "## Phenomena to Explain"')
        return (len(issues) == 0, issues)

    @staticmethod
    def _latest_marker(state) -> str | None:
        if state is None:
            return None
        for entry in reversed(state.update_log):
            marker = entry.get("phase_marker")
            if marker:
                return marker
        return None

    def _send_fixup(self, message: str, issues: list[str]) -> None:
        agent = self._agent
        if agent is None:
            return
        content = message
        if issues:
            content += "\nOutstanding items: " + "; ".join(issues)
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

    def _append_prompt(self, key: str) -> None:
        agent = self._agent
        if agent is None:
            return
        content = RECON_STAGE_PROMPTS.get(key)
        if not content:
            return
        agent.logger.info("📋 hypothesis bridge: %s", key)
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

    def _set_phase(self, phase: str, expected_marker: str | None):
        self._phase = phase
        self._expected_marker = expected_marker
        self._steps_since_prompt = 0
        self._reminder_sent = False

    def _maybe_remind(self, expected: str | None) -> None:
        if expected is None or self._reminder_sent:
            return
        if self._steps_since_prompt < self._reminder_interval:
            return
        agent = self._agent
        if agent is None:
            return
        stage_label = {
            "sanitizer_pending": "Stage A (Sanitizer Sweep)",
            "stack_scan_pending": "Stage B (Stack Frame Scan)",
            "poc_active": "Final Report",
        }.get(self._phase, "current phase")
        agent.logger.info("🧭 hypothesis bridge reminder: waiting for marker %s", expected)
        agent._append_history(
            {
                "role": "user",
                "content": (
                    f"Reminder: finish {stage_label} and include `\"phase_marker\": \"{expected}\"` "
                    "in your next `hypothesis_update` once the output is ready."
                ),
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._reminder_sent = True
