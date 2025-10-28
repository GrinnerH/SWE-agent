# VulnTree 当前架构说明（v3.11）

本说明聚焦系统最新状态，围绕四个维度展开：**Agent 设计、Unified Memory 与上下文管理、规划与推理理念、反思与自修复机制**。目标是让维护者在同一文档内理解所有核心组件如何协同工作。

**v3.11 更新（2025-10-26）**：
- **🔧 [CRITICAL FIX] HypothesisDrivenSelectorV2**：修复 v3.10 基于 reward 选择的严重bug，改为深度优先选择
- **🔄 [NEW] 假设切换信号机制**：Plan Agent 通过 UpdatePlan 显式触发假设切换，Selector 检测信号
- **🎯 [NEW] LLM 辅助切换决策**：可选的 LLM 分析 MCTS 结构、假设状态、TodoList 来决定是否切换
- **📋 [UPDATE] Plan Agent 提示词增强**：新增 "Hypothesis Switching Protocol"，强调高切换门槛
- **🔍 [UPDATE] 死胡同检测优化**：更严格的阈值，避免过早放弃探索路径

**v3.10 更新（2025-10-25）**：
- 优化 UpdatePlan 元操作评分策略，降低对 Selector 的影响
- **新增 meta-operation 节点过滤机制**，完全阻止 Selector 选择规划节点
- 确认 Serena 工具集成，新增 `get_symbols_overview` 符号概览工具
- 新增 `HypothesisDrivenSelector` 假设驱动选择器（已在 v3.11 废弃，替换为 V2）



## 1. 系统总体视图

