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
            "### Recon Survey – Stage A (Sanitizer Sweep)\n"
            "1. Read the sanitizer anchor and stack summary.\n"
            "2. Draft 3–4 mutually exclusive hypotheses that explain the crash signal.\n"
            "3. For each hypothesis, jot the trigger, key object, and a quick probe (suggested step or log snippet).\n"
            "4. Publish Stage A with the headings `## Sanitizer Analysis` and `## Candidate Hypotheses (unordered)`.\n"
            "5. Record the board with a single `hypothesis_update` payload that lists every hypothesis and sets `\"phase_marker\": \"RECON_SANITIZER\"`."
        )
        self.followup_steps = max(followup_steps, 1)
        self.followup_message = followup_message or (
            "Reminder: finish Stage A of the Recon Survey. You need 3–4 mutually exclusive sanitizer-grounded "
            "hypotheses, the markdown block (`## Sanitizer Analysis`, `## Candidate Hypotheses`), and a "
            "`hypothesis_update` with `\"phase_marker\": \"RECON_SANITIZER\"` capturing the board."
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
        latest_marker = self._latest_marker(state)
        if latest_marker != "RECON_SANITIZER":
            issues.append('call `hypothesis_update` with "phase_marker": "RECON_SANITIZER" to lock Stage A')

        hypotheses = list(state.hypotheses.values())
        if len(hypotheses) < 3:
            issues.append("provide at least three mutually exclusive hypotheses")

        active = state.get_active_entry()
        if not active:
            issues.append("no active hypothesis captured after Stage A")

        fallbacks = [hyp for hyp in hypotheses if not active or hyp.hypothesis_id != active.hypothesis_id]
        if len(fallbacks) < 2:
            issues.append("add at least two fallback hypotheses (Stage A expects 3–4 total)")

        annotated = sum(1 for hyp in hypotheses if hyp.suggested_steps or hyp.open_questions)
        if annotated < len(hypotheses) - 1:
            issues.append("include quick probes or open questions for each hypothesis so PoC work has entry points")

        return (len(issues) == 0, issues)

    @staticmethod
    def _latest_marker(state) -> str | None:
        for entry in reversed(state.update_log):
            marker = entry.get("phase_marker")
            if marker:
                return marker
        return None
