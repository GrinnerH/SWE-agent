RECON_BLUEPRINT_TEMPLATE = """\
Blueprint still incomplete. Ensure your `hypothesis_update` contains:
- primary hypothesis with `description`, `keyframes` (crash/propagation/origin/lifecycle), `verification_plan`, `suggested_steps`, `open_questions`
- at least one fallback hypothesis (互斥 root cause) with相同字段
- `phase_marker`: "BLUEPRINT_DONE"

示例:
```json
{
  "phase_marker": "BLUEPRINT_DONE",
  "hypotheses": [
    {
      "id": "H0_primary",
      "description": "...",
      "keyframes": {
        "crash": "...",
        "propagation": "...",
        "origin": "...",
        "lifecycle": "..."
      },
      "verification_plan": ["Step 1", "Step 2"],
      "suggested_steps": ["Action"],
      "open_questions": ["Unknown"]
    }
  ],
  "fallback_hypotheses": [
    {
      "id": "H1_fallback",
      "description": "...",
      "keyframes": { "...": "..." },
      "verification_plan": ["Step"],
      "open_questions": ["Unknown"]
    }
  ]
}
```""".strip()

RECON_ROUND_FIXUP_TEMPLATES = {
    "ROUND12_DONE": """\
Round 1/2 output缺少必需部分。请重新输出一次 Markdown block，格式如下：
```
## Immediate Cause (Round 1)
- failing operation / object / failure condition

## Origin Trace (Round 2)
- 价值来源、赋值链、Outstanding questions

## Reasoning State Snapshot
- Proven Facts ...
- Refuted Hypotheses ...
- Active Hypotheses ...
```
完成后再次提交 `hypothesis_update`，并设置 `"phase_marker": "ROUND12_DONE"`。
""".strip(),
    "ROUND3A_DONE": """\
Round 3a 输出缺失，请严格按照以下模板：
```
### Question
### Findings
### Table Update
### Hypothesis Impact
### Reasoning State Update
```
补齐内容后，调用 `hypothesis_update`，`"phase_marker": "ROUND3A_DONE"`。
""".strip(),
    "ROUND3B_DONE": """\
Round 3b 输出缺失，请补齐以下段落：
```
### Primary Path Exploration
### Pivot Checkpoint Results
### Alternative Path Exploration   (如未激活可写 N/A)
### Table Update
### Hypothesis Impact
### Reasoning State Update
```
补齐后重新发送 `hypothesis_update`，`"phase_marker": "ROUND3B_DONE"`。
""".strip(),
}

RECON_SEARCH_CHECKLIST = """\
Before executing a search, answer the planning checklist in your next thought:
1. Which hypothesis (AH-#) are you targeting and why?
2. What evidence gap或 Control-Flow ID 正在弥补？
3. 预期结果是什么？如何确认或证伪该假设？
4. 是否重复搜索？之前结果如何？这次有何不同？
""".strip()

RECON_TRIGGER_REMINDER = """\
Deep Analysis Trigger reminder: 当阅读代码触发聚合赋值、Union 访问、多级指针、跨上下文传递或关键条件分支时，请回答对应问题，然后再进行下一次工具调用。
""".strip()