```
┌────────────────────────────────────────────────────────────────┐
│  搜索控制层：SearchTree (MCTS)                                  │
│  ├─ 节点选择 / 扩展 / 模拟 / 回传                               │
│  └─ 调度 PlanAgent 执行具体动作                                 │
├────────────────────────────────────────────────────────────────┤
│  决策层：PlanAgent                                              │
│  ├─ 构造 LLM 上下文（系统 prompt + plan_view）                   │
│  ├─ 执行动作（Read/Find/Task/DockerScript/UpdatePlan/...）       │
│  ├─ 自动监控失败并触发 CounterfactualBacktrack                   │
│  └─ 调用 Sub-Agent（Phase0 / 专项任务）                          │
├────────────────────────────────────────────────────────────────┤
│  状态层：Unified Memory                                          │
│  ├─ PlanManager：todo、假设、counterfactual 标记                 │
│  ├─ Blackboard：节点事件、VAS 状态、初始 triage 等               │
│  ├─ Views：聚合结构化上下文供 PlanAgent / Selector 等使用         │
│  └─ Knowledge/ProcessMemory：工具结果分层缓存、重复过滤           │
├────────────────────────────────────────────────────────────────┤
│  行动层：行动执行与工具调用                                      │
│  ├─ Phase0 Sub-Agent：生成 Phase 0 Exploration Blueprint         │
│  ├─ Serena/Read/Find 工具：代码浏览与静态分析                     │
│  ├─ DockerScript/Debugger：PoC 执行与验证                        │
│  └─ Counterfactual meta-actions：回退与策略调整                   │
└────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent 设计

### 2.1 PlanAgent（核心决策体）
- **职责**：从 PlanManager 获取当前目标与假设，将其转化为 LLM prompt，选择最合适的工具动作，处理返回结果并更新计划。
- **关键能力**：
  - 使用 `plan_view` 注入假设上下文、行动轨迹、开放问题。
  - 执行动作后自动调用 `_auto_counterfactual_backtrack()` 统计连续失败。
  - 处理 `[Auto] counterfactual` todo，引导 LLM 通过 `UpdatePlan` 写入新的探索路径。

### 2.2 Sub-Agent（Phase0 Reconnaissance）

#### 2.2.1 系统提示与桥接模板
- **宪法式系统提示**：默认加载 `prompts/sub_agent/phase0_system_prompt_v4.prompt`（ASCII 版）。内容覆盖因果约束、动态分级、控制流表、报告模板等核心规则。
  - **v1.0 新增（2025-01-22）**：
    - Deep Analysis Triggers（5个模式触发器）
    - Evidence Efficiency Management（证据注册表与搜索预检）

- **桥接提示模板**（阶段性指令）：
  - `prompts/sub_agent/bridges/post_round0_guidance.prompt` **[已增强]**
    - 新增：Reasoning State Snapshot（推理状态快照）
    - 要求输出 [PF] Proven Facts、[RH] Refuted Hypotheses、[AH] Active Hypotheses
  - `prompts/sub_agent/bridges/round3a_origin_validation.prompt` **[已增强]**
    - 新增：Reasoning State Update（状态更新要求）
    - 指导何时更新 [PF]、[RH]、[AH]
  - `prompts/sub_agent/bridges/round3b_lifecycle_validation.prompt` **[完全重写]**
    - 新架构：Dual-Path + Pivot Checkpoint
    - Primary Path: Lifecycle / Value Origin
    - Pivot Checkpoint: 证据评分机制（Score = Tier-1×2 + Tier-2×1）
    - Alternative Paths: Structure Overwrite / Type Safety / Value Generation
  - `prompts/sub_agent/bridges/round3_decision_prompt.prompt`
  - `prompts/sub_agent/bridges/final_gate.prompt` **[已增强]**
    - 新增：Anti-Regression Check（反向一致性检查）
    - Check 1: 新假设 vs 已驳斥假设
    - Check 2: 新证据 vs 已证明事实
    - Check 3: 报告内部自洽性
  - `prompts/sub_agent/bridges/validation_failed_guidance.prompt`

#### 2.2.2 推理状态管理（v1.0 新增）
Phase 0 现在维护结构化推理状态，防止逻辑倒退：

**状态类别：**
- **[PF-X] Proven Facts**：已证明事实，不可推翻
  - 判定标准：≥2个Tier-2证据，Position=Before/Same，Execution=Yes
  - 示例：`[PF-1] Object allocated at file.c:100 | Evidence: E-5, E-6 | Proven in: Round 3a`

- **[RH-X] Refuted Hypotheses**：已驳斥假设，不可复活
  - 判定标准：Tier-2证据直接矛盾核心声明，或必要前提被证伪
  - 示例：`[RH-2] Uninitialized pointer | Reason: Initialization proven | Evidence: E-5, E-6 | Refuted in: Round 3a`

- **[AH-X] Active Hypotheses**：活跃假设，正在调查
  - 标记为 primary（最高置信度）或 fallback（备选）

**状态持久化：** 从 Round 1-2 开始，每个阶段结束后强制声明状态快照，状态在后续轮次中持续追踪。

#### 2.2.3 深度分析触发器（v1.0 新增）
系统提示中定义5个基于代码模式的触发器，遇到匹配模式时强制深入分析：

| 触发器 | 模式 | 强制问题 | 适用场景 |
|--------|------|---------|---------|
| Trigger 1 | `struct_var = value` | 覆写了什么？之前状态？值来源？覆写后果？ | 结构体/union整体赋值 |
| Trigger 2 | `union.field_A` | union所有字段？写入/读取哪个？是否匹配？ | Union字段访问 |
| Trigger 3 | `expr->field->field` | 每级类型？中间有效性？有验证吗？ | 多级指针解引用 |
| Trigger 4 | `callback(value)` | 值类型？生命周期？类型契约？有验证？ | 跨上下文值传递 |
| Trigger 5 | `if (cond) {...}` | 条件语义？分支假设？崩溃路径？边界情况？ | 条件分支与假设 |

**执行协议：** 每次Read/Search后扫描模式，匹配则输出 `[DEEP DIVE TRIGGER X ACTIVATED]` 并回答强制问题，只有回答完毕才能继续下一工具调用。

#### 2.2.4 Pivot机制（v1.0 新增）
Round 3b 使用双路径+检查点结构，当主路径证据不足时自动切换替代路径：

**Phase 1: Primary Path**
- Path A: Lifecycle Event Analysis（对象已分配+初始化时激活）
- Path B: Value Origin Analysis（未找到分配或未初始化时激活）

**Pivot Checkpoint（强制执行）**
```
证据评分 = (Tier-1数量 × 2) + (Tier-2数量 × 1)
决策规则：
- 得分 ≥ 3：主路径成功，跳过替代路径
- 得分 1-2：主路径弱，执行1次目标搜索后重评
- 得分 = 0：主路径失败，必须激活替代路径
```

**Phase 2: Alternative Paths（得分<3时激活）**
- Alternative A: Structure Overwrite Analysis（失败指针在struct/union中）
- Alternative B: Type Safety Analysis（涉及union/void*/类型转换）
- Alternative C: Value Generation Logic Analysis（失败值来自函数返回/参数）

**路径选择逻辑：** 基于失败对象的可观察特征（是否在结构中、是否从函数返回）自动选择。

#### 2.2.5 反向一致性验证（v1.0 新增）
Final Gate 增加强制反向检查，防止逻辑倒退：

**验证顺序：**
1. **Anti-Regression Check**（新增，优先级最高）
   - 扫描最终报告假设 vs [RH]列表，检测语义相似度
   - 扫描最终报告证据 vs [PF]列表，检测矛盾
   - 检查报告内部自洽性
   - 如发现冲突：强制撤回或重新分析原始证明

2. **Evidence Integrity Check**（原有）
3. **Causality Check**（原有）
4. **Output Hygiene**（原有）

**冲突处理：** 检测到冲突时输出 `Final gate failed. Logical conflict detected: <description>` 并返回分析阶段，不允许生成最终报告。

- `SubAgentExecutor` 内部维护 Phase 0 状态机，驱动"司令官"式对话节奏：

| 状态 | 触发输出 | 指令 / 出口 |
|------|----------|-------------|
| `awaiting_round0_output` | 子代理收到初始指令，仅执行 Round 0（Sanitizer Analysis），以 `Round 0 complete. Awaiting further instructions.` 收尾 | 解析候选表和关键信号 → 注入 `post_round0_guidance`，进入 `awaiting_round1_2_output` |
| `awaiting_round1_2_output` | 需要 `## Immediate Cause (Round 1)` + `## Origin Trace (Round 2)` + 终止句 | 注入 `round3a_origin_validation.prompt`，缓存关键段落，进入 `awaiting_round3a_output` |
| `awaiting_round3a_output` | Round 3a 输出必须以 `Round 3a (Origin) complete. Awaiting lifecycle guidance.` 结束 | 注入 `round3b_lifecycle_validation.prompt`，进入 `awaiting_round3b_output` |
| `awaiting_round3b_output` | Round 3b 输出必须以 `Round 3b (Lifecycle) update ready. Awaiting next directive.` 结束 | 注入 `round3_decision_prompt.prompt` 请求 A/B 选择，状态转为 `awaiting_round3b_decision` |
| `awaiting_round3b_decision` | 仅接受 `A` / `B` | `A` → 再次发送 `round3b_lifecycle_validation.prompt`，回到 `awaiting_round3b_output`；`B` → 注入 `final_gate.prompt`，进入 `awaiting_final_gate` |
| `awaiting_final_gate` | 等待终局自检结果 | 若返回 `Final gate failed...` → 注入 `validation_failed_guidance.prompt`，回滚至 `awaiting_round3b_output`；否则允许输出 `# FINAL REPORT`，终止 |

**每轮输入/预期输出标准**

