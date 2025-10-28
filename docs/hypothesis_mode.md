## Hypothesis-driven mode (lightweight)

The lightweight hypothesis integration keeps VulnTree's core ideas—high-quality sanitizer grounding and assumption-driven exploration—without forking the SWE-agent execution loop.

### What it adds

- A sanitizer analyzer (`SanitizerReportAnalyzer`) extracts crash type, location, and stack frames from the problem statement.
- An in-memory hypothesis tracker maintains the active hypothesis, open questions, suggested steps, evidence, and a step-by-step update log.
- A new inline tool command `hypothesis_update` lets the model report structured updates via JSON.
- A bootstrap hook nudges the model to first produce a structured recon survey blueprint (primary + fallback hypotheses, keyframes, verification plans), the discipline hook enforces planning/deep-trigger reminders before searches and code reviews, and an auto-reminder hook keeps the board fresh when several steps pass without updates.
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
4. Let the bootstrap and discipline hooks guide the initial blueprint; the first `hypothesis_update` must contain `keyframes`, `verification_plan`, at least one fallback hypothesis, and `"phase_marker": "BLUEPRINT_DONE"` or the hook will request corrections. Search commands also require answering the planning checklist the hook injects.

The rest of SWE-agent (tools, retries, submissions) continues to work unchanged. This keeps the surface area small while still giving you hypothesis tracking, explicit switching, and sanitizer anchoring.

### Update history & reminders

- Every call to `hypothesis_update` is stored in an in-memory log (timestamp, step, summary, payload snapshot). Recent entries are surfaced through `problem_statement.extra_fields` and written to the trajectory file, making it easy to audit hypothesis evolution.
- The bootstrap hook (enabled via `hypothesis.enable_bootstrap`) prompts the first `hypothesis_update`, ensuring a recon survey blueprint (primary + fallback hypotheses with keyframes and verification plans) is recorded before heavy exploration.
- The recon survey bridge hook (enabled via `hypothesis.enable_phase_guidance`) injects structured prompts for crash-site, origin, lifecycle, and final-report rounds. Each round is completed by including the appropriate `phase_marker` (e.g., `ROUND12_DONE`, `ROUND3A_DONE`, `ROUND3B_DONE`, `DECISION_A/B`, `FINAL_REPORT`) in a `hypothesis_update` payload. If the marker or required sections are missing, the hook will inject fix-up guidance before progressing.
- The discipline hook (enabled via `hypothesis.enable_discipline`) reminds the model to answer planning questions before each search and to process Deep Analysis Triggers after code readings.
- The auto-reminder hook (enabled via `hypothesis.enable_auto_reminder`) injects a system message when the agent goes too many steps without writing back. Adjust `reminder_steps` to tune the cadence or disable the hook entirely for free-form experimentation.
