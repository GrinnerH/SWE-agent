from __future__ import annotations

from typing import TYPE_CHECKING

from sweagent.agent.hooks.abstract import AbstractAgentHook
from sweagent.types import AgentInfo, StepOutput

if TYPE_CHECKING:
    from sweagent.agent.agents import DefaultAgent

from .recon_templates import RECON_SEARCH_CHECKLIST, RECON_TRIGGER_REMINDER


class ReconDisciplineHook(AbstractAgentHook):
    """Lightweight enforcement of recon survey discipline.

    - Requires search commands to include planning context in the model's thought.
    - Reminds the model to apply deep analysis triggers after code readings.
    """

    SEARCH_COMMAND_PREFIXES = (
        "search_dir",
        "search_file",
        "search_repo",
        "grep",
        "rg",
        "find",
    )
    READ_COMMAND_PREFIXES = (
        "open_file",
        "read_file",
        "show_file",
        "cat",
        "sed",
    )

    def __init__(self, reminder_interval: int = 2):
        self._agent: DefaultAgent | None = None
        self._reminder_interval = max(reminder_interval, 1)
        self._last_planning_reminder_step = -100
        self._last_trigger_reminder_step = -100

    def on_init(self, *, agent: "DefaultAgent"):
        self._agent = agent

    def on_step_done(self, *, step: StepOutput, info: AgentInfo):
        agent = self._agent
        if agent is None or not getattr(agent, "hypothesis_config", None):
            return
        config = agent.hypothesis_config
        if not (config and config.enabled and config.enable_discipline):
            return

        action = (step.action or "").strip()
        if not action:
            return

        lower_action = action.lower()
        step_index = len(agent.trajectory)

        if self._is_search_action(lower_action):
            if not self._thought_has_planning(step.thought):
                if step_index - self._last_planning_reminder_step >= self._reminder_interval:
                    self._send_planning_reminder(step_index)

        if self._is_read_action(lower_action):
            observation = (step.output or "") + "\n" + (step.observation or "")
            if "[DEEP DIVE TRIGGER" not in observation:
                if step_index - self._last_trigger_reminder_step >= self._reminder_interval:
                    self._send_trigger_reminder(step_index)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_search_action(self, action: str) -> bool:
        if any(action.startswith(prefix) for prefix in self.SEARCH_COMMAND_PREFIXES):
            return True
        if action.startswith("bash") and any(f" {cmd}" in action for cmd in ("rg ", "grep ", "find ")):
            return True
        return False

    def _is_read_action(self, action: str) -> bool:
        if any(action.startswith(prefix) for prefix in self.READ_COMMAND_PREFIXES):
            return True
        if action.startswith("bash") and any(f" {cmd}" in action for cmd in ("cat ", "sed ")):
            return True
        return False

    def _thought_has_planning(self, thought: str | None) -> bool:
        if not thought:
            return False
        normalized = thought.lower()
        keywords = ("hypothesis", "evidence", "gap", "ah-", "pf-", "rh-", "verify", "plan")
        hits = sum(1 for kw in keywords if kw in normalized)
        return hits >= 2

    def _send_planning_reminder(self, step_index: int) -> None:
        agent = self._agent
        if agent is None:
            return
        message = RECON_SEARCH_CHECKLIST
        agent._append_history(
            {
                "role": "user",
                "content": message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._last_planning_reminder_step = step_index

    def _send_trigger_reminder(self, step_index: int) -> None:
        agent = self._agent
        if agent is None:
            return
        message = RECON_TRIGGER_REMINDER
        agent._append_history(
            {
                "role": "user",
                "content": message,
                "agent": agent.name,
                "message_type": "observation",
            }
        )
        self._last_trigger_reminder_step = step_index