- **Round 0（Sanitizer Deep Dive）**
  - *输入指令*：仅执行 Round 0，严禁读代码或查 lifecycle。
  - *理想输出*：`## Sanitizer Analysis` + `## Candidate Root Causes (Unranked Guesses)` 表；所有 Status=`?`；结尾行 `Round 0 complete. Awaiting further instructions.`
- **Round 1（Crash Context）**
  - *输入指令*：读取崩溃点 ±10 行，识别 deref / 失败变量，不推生命周期结论；
  - *理想输出*：`## Immediate Cause (Round 1)` 段落，给出操作、对象、失败条件。
- **Round 2（Origin Trace）**
  - *输入指令*：追踪失败变量来源，限定在 provenance 问题解决前禁止查 `free/delete`；
  - *理想输出*：`## Origin Trace (Round 2)` 段落，列出赋值链、确认路径、开放疑问；结尾加 `Round 1-2 complete. Awaiting further instructions.`
- **Round 3a（Allocation / Origin）**
  - *输入指令*：仅追踪分配与赋值链，禁止搜索 `free`；
  - *理想输出*：`### Question / Findings / Table Update / Hypothesis Impact`，结尾 `Round 3a (Origin) complete. Awaiting lifecycle guidance.`
- **Round 3b（Lifecycle）**
  - *输入指令*：集中寻找释放/失效事件，验证执行顺序和数据同一性；
  - *理想输出*：同样的四段结构，结尾 `Round 3b (Lifecycle) update ready. Awaiting next directive.` 之后根据 A/B 决策进入下一步。
- 状态机确保每一轮新指令都紧贴子代理最新输出，使其注意力集中在当前阶段的强制性任务上，减少单体提示的遗忘问题。
- 生成的 **Phase 0 Exploration Blueprint** 仍由 PlanManager 解析，映射为假设集与初始 todo。
- 最终 Blueprint 强制包含 `## Keyframe Timeline`：按“Crash → Propagation → Origin → Lifecycle/Type”顺序列出 3-5 个关键帧，逐帧写明证据 ID 及约束的假设，用于 PlanManager 和 Phase1 快速建立 sink-to-source 执行路径。

### 2.3 Serena 工具集成（v3.10 更新）

VulnTree 集成了 Serena 代码分析工具集，提供语义级别的代码理解能力：

#### 2.3.1 核心工具
- **`find_symbol`**：基于符号路径搜索代码实体（类、方法、函数等）
  - 支持相对路径（`class/method`）和绝对路径（`/class/method`）匹配
  - 可限定文件/目录范围（`relative_path` 参数）
  - 支持深度遍历子符号（`depth` 参数）

- **`get_symbols_overview`** **[v3.10 新增]**：获取文件顶层符号概览
  - 用途：首次探索新文件时快速了解结构
  - 返回：顶层类、函数、变量等符号的元数据列表
  - 推荐：作为深入分析前的"预览"工具，避免盲目读取大文件

- **`find_referencing_symbols`**：查找符号引用关系
  - 返回：引用位置 + 代码片段
  - 用于：追踪函数调用、变量使用等

- **`read_file`**：读取文件内容（支持行范围）
- **`search_for_pattern`**：基于正则表达式的模式搜索
- **`list_dir`** / **`find_file`**：文件系统浏览
- **`execute_shell_command`**：执行 shell 命令

#### 2.3.2 工具选择策略
- **符号优先**：已知符号名时优先使用 `find_symbol` / `find_referencing_symbols`
- **概览优先**：探索新文件时先用 `get_symbols_overview` 获取结构
- **模式搜索**：不确定符号名时使用 `search_for_pattern`
- **文件读取**：只在需要完整上下文或符号工具不适用时使用 `read_file`

#### 2.3.3 集成细节
- 工具注册：`moatless/actions/__init__.py` 的 `SERENA_TOOL_NAMES` 集合
- 适配层：`moatless/actions/serena_adapter.py` 将 Serena 工具转为 VulnTree Action
- 智能过滤：超长内容自动调用 LLM 进行上下文感知过滤（`ContextAwareLLMFilter`）

### 2.4 其他辅助 Agent / Action
- `CounterfactualBacktrack`（meta-operation）：当 PlanAgent 发现路径失败时自动注入。
- `Task` 子代理：在 PlanAgent 需要大规模信息收集时调用，执行完毕后通过 `structured_result` 写回。

---

## 3. Unified Memory 与上下文管理

### 3.1 PlanManager（`moatless/memory/plan_manager.py`）
- **数据结构**：
  - `_hypotheses`：记录 `priority`、`current_understanding`、`known_facts`、`open_questions`、`suggested_steps`、`fallback_to`、`counterfactual_requested` 等。
  - `_active_hypothesis`：当前验证的假设；只有其 todo 处于解锁状态。
  - `AnalysisPlanTask`：todo 列表，包含状态、优先级、所属假设。
- **关键流程**：
  - **Phase0 解析**：`_parse_phase0_exploration_blueprint()` → `/_apply_phase0_blueprint()` 注册假设与初始任务。
  - **渐进式生成**：`apply_hypothesis_update()` 根据 `UpdatePlan` 反馈追加任务或标记假设状态。
  - **自动 Counterfactual**：在无 fallback 时调用 `_auto_counterfactual_for_hypothesis()` 创建 `[Auto] counterfactual` todo，并记下 `counterfactual_requested=True`。

### 3.2 Blackboard（`analysis_blackboard.py`）
- 维护全局运行状态：节点事件、VAS (sources/sinks/dataflow paths)、triage 结果等。
- 提供 `get_current_plan_task()`、`complete_plan_task()` 等方法给 PlanAgent 使用。

