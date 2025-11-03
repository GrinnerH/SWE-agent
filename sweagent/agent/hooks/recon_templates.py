RECON_SANITIZER_FIXUP = """\
Recon Stage A (Sanitizer Sweep) is incomplete. Please:
- Re-run the Stage A narration with the headings `## Sanitizer Analysis` and `## Candidate Hypotheses (unordered)`.
- List at least **three** mutually exclusive hypotheses, each with a trigger, key object, and quick probe.
- Call `hypothesis_update` again with `{"phase_marker": "RECON_SANITIZER", ...}` so the board records the update.
""".strip()

RECON_STACK_SCAN_FIXUP = """\
Recon Stage B (Stack Frame Scan) is missing required structure. Output a markdown block containing:
- `## Hypothesis Ranking` (ordered list with a one-line justification per hypothesis)
- `## Phenomena to Explain` (facts still unexplained)
- Optional `## Next Moves` if you already see the PoC path
Then call `hypothesis_update` with `{"phase_marker": "RECON_STACK_SCAN", ...}` reflecting the new ranking.
""".strip()

RECON_STAGE_PROMPTS = {
    "stack_scan_guidance": """\
### Stage B – Stack Frame Scan
- Walk the hottest stack frames (~30 lines each) and stress test every Stage-A hypothesis.
- Promote/demote hypotheses based on concrete code evidence; keep descriptions short.
- When finished, write the markdown block (`## Hypothesis Ranking`, `## Phenomena to Explain`) and update the board with `phase_marker`: `"RECON_STACK_SCAN"`.
""".strip(),
    "poc_transition": """\
### Transition to PoC Development
- Stage B is locked. Now focus on building the minimal PoC that discriminates the leading hypothesis.
- Deep Analysis Triggers re-activate for any new `open_file`/`search_*` call—answer them before the next tool use.
- Capture PoC scripts under `/testcase`, validate with `secb build` / `secb repro`, and only then prepare the final report (`phase_marker`: `"FINAL_REPORT"`).
""".strip(),
}

RECON_SEARCH_CHECKLIST = """\
Before running a search, include in your thought:
1. Target hypothesis / phenomenon and why it matters now.
2. Evidence gap or crash behavior you expect to resolve.
3. Anticipated signal and how it updates your ranking.
4. Whether this repeats a prior search and what changed.
""".strip()

RECON_TRIGGER_REMINDER = """\
Deep Analysis Trigger (PoC mode): aggregate writes, union member swaps, multi-level dereferences, cross-context passes, and guard-rail conditionals all require a short answer before your next tool call.
""".strip()
