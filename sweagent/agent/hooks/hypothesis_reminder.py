from __future__ import annotations

from typing import TYPE_CHECKING

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import AgentInfo, StepOutput

if TYPE_CHECKING:
    from sweagent.agent.agents import DefaultAgent


class HypothesisReminderHook(AbstractAgentHook):
    """Injects periodic reminders urging the model to update the hypothesis state."""

    def __init__(self, *, reminder_steps: int = 5, message: str | None = None):
        self.reminder_steps = max(reminder_steps, 1)
        self.message = (
            message
            or "Reminder: update the active hypothesis (current: {hypothesis_id}) "
            "using `hypothesis_update` with new evidence or contradictions."
        )
        self._agent: DefaultAgent | None = None
        self._tracked_last_update = -1
        self._last_reminder_step = -1

    def on_init(self, *, agent: "DefaultAgent"):
        self._agent = agent

    def on_step_done(self, *, step: StepOutput, info: AgentInfo):
        agent = self._agent
        if agent is None or not getattr(agent, "hypothesis_config", None):
            return
        config = agent.hypothesis_config
        if not (config and config.enabled and config.enable_auto_reminder):
            return
        state = getattr(agent, "_hypothesis_state", None)
        if state is None:
            return

        current_step = len(agent.trajectory)
        last_update = getattr(state, "last_update_step", -1) or -1

        # Reset reminder tracking if a new hypothesis update occurred.
        if last_update > self._tracked_last_update:
            self._tracked_last_update = last_update
            self._last_reminder_step = last_update
            return

        if not state.has_open_questions():
            return

        reference_step = max(self._last_reminder_step, last_update, 0)
        if current_step - reference_step < self.reminder_steps:
            return

        message = self.message.format(
            hypothesis_id=state.active_id,
            step=current_step,
            last_update=last_update if last_update >= 0 else "never",
        )
        agent.logger.info("🧭 hypothesis reminder: %s", message)
        agent._append_history(
            {
                "role": "user",
                "content": message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._last_reminder_step = current_step