### 3.3 Views（`moatless/views.py`）
- `for_plan()` 聚合为 PlanAgent 提供的结构化上下文：
  - `hypothesis_context`（含 counterfactual 标记）。
  - `current_path_digest` / `full_path_digest` 追踪行动历史。
  - `working_plan`、VAS 状态、兄弟节点尝试等。

### 3.4 结构化结果回写（TaskResultSchema）
- 所有 Sub-Agent / 工具调用统一返回 `TaskResultSchema`（status、summary、data、is_poc、causality_id）。
- 带来的能力：
  1. **因果追踪**：`causality_id` 直接构建动作 → 结果 → 新任务的 DAG。
  2. **成果检测**：`is_poc` 让系统即时识别可执行 PoC 并切换到验证流程。
  3. **无歧义更新**：AnalysisBlackboard 按 schema 写入状态，避免再次解析自然语言。

### 3.5 LifecycleOrchestrator 与 TodoSync
- LifecycleOrchestrator 在行动执行前后调用 `start_task` / `complete_task`，确保任务状态和假设状态同步推进（日志以 `🚀/✅ [Lifecycle]` 标识）。
- TodoSync Service 将 PlanManager 的任务快照统一导出到 `analysis_artifacts["working_plan"]`，Selector、PlanAgent prompt 等组件都从同一入口获取 todo。

### 3.6 工具结果分层与重复过滤
- Unified Memory 的 `record_action_result()` 在每次行动后记录：
  - 行动类型、目标文件、reward 值、observation 摘要。
  - 派生结构化知识（例如标记已阅读代码、提取 sources/sinks）。
- 通过已记录信息避免重复阅读同一文件片段或重复执行相同命令。

---

## 4. 规划设计理念

### 4.1 分层假设驱动
- Phase0 仅输出粗颗粒假设 → PlanManager 将其存储并逐步细化。
- PlanAgent 在每次 `UpdatePlan` 时补充 `hypothesis_update` / `new_open_questions` / `new_suggested_steps`，PlanManager 将其转化为新的 todo。
- 假设状态根据证据自动流转：`pending → active → confirmed/refuted/inconclusive`。

### 4.2 渐进式任务生成
- 初始化仅有 2–3 个种子任务（崩溃点 + 关键调用者）。
- 动态任务生成遵循 “最多 3 个/次、保持粗粒度、仅在 LLM 反馈明确方向时才生成” 的原则。
- 更新入口统一为 `UpdatePlan` action，确保 PlanManager 是唯一写入点。

### 4.3 MCTS 驱动探索
- SearchTree 通过 UCT 平衡探索与利用。
- 每次模拟实际调用 PlanAgent 执行动作，reward 回写驱动树形结构向高价值路径收敛。
- Phase0 完成后自动刷新 todo，确保 SearchTree 继续沿最有希望的假设扩展。

---

## 5. 反事实与反思机制

### 5.1 连续失败回退（动作级自动触发）
- PlanAgent 维护每个节点的 `consecutive_failures`。  
- 连续 3 次失败 → 自动执行 `CounterfactualBacktrackArgs` 元操作：  
  - 指定回退深度（1–3）  
  - 给出替代假设列表（结合当前假设 & Phase0 fallback）  
  - 重置失败计数并记录在节点属性中

### 5.2 假设级调整
- `apply_hypothesis_update()` 在发现 `found_contradiction` 或任务全部完成但无结论时：  
  - 有 fallback → `_activate_hypothesis(fallback)`  
  - 无 fallback → `_auto_counterfactual_for_hypothesis()` 创建 `[Auto] counterfactual` todo，并在 `hypothesis_context` 中设置 `counterfactual_requested=True`。
- PlanAgent 读取该 todo 后，指导 LLM 用 `UpdatePlan` 输出新的探索建议 / 替代假设。
- 两级触发对比如下：

| 级别 | 触发位置 | 条件 | 动作 | 频率限制 |
|------|---------|------|------|-----------|
| Level 1（动作级） | PlanAgent `_auto_counterfactual_backtrack()` | 同一节点连续 3 次失败，且 observation 非终止 | 注入 `CounterfactualBacktrackArgs`，建议回退深度与替代假设 | 每次回退后重置计数 |
| Level 2（假设级） | PlanManager `apply_hypothesis_update()` | a) `found_contradiction=True`；b) 当前假设所有任务完成且 `open_questions` 为空（验证枯竭）；c) 所有假设均 `refuted/inconclusive` | `_auto_counterfactual_for_hypothesis()` 生成 `[Auto] counterfactual` todo，要求 LLM 用 `UpdatePlan` 推出新方向 | `counterfactual_requested` 避免重复触发 |

### 5.3 反思与奖励反馈
- `RewardFeedbackGenerator` 根据动作结果、工具输出和计划完成度给出即时奖励。
- Selector / ValueFunction 基于 reward、路径长度、工具多样性挑选下一个节点，避免陷入局部循环。

### 5.4 LATS 风格反思
- `VulnReflectionOptimizer`（`moatless/reflection_optimizer.py`）在关键任务失败后被触发，回溯失败轨迹并生成高层反思写入 Unified Memory。
- 反思内容由 BackgroundPlanUpdater/PlanAgent 读取，可用于调整假设、添加新任务或修改策略。
- `evaluate_SEC-bench.py` 初始化流程会创建该优化器；相关日志以 `🧠 [ReflectionOptimizer]` 开头。

---

## 6. Selector 策略与节点选择（v3.10 新增）

### 6.1 Selector 概述
Selector 负责在 MCTS 搜索树中选择下一个扩展节点。VulnTree 提供多种 Selector 策略以适应不同探索模式：

