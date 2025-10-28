from __future__ import annotations

from typing import TYPE_CHECKING

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import AgentInfo, StepOutput

if TYPE_CHECKING:
    from sweagent.agent.agents import DefaultAgent


class HypothesisBootstrapHook(AbstractAgentHook):
    """Ensures the agent produces an initial high-level hypothesis overview."""

    def __init__(
        self,
        *,
        initial_message: str | None = None,
        followup_steps: int = 1,
        followup_message: str | None = None,
    ):
        self.initial_message = initial_message or (
            "### Recon Survey – Sanitizer Blueprint\n"
            "1. Combine sanitizer signals and stack frames into a CONTROLLED blueprint.\n"
            "2. Produce mutually exclusive hypotheses ranked by likelihood.\n"
            "3. For each hypothesis, list:\n"
            "   - **Scenario / Root cause statement**\n"
            "   - **Keyframes**: Crash, Propagation, Origin, Lifecycle\n"
            "   - **Verification plan**: control-flow & data-flow checks required in Phase 1\n"
            "4. Call `hypothesis_update` once using this structure:\n"
            "```json\n"
            "{\n"
            "  \"hypothesis_id\": \"H0_primary\",\n"
            "  \"description\": \"<Primary root cause>\",\n"
            "  \"keyframes\": {\n"
            "    \"crash\": \"<What happens at the crash site>\",\n"
            "    \"propagation\": \"<How the faulty state propagates>\",\n"
            "    \"origin\": \"<Where the faulty value originates>\",\n"
            "    \"lifecycle\": \"<Why the value persists until crash>\"\n"
            "  },\n"
            "  \"verification_plan\": [\"<Verification step 1>\", \"<Verification step 2>\"],\n"
            "  \"add_suggested_steps\": [\"<Verification step 1>\", \"<Verification step 2>\"] ,\n"
            "  \"add_open_questions\": [\"<Outstanding question>\"] ,\n"
            "  \"new_hypotheses\": [\n"
            "    {\n"
            "      \"id\": \"H1_fallback\",\n"
            "      \"description\": \"<Fallback scenario>\",\n"
            "      \"status\": \"pending\",\n"
            "      \"keyframes\": {\n"
            "        \"crash\": \"<Crash manifestation>\",\n"
            "        \"propagation\": \"<Propagation path>\",\n"
            "        \"origin\": \"<Where alternate root cause begins>\",\n"
            "        \"lifecycle\": \"<Lifecycle assumption>\"\n"
            "      },\n"
            "      \"verification_plan\": [\"<Fallback check>\"],\n"
            "      \"suggested_steps\": [\"<Check>\"] ,\n"
            "      \"open_questions\": [\"<Key uncertainty>\"]\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "If multiple fallbacks exist, include them in `new_hypotheses`. Highlight Tier-1/2 evidence ids and guardrails (mutual exclusivity, execution order requirements).\n"
            "When the blueprint is ready, call `hypothesis_update` with `\"phase_marker\": \"BLUEPRINT_DONE\"`."
        )
        self.followup_steps = max(followup_steps, 1)
        self.followup_message = followup_message or (
            "Reminder: produce the recon survey hypothesis blueprint now. Include primary + fallback "
            "hypotheses, keyframes, verification plan, and outstanding questions via `hypothesis_update`."
        )
        self._agent: DefaultAgent | None = None
        self._initial_prompt_sent = False
        self._followup_sent = False

    def on_init(self, *, agent: "DefaultAgent"):
        self._agent = agent

    def on_run_start(self):
        agent = self._agent
        if agent is None or not getattr(agent, "hypothesis_config", None):
            return
        config = agent.hypothesis_config
        if not (config and config.enabled and config.enable_bootstrap):
            return
        agent.logger.info("🧭 hypothesis bootstrap: requesting initial overview.")
        agent._append_history(
            {
                "role": "user",
                "content": self.initial_message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._initial_prompt_sent = True

    def on_step_done(self, *, step: StepOutput, info: AgentInfo):
        agent = self._agent
        if agent is None or not getattr(agent, "hypothesis_config", None):
            return
        config = agent.hypothesis_config
        if not (config and config.enabled and config.enable_bootstrap):
            return
        state = getattr(agent, "_hypothesis_state", None)
        if state is None:
            return

        ready, issues = self._check_blueprint(state)
        if ready:
            return

        if self._followup_sent:
            return

        current_step = len(agent.trajectory)
        if current_step < self.followup_steps:
            return

        followup_message = self.followup_message
        if issues:
            followup_message += "\nOutstanding items: " + "; ".join(issues)

        agent.logger.info("🧭 hypothesis bootstrap follow-up: requesting initial update.")
        agent._append_history(
            {
                "role": "user",
                "content": followup_message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._followup_sent = True

    def _check_blueprint(self, state) -> tuple[bool, list[str]]:
        issues: list[str] = []
        latest_marker = None
        for entry in reversed(state.update_log):
            marker = entry.get("phase_marker")
            if marker:
                latest_marker = marker
                break
        if latest_marker != "BLUEPRINT_DONE":
            issues.append('call `hypothesis_update` with "phase_marker": "BLUEPRINT_DONE"')

        active = state.get_active_entry()
        if not active:
            issues.append("missing primary hypothesis")
        else:
            required_keyframes = {"crash", "propagation", "origin", "lifecycle"}
            keyframe_keys = set(k.lower() for k in active.keyframes.keys())
            if not required_keyframes.issubset(keyframe_keys):
                missing = required_keyframes - keyframe_keys
                issues.append("primary hypothesis missing keyframes: " + ", ".join(sorted(missing)))
            if not active.verification_plan:
                issues.append("primary hypothesis missing verification plan")

        fallback_hypotheses = [
            hyp for hyp in state.hypotheses.values() if active and hyp.hypothesis_id != active.hypothesis_id
        ]
        if not fallback_hypotheses:
            issues.append("provide at least one fallback hypothesis")
        else:
            for hyp in fallback_hypotheses:
                if not hyp.keyframes:
                    issues.append(f"{hyp.hypothesis_id} missing keyframes")
                if not hyp.verification_plan:
                    issues.append(f"{hyp.hypothesis_id} missing verification plan")

        return (len(issues) == 0, issues)
