## Hypothesis-driven mode (lightweight)

The lightweight hypothesis integration keeps VulnTree's core ideas—high-quality sanitizer grounding and assumption-driven exploration—without forking the SWE-agent execution loop.

### What it adds

- A sanitizer analyzer (`SanitizerReportAnalyzer`) extracts crash type, location, and stack frames from the problem statement.
- An in-memory hypothesis tracker maintains the active hypothesis, open questions, suggested steps, evidence, and a step-by-step update log.
- A new inline tool command `hypothesis_update` lets the model report structured updates via JSON.
- An auto-reminder hook nudges the agent to refresh the hypothesis when it has been idle for several steps, keeping the workflow aligned with the core methodology.
- Contextual blocks describing the sanitizer anchor and hypothesis board are appended to every LM query, so the model always sees the latest state.

### Payload schema (JSON)

```json
{
  "hypothesis_id": "H0_primary",
  "description": "Updated belief (optional)",
  "status": "active|pending|refuted|confirmed",
  "add_open_questions": ["Question text"],
  "resolve_open_questions": ["Resolved question"],
  "add_suggested_steps": ["Next action"],
  "drop_suggested_steps": ["Step to remove"],
  "add_evidence": ["Short evidence note"],
  "new_hypotheses": [
    {
      "id": "H1_memory",
      "description": "Alternative cause",
      "suggested_steps": ["Trace allocator"]
    }
  ],
  "switch_to": "H1_memory",
  "found_support": true,
  "found_contradiction": false
}
```

Only include fields that changed—everything else is optional. The command never touches the sandbox; it is intercepted before execution.

### Enabling the mode

1. Point your run to `config/security_hypothesis.yaml`, or copy the `hypothesis:` block into your own agent config.
2. Ensure the system instructions reference `{{sanitizer_context}}`, `{{hypothesis_current_block}}`, and `{{hypothesis_board}}`.
3. Encourage the model (via prompt) to call `hypothesis_update` after meaningful observations.

The rest of SWE-agent (tools, retries, submissions) continues to work unchanged. This keeps the surface area small while still giving you hypothesis tracking, explicit switching, and sanitizer anchoring.

### Update history & reminders

- Every call to `hypothesis_update` is stored in an in-memory log (timestamp, step, summary, payload snapshot). Recent entries are surfaced through `problem_statement.extra_fields` and written to the trajectory file, making it easy to audit hypothesis evolution.
- The optional auto-reminder hook (enabled via `hypothesis.enable_auto_reminder`) injects a system message when the agent goes too many steps without writing back. Adjust `reminder_steps` to tune the cadence or disable the hook entirely for free-form experimentation.