| Selector 类型 | 策略 | 适用场景 |
|--------------|------|---------|
| `HeuristicStageAwareSelector` | 基于阶段启发式规则 | 快速原型、简单任务 |
| `LLMSelector` | LLM 驱动的智能选择 | 复杂决策、需要推理 |
| `FeedbackSelector` | 基于历史反馈优化 | 需要学习优化的场景 |
| `IntelligentLLMSelector` | 增强的 LLM 选择器（含扩展决策） | 高级探索控制 |
| **`HypothesisDrivenSelectorV2`** **[v3.11 重大修复]** | 深度优先 + 假设忠诚 + 高切换门槛 | **假设验证、深度探索（推荐）** |
| ~~`HypothesisDrivenSelector`~~ ~~[v3.10 已废弃]~~ | ~~基于 reward 选择（bug）~~ | ~~已被 V2 替代~~ |

### 6.2 HypothesisDrivenSelectorV2 假设驱动选择器（v3.11 重大修复）

#### 6.2.1 设计动机与问题修复

**v3.10 版本的严重问题**：
- HypothesisDrivenSelector 基于 **reward 分数**选择节点，导致浅层高 reward 节点被反复扩展
- 示例问题：Node1(depth=1, reward=85) 被选择 2 次，而 Node2(depth=2, reward=65) 被放弃
- 违背了"深度优先探索假设"的核心原则
- 过程中的低价值行动很正常，但原实现会因此回退到浅层节点

**v3.11 根本性修复（HypothesisDrivenSelectorV2）**：
- **深度优先选择**：节点评分以深度为主导因素，reward 影响极小
- **高切换门槛**：只在显式信号、确认死路或 LLM 推荐时切换假设
- **LLM 辅助决策**：可选地使用 LLM 分析 MCTS 结构、假设状态、TodoList 来决定是否切换
- **与 Plan Agent 协同**：Plan Agent 通过 UpdatePlan 显式触发假设切换

#### 6.2.2 核心机制：深度优先选择（PRIMARY FIX）

**评分公式（v3.11 新）**：
```python
# PRIMARY: 深度主导（乘以 10 倍权重）
depth_score = node.get_depth() * 10.0

# SECONDARY: 假设对齐奖励（降低至 5.0）
alignment_bonus = 5.0 if hypothesis_aligned else 0.0

# TERTIARY: reward 影响极小（限制在 0-3 范围）
reward_score = min(node.reward.value / 30.0, 3.0)

# 总分：深度主导
total_score = depth_score + alignment_bonus + reward_score
```

**示例对比**：

| 节点 | 深度 | Reward | 对齐 | v3.10 评分 | v3.11 评分 | 选择结果 |
|------|-----|--------|------|-----------|-----------|---------|
| Node1 | 1 | 85 | ✓ | **100.0** (85+15) | 18.0 (10+5+3) | v3.10: ✓ v3.11: ✗ |
| Node2 | 2 | 65 | ✓ | 80.0 (65+15) | **28.0** (20+5+3) | v3.10: ✗ v3.11: ✓ |

**结果**：v3.11 正确选择深层节点 Node2，避免在浅层反复扩展。

#### 6.2.3 假设切换协议（v3.11 新增）

**切换触发条件（ONLY 以下情况）**：

1. **显式切换信号**（Plan Agent 调用 UpdatePlan）
   ```python
   UpdatePlan(
       found_contradiction=True,  # 关键标志！
       hypothesis_id="H1_fallback_npd",
       hypothesis_update="SWITCH: Demoting PRIMARY, promoting FALLBACK..."
   )
   # 触发：blackboard.hypothesis_switch_requested = True
   ```

2. **确认死路**（更严格的阈值）
   - 连续 3 个终端节点（所有路径耗尽）
   - 同一节点被选择 4 次（无限循环）
   - 8 层深度无任何高 reward（最大 reward < 70）

3. **LLM 推荐切换**（可选，需要 completion model）
   - 分析 MCTS 树结构、假设状态、TodoList
   - 判断当前假设是否严重矛盾或无法推进

**Plan Agent 提示词要求**：
- `prompts/plan_agent/system_prompt_v7.prompt:75-135` 中新增 "🔄 CRITICAL: Hypothesis Switching Protocol"
- 明确要求：**HIGH THRESHOLD FOR SWITCHING**
- 强制使用 UpdatePlan 切换（with `found_contradiction=true`）

#### 6.2.4 假设切换信号流程（v3.11 新增）

```
┌─────────────────────────────────────────────────────┐
│ 1. Plan Agent (LLM 判断需要切换)                     │
│    - 分析证据发现严重矛盾                             │
│    - 或所有探索路径确认死路                           │
└──────────────────┬──────────────────────────────────┘
                   ↓ UpdatePlan 调用
┌─────────────────────────────────────────────────────┐
│ 2. UpdatePlan Action                                 │
│    - _set_hypothesis_switch_signal()                │
│    - 检测 found_contradiction=True                  │
│    - 或 hypothesis_id 改变                          │
│    - 设置信号:                                      │
│      blackboard.hypothesis_switch_requested = True  │
│      unified_memory.hypotheses.switch_requested = True │
│                                                      │
│    日志: 🔄 [Hypothesis Switch] ✅ Switch signal activated │
└──────────────────┬──────────────────────────────────┘
                   ↓ 下次 MCTS iteration
┌─────────────────────────────────────────────────────┐
│ 3. HypothesisDrivenSelectorV2.select()              │
│    - _check_explicit_switch_signal()                │
│    - 检测 blackboard.hypothesis_switch_requested   │
│    - 决策: SWITCH_EXPLICIT                          │
│    - 执行: _select_alternative_branch_node()       │
│    - 重置死路检测器                                  │
│                                                      │
│    日志: 🧭 Explicit hypothesis switch detected (UpdatePlan) │
└──────────────────┬──────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────────────────┐
│ 4. 结果                                              │
│    - 选择非当前假设的节点                             │
│    - 开始新假设分支的深度优先探索                      │
└─────────────────────────────────────────────────────┘
```

