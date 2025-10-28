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
            "Before issuing other actions, synthesize sanitizer findings into an initial "
            "hypothesis overview. Call `hypothesis_update` with `new_hypotheses`, "
            "`add_suggested_steps`, and `open_questions` to register the primary branches."
        )
        self.followup_steps = max(followup_steps, 1)
        self.followup_message = followup_message or (
            "Reminder: record the initial hypothesis report with `hypothesis_update` "
            "(include competing root-cause candidates and their key checks)."
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
        if state is None or state.update_log:
            # Initial hypothesis recorded.
            return
        if self._followup_sent:
            return
        current_step = len(agent.trajectory)
        if current_step < self.followup_steps:
            return
        agent.logger.info("🧭 hypothesis bootstrap follow-up: requesting initial update.")
        agent._append_history(
            {
                "role": "user",
                "content": self.followup_message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._followup_sent = True
