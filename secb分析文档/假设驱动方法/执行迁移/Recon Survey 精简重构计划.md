# Recon Survey 精简重构计划

## 目标动机
- 当前 Recon Survey 流程依旧沿用 VulnTree Phase0 的完整多轮结构，虽能生成高质量蓝图，但执行成本巨大，实际轨迹往往需要数十个回合才能推进到 PoC 阶段。
- 蓝图阶段多项静态分析与深度探测在 PoC 验证前重复出现，造成“理论-实践脱节”：模型即便更新了假设，也未必及时转化为动态测试。
- 需要将 Recon Survey 调整为更轻量的“两阶段”流程：先快速生成互斥假设，再结合栈帧进行初步筛选；将深入的静态分析与动态验证留到 PoC 开发阶段，从而兼顾效率与可解释性。

## 拟实施方案
1. **两阶段 Recon Survey**
   - **阶段 A：Sanitizer 假设收敛**
     - 模型读取 crash 报告后，一次 `hypothesis_update` 生成 3–4 个互斥假设，内容包括触发条件、关键对象、初步验证想法。
     - 输出结构可包含：`## Sanitizer Analysis`、`## Candidate Hypotheses (unordered)`，不再要求 keyframes/verification plan 等细节。
   - **阶段 B：栈帧快速排查**
     - 阅读关键栈帧附近几十行代码，对假设进行初步检验与排序；输出 `## Hypothesis Ranking`、`## Phenomena to Explain` 等段落，形成最终的 Recon Survey 报告。
     - 若证据不足，允许保留多假设并指出待验证问题。
2. **后置细化与动态验证**
   - 在进入 PoC 阶段后，再触发 Deep Analysis Trigger、Control-Flow Table 等深度分析要求。
   - Final Gate 与提交流程需绑定 PoC 成功复现，避免出现“Final Gate 通过后仍继续 Round4-7”现象。
3. **提示词与 Hook 重构**
   - system prompt 重新描述“两阶段 Recon Survey → PoC 验证”的新流程，删除旧有的 Round1/2/3 模板及示例。
   - 新增精简版 bridge/disciplines hook：
     - 阶段 A 结束时检测 `phase_marker: "RECON_SANITIZER"`。
     - 阶段 B 结束时检测 `phase_marker: "RECON_STACK_SCAN"`。
     - 动态阶段再启用 Deep Analysis/Control-Flow 提示。
   - 采用宽松 parser 校验输出，减少因 Markdown 细节导致的循环。
4. **假设模板示例更新**
   - 提供更具体的示例（如 uninitialized `data.u.next` vs use-after-free）帮助模型区分，但保持通用性，避免实例绑定。
   - 指导模型在描述中使用关键词（uninitialized、type confusion、lifecycle 等）增强可读性。

## 后续工作
- 在新对话中重新加载配置与 hook，完成提示词、阶段标记、校验逻辑的修改。
- 运行短轨迹验证 Recon Survey 是否压缩至若干回合内完成；若仍冗长，再迭代精简。