#### 6.2.5 死胡同检测机制（v3.11 更严格）

**检测器 1：连续终端节点检测**（新）
```python
consecutive_terminal_threshold = 3  # 连续终端节点数
```
- 触发条件：连续 3 个节点都是终端节点（所有路径耗尽）
- 目的：识别假设分支完全探索完毕

**检测器 2：节点重复选择检测**（提高容错）
```python
max_same_node_selections = 4  # 从 3 提高到 4
```
- 触发条件：同一节点被选择超过 4 次
- 目的：防止无限循环，但允许合理的重试

**检测器 3：深度无高 reward 检测**（更严格）
```python
max_depth_without_high_reward = 8  # 从 5 提高到 8
high_reward_threshold = 70  # 新增：高 reward 阈值
```
- 触发条件：最近 8 步无任何节点 reward >= 70
- 目的：识别假设可能根本错误的情况

**对比 v3.10**：

| 检测器 | v3.10 | v3.11 | 变化 |
|--------|-------|-------|------|
| 低 reward 检测 | 连续 3 次 < 30 分 | ❌ 移除 | 过于敏感 |
| 终端节点检测 | ❌ 无 | ✅ 连续 3 个 | 新增 |
| 重复选择检测 | 3 次 | 4 次 | 提高容错 |
| 深度检测 | 5 步无改善 | 8 步无高 reward | 更严格 |

#### 6.2.6 LLM 辅助切换决策（v3.11 新增）

**启用条件**：
```python
selector = HypothesisDrivenSelectorV2(
    completion=completion_model,  # 提供 LLM
    enable_llm_assisted_switch=True,  # 启用辅助决策
)
```

**分析内容**：
- **当前假设状态**：hypothesis_id, confidence, status
- **Plan/TodoList 状态**：active tasks, completion percentage
- **最近轨迹分析**：rewards, outcomes, depth
- **候选节点摘要**：depth, reward, hypothesis alignment

**LLM 决策提示**：
```markdown
# Hypothesis Switch Decision Analysis

## Current Situation
**Current Hypothesis**: H0_primary_uaf
**Hypothesis Confidence**: 0.95
**Hypothesis Status**: active

## Plan Status
Active Task: phase0_survey - Phase0: Three-Part Vulnerability Investigation

## Recent Trajectory Analysis
Step 1: Node1 (depth=1, reward=85.0, outcome=PROGRESS)
Step 2: Node2 (depth=2, reward=65.0, outcome=PROGRESS)

**Switching Threshold is HIGH** - only switch if:
1. Current hypothesis is severely contradicted by evidence
2. All paths in current hypothesis are confirmed dead-ends
3. Plan explicitly requests hypothesis change (UpdatePlan operation)
```

**返回决策**：
```json
{
  "should_switch": false,
  "reasoning": "Current hypothesis making incremental progress, no severe contradiction"
}
```

#### 6.2.7 使用示例（v3.11 更新）

```python
from moatless.selector.hypothesis_driven_selector_v2 import HypothesisDrivenSelectorV2

# 推荐配置：深度优先 + 高切换门槛 + LLM 辅助
selector = HypothesisDrivenSelectorV2(
    # 死胡同检测（更严格的阈值）
    enable_deadend_detection=True,
    consecutive_terminal_threshold=3,  # 需要 3 个连续终端节点
    max_same_node_selections=4,  # 允许同节点选择 4 次
    max_depth_without_high_reward=8,  # 8 层深度无高 reward

    # 假设忠诚度（降低，深度是主要因素）
    hypothesis_loyalty_bonus=5.0,  # 从 15.0 降低到 5.0

    # LLM 辅助切换决策（可选）
    completion=completion_model,
    enable_llm_assisted_switch=True,
)

# 注入 blackboard 以访问假设管理和切换信号
selector.attach_views(blackboard=blackboard)
```

**日志输出示例**：
```
🧭 [HypothesisDrivenSelectorV2] Evaluating 3 candidates
🧭 Node 1: depth=1(10.0), align=5.0, reward=3.0, total=18.0
🧭 Node 2: depth=2(20.0), align=5.0, reward=3.0, total=28.0  ← 深度主导
🧭 Selected Node 2 (depth=2, total_score=28.0)  ← 正确！
```

#### 6.2.8 集成要求（v3.11 更新）

**必需组件**：
- ✅ **假设管理**：`blackboard.unified_memory.hypotheses` 提供活跃假设
- ✅ **节点绑定**：节点通过 `properties['hypothesis_id']` 标记所属假设
- ✅ **切换信号**：
  - `blackboard.hypothesis_switch_requested` (主信号)
  - `unified_memory.hypotheses.switch_requested` (冗余信号)
- ✅ **Plan Agent 协同**：Plan agent 提示词包含切换协议（`system_prompt_v7.prompt:75-135`）

**UpdatePlan 集成**：
- `moatless/actions/update_plan.py:296-298, 699-759` 实现 `_set_hypothesis_switch_signal()`
- 当检测到 `found_contradiction=True` 或 `hypothesis_id` 改变时自动设置切换信号

**可选组件**：
- ⭕ **LLM 辅助**：`completion_model` + `enable_llm_assisted_switch=True`

#### 6.2.9 版本对比��结

| 特性 | v3.10 (HypothesisDrivenSelector) | v3.11 (HypothesisDrivenSelectorV2) |
|------|----------------------------------|-----------------------------------|
| **选择策略** | 基于 reward（错误！） | ✅ 基于 depth（正确） |
| **评分公式** | reward + 15 | depth×10 + 5 + reward/30 |
| **切换门槛** | 低 reward 即切换 | ✅ 只在显式信号/确认死路时切换 |
| **信号机制** | ❌ 无 | ✅ UpdatePlan 设置 blackboard 标志 |
| **LLM 辅助** | ❌ 无 | ✅ 可选的 LLM 切换决策分析 |
| **死路检测** | 3 种（过敏感） | ✅ 3 种（更严格阈值） |
| **Plan 协同** | ❌ 弱 | ✅ 强（提示词 + 信号流程） |
| **典型问题** | 浅层节点重复扩展 | ✅ 深度优先持续推进 |

**v3.11 修复文档**：
- 详细诊断：`docs/HYPOTHESIS_SELECTOR_FIX.md`
- 信号验证：`docs/HYPOTHESIS_SWITCH_SIGNAL_VALIDATION.md`

### 6.3 UpdatePlan 元操作评分优化（v3.10 更新）

#### 6.3.1 问题分析
**旧版本问题**：
- UpdatePlan 虽标记为 meta-operation，但仍创建节点并参与评分
- 评分范围过高（20-70 分），可能导致 Selector 倾向选择规划节点而非探索节点
- 影响任务推进效率，过度规划而探索不足

**根本原因**：
- Meta-operation 在 search_tree 中仍被创建为节点（line 974: `node.properties['is_meta_operation'] = True`）
- Value function 为其分配奖励（vuln_value.py:167-212）
- Selector 将其纳入候选节点集合

#### 6.3.2 优化策略

**评分降级（避免过度影响 Selector）**
```python
# 原评分范围：20-70 → 新评分范围：15-65

operation          旧评分    新评分    变化
─────────────────────────────────────────
create            55      → 45      (-10)
completed         60      → 55      (-5)
  + 详细笔记bonus    0      → +5     (+5)
in_progress       45      → 35      (-10)
add_item          40      → 35      (-5)
blocked           25      → 20      (-5)
```

**Hypothesis Feedback 优化**
```python
# 原策略：无上限累加 → 新策略：总 bonus 上限 10 分

found_support:         +5 → +4
found_contradiction:   +4 → +4
new_open_questions:    +2/个 (max 6) → +2/个 (max 5)
new_suggested_steps:   +2/个 (max 6) → +2/个 (max 5)

总 hypothesis_bonus:   无限制 → 上限 10 分
```

**高质量完成激励**
```python
# 新增：鼓励详细的完成笔记
if status == "completed" and len(completion_notes) >= 50:
    base_value += 5  # 额外 +5 分
```

#### 6.3.3 效果与影响

**对 Selector 的影响**：
- UpdatePlan 最高分：70 分 → 65 分（降低 7%）
- 真实探索动作（Read/Find）：可达 80-94 分
- 评分差距拉大：规划节点相对吸引力降低约 12-15%

**对任务推进的影响**：
- ✅ 减少 Selector 选择 UpdatePlan 节点的频率
- ✅ 增加选择实际探索动作（Read/Find/DockerScript）的概率
- ✅ 鼓励高质量任务完成（详细笔记 +5 分）
- ✅ 保持假设反馈的价值（hypothesis bonus 仍有 10 分空间）

**实现位置**：
- 文件：`moatless/value_function/vuln_value.py`
- 方法：`_score_update_plan_meta()` (line 167-234)
- 调用链：`get_reward()` → `_evaluate_meta_operation_reward()` → `_score_update_plan_meta()`

#### 6.3.4 Meta-Operation 节点过滤机制（v3.10 新增）

**问题升级**：
虽然降低了评分，但 UpdatePlan 节点仍然大量出现在搜索树中（见下例）：
```
Node6 (Read_fileArgs)
  ├── Node7 (UpdatePlanArgs) reward=0
  ├── Node8 (UpdatePlanArgs) reward=0
  ├── Node9 (UpdatePlanArgs) reward=0
  ├── Node10 (UpdatePlanArgs) reward=0
  └── Node11 (UpdatePlanArgs) reward=0
```
这些 reward=0 的规划节点占据了探索空间，阻碍真正的漏洞分析进展。

**根本解决方案：节点过滤机制**

在 `SearchTree._filter_meta_operation_nodes()` (line 1968-2006) 中实现双重检测：

```python
def _filter_meta_operation_nodes(self, nodes: List[Node]) -> List[Node]:
    """Filter out meta-operation nodes from candidate list"""
    filtered = []

    for node in nodes:
        # 检测1：properties 标记
        if node.properties and node.properties.get('is_meta_operation'):
            logger.debug(f"🚫 Skipping Node{node.node_id} (meta-operation)")
            continue

        # 检测2：terminal + is_exhausted 标记
        if getattr(node, 'terminal', False) and getattr(node, 'is_exhausted', False):
            if node.action_steps:
                last_action = node.action_steps[-1].action
                if hasattr(last_action.__class__, 'is_meta_operation'):
                    if last_action.__class__.is_meta_operation():
                        logger.debug(f"🚫 Skipping Node{node.node_id} (terminal meta-op)")
                        continue

        filtered.append(node)

    return filtered
```

**应用位置**（两个关键入口）：
1. **`run_search()` 主循环** (line 445-448)：
   ```python
   expandable_nodes = self.root.get_expandable_descendants()
   # 过滤掉 meta-operation 节点
   expandable_nodes = self._filter_meta_operation_nodes(expandable_nodes)
   ```

2. **`_select()` 节点选择** (line 685-688)：
   ```python
   expandable_nodes = node.get_expandable_descendants()
   # 过滤掉 meta-operation 节点
   expandable_nodes = self._filter_meta_operation_nodes(expandable_nodes)
   ```

**效果对比**：

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| UpdatePlan 节点被选中 | ✅ 频繁（占用 30-40% 选择） | ❌ 完全阻止 |
| 探索动作占比 | 60-70% | 100% |
| 树的有效节点密度 | 低（大量 reward=0 节点） | 高（仅包含探索节点） |
| 任务推进速度 | 慢（过度规划） | 快（专注探索） |

**注意事项**：
- UpdatePlan 节点仍会被**创建**（因为在 agent 执行后才检测）
- 但这些节点会被**标记为 terminal**，不会被再次选中
- 过滤器确保 Selector **永远不会选择**这些节点
- 这是一个"防御性"策略，确保即使节点被创建，也不会影响探索

---

## 7. 渐进式假设验证体系（v3.13）

### 7.1 设计动机：从"硬编码计划"到"渐进式推理"
- **旧模式**：Phase0 试图直接生成 30+ 步详细计划 → 信息不足导致误导；PlanAgent 只能机械执行，遇到偏差时无法调整。
- **新模式**：Phase0 仅提供粗颗粒假设 + 验证建议 -> Phase1 在探索过程中自然细化；计划由真实证据驱动逐步演化。
- **核心理念**：接受 Phase0 的视角有限、细节偏差可修正；将“探索 → 发现 → 更新”作为主流程而非一次性规划。

### 7.2 假设结构与演进
- `current_understanding`：记录当前假设的最新认知，随着每次 `hypothesis_update` 自然演进（例如 NULL deref → Promise 校验缺失 → njs_promise.c:1745 未加 `njs_is_valid()`）。
- `open_questions`：所有待解答问题列表；每个问题对应一个探索任务，解决后从列表移除。
- `suggested_steps`：LLM/分析所得的下一步建议，PlanManager 为 active hypothesis 动态生成 todo。
- 状态流转：`pending`（未启动）→ `active`（正在验证）→ `confirmed/refuted/inconclusive`（由 evidences & task 完成度决定）。

### 7.3 UpdatePlan 高频反馈
- UpdatePlan 不再是偶尔修 plan 的工具，而是“探索 → 反馈”的核心接口；推荐频率：每个信息收集动作 2–3 次。
- 关键字段与作用：
  - `hypothesis_update`：更新 `current_understanding`。
  - `new_open_questions` / `new_suggested_steps`：添加探索问题与粗颗粒步骤。
  - `found_support` / `found_contradiction`：驱动假设置信度与自动 fallback。
- PlanManager `apply_hypothesis_update()` 将这些反馈转化为新任务、假设状态，并在必要时触发 counterfactual。

### 7.4 演进示例（CVE-2022-32414）
1. **Phase0 输出**：Hypothesis A = “NULL pointer deref at value2->data.u.next”
2. **初始理解**：`current_understanding = "value2 deref"`；`open_questions = ["value2 来源？"]`
3. **探索步骤**：
   - Read crash site → UpdatePlan 添加 fact；解决 “value2 来源？” → 新问题 “Promise handler 如何返回？”
   - 追踪 Promise → UpdatePlan `hypothesis_update = "Promise handler 未验证 value"`，新增 suggested step “阅读 njs_promise_perform_race_handler”
4. **验证线索**：发现缺少 `njs_is_valid()` → `found_support=True`；继续产生 PoC 验证任务
5. **若证伪**：`found_contradiction=True` → 状态变为 `refuted`，自动激活 fallback 或触发 counterfactual

### 7.5 Counterfactual 与频率控制
- `counterfactual_requested`/`counterfactual_used` 标志记录每个假设是否已经触发过自动 counterfactual，避免重复骚扰 LLM。
- 当 `[Auto] counterfactual` todo 出现时，PlanAgent 必须尽快用 `UpdatePlan` 写入新的方向，否则假设保持阻塞状态。

---

## 7. 组件与代码索引

| 功能 | 位置 |
|------|------|
| Phase0 Sub-Agent Prompt | `moatless/agent/sub_agent_executor.py` |
| PlanAgent 主循环 & 自动 Counterfactual | `moatless/agent/plan_agent.py` |
| PlanManager（假设 & todo & counterfactual） | `moatless/memory/plan_manager.py` |
| UpdatePlan 扩展字段 | `moatless/actions/update_plan.py` |
| 计划视图（Plan view） | `moatless/views.py` |
| Counterfactual Backtrack Action | `moatless/actions/counterfactual_backtrack.py` |
| BackgroundPlanUpdater | `moatless/planning/background_updater.py` |
| LifecycleOrchestrator / TodoSync | `moatless/memory/unified_memory.py`, `analysis_blackboard.py` |
| TaskResultSchema 定义 | `moatless/actions/task_result_schema.py` |
| ReflectionOptimizer | `moatless/reflection_optimizer.py` |
| 系统 Prompt | `prompts/plan_agent/system_prompt_v7.prompt` |

---

## 8. 使用与维护建议

1. **保持 UpdatePlan 高频更新**：每当获得支持/反证证据、提出新问题或验证步骤，应调用 `UpdatePlan` 写回，确保 `_hypotheses` 状态及时更新。  
2. **关注 counterfactual 标记**：`hypothesis_context.counterfactual_requested=True` 表示当前假设已触发自动 counterfactual，需要尽快提交新的探索方向。  
3. **阅读 Phase0 蓝图与假设链**：PlanAgent prompt 显式展示当前假设、开放问题、fallback，执行动作前请先确认当前验证目标。  
4. **监控自动回退**：若节点出现 `counterfactual_backtrack` 属性，可参考生成的 `alternative_hypotheses`，避免重复失败。
5. **维护 Prompt 与 Views**：任何新字段需同步更新 `system_prompt_v7` 和 `views.for_plan()`，确保 LLM 接收完整上下文。

---

以上内容反映了 VulnTree 在 v3.9 阶段的最新架构设计。若新增组件或流程，推荐在本框架下增补相应章节，保持文档的一致性与可维护性。
