# VulnTree 到 SWE-agent 迁移建议

**目标**：将 VulnTree 的核心方法（假设驱动 + Sanitizer 高起点）迁移到 SWE-agent 成熟框架，简化架构（去除 MCTS 和评估器）

**日期**：2025-01-27
**版本**：v1.0

---

## 📋 目录

1. [核心理念对比](#核心理念对比)
2. [架构映射方案](#架构映射方案)
3. [假设驱动工作流设计](#假设驱动工作流设计)
4. [配置系统设计](#配置系统设计)
5. [工具扩展需求](#工具扩展需求)
6. [简化探索策略](#简化探索策略)
7. [实施路线图](#实施路线图)
8. [风险与挑战](#风险与挑战)

---

## 核心理念对比

### VulnTree 核心优势（需保留）

| 特性 | VulnTree 实现 | 核心价值 |
|------|-------------|---------|
| **假设驱动** | Phase0 Sub-Agent 生成多个候选假设，PlanManager 管理验证流程 | 结构化推理，避免盲目探索 |
| **Sanitizer 高起点** | SanitizerParser 提取 crash_location、call_stack 作为 Ground Truth | 从已知事实出发，提升效率 |
| **深度优先探索** | HypothesisDrivenSelectorV2 坚持当前假设，只在明确矛盾时切换 | 充分验证每个假设 |
| **渐进式计划生成** | UpdatePlan 动态追加任务，避免过早详细规划 | 根据实际发现调整策略 |

### SWE-agent 成熟能力（可利用）

| 特性 | SWE-agent 实现 | 迁移价值 |
|------|--------------|---------|
| **配置驱动** | YAML 定义 Agent 行为、工具、Prompt 模板 | 灵活配置，易于调试 |
| **模块化工具** | Tools bundles 自包含（config.yaml + bin/ + install.sh） | 工具复用和扩展 |
| **环境隔离** | SWE-ReX 容器化执行，自动管理 repo checkout | 安全执行，状态清理 |
| **批量处理** | run-batch 支持并行处理、进度管理、结果汇总 | 规模化评估 |

### 需删除的复杂组件

| VulnTree 组件 | 删除原因 | 替代方案 |
|-------------|---------|---------|
| **SearchTree (MCTS)** | 过度复杂，难以调试，探索策略不透明 | 线性执行 + 假设切换 |
| **VulnRewardFunction** | LLM 评估成本高，反馈延迟，不稳定 | 规则判断 + 明确的成功/失败标志 |
| **Selector** | 为 MCTS 服务，去除 MCTS 后不再需要 | Agent 自主决策下一步 |
| **Backpropagation** | MCTS 专用，与新架构不兼容 | 无需回传奖励 |

---

## 架构映射方案

### 整体架构对比

```
┌─────────────────────────────────────────────────────────────────┐
│                      VulnTree v3.11 架构                         │
├─────────────────────────────────────────────────────────────────┤
│  SearchTree (MCTS)                                               │
│    ├─ Selector: 选择节点                                         │
│    ├─ Expander: 扩展节点                                         │
│    ├─ Simulator: 执行 action                                     │
│    └─ Value Function: LLM 评估奖励                               │
│                                                                   │
│  PlanAgent                                                        │
│    ├─ 读取 plan_view（假设、todo、反思）                          │
│    ├─ 调用 LLM 生成 action                                       │
│    └─ UpdatePlan 更新假设状态                                    │
│                                                                   │
│  Unified Memory                                                   │
│    ├─ PlanManager: 假设和任务管理                                │
│    ├─ Blackboard: 全局状态                                       │
│    └─ KnowledgeBase: 发现记录                                    │
└─────────────────────────────────────────────────────────────────┘

                            ↓ 迁移到

┌─────────────────────────────────────────────────────────────────┐
│                  SWE-agent + 假设驱动架构 (新)                    │
├─────────────────────────────────────────────────────────────────┤
│  HypothesisOrchestrator (新增核心组件)                           │
│    ├─ 初始化: SanitizerParser → Phase0 Sub-Agent                │
│    ├─ 假设管理: 当前假设、fallback 列表、切换信号                │
│    └─ 状态追踪: 验证尝试次数、证据收集、矛盾检测                 │
│                                                                   │
│  MainAgent (基于 SWE-agent Agent)                                │
│    ├─ 系统 Prompt: 注入当前假设、已知发现、验证目标              │
│    ├─ Action 循环: 线性执行（Read/Find/Task/DockerScript）      │
│    └─ 结果处理: 更新 HypothesisOrchestrator、检测成功/失败       │
│                                                                   │
│  StateManager (简化的 Blackboard)                                │
│    ├─ current_hypothesis: 当前验证的假设                         │
│    ├─ discoveries: 已知发现列表                                  │
│    ├─ verification_attempts: 验证历史                            │
│    └─ sanitizer_info: Ground Truth 锚点                          │
│                                                                   │
│  Tools (扩展 SWE-agent tools)                                    │
│    ├─ tools/secb_poc: PoC 提交工具（已有）                       │
│    ├─ tools/hypothesis_switch: 假设切换工具（新增）             │
│    └─ tools/sanitizer_analysis: Sanitizer 分析工具（新增）      │
└─────────────────────────────────────────────────────────────────┘
```

### 组件映射表

| VulnTree 组件 | SWE-agent 映射 | 实现方式 |
|-------------|--------------|---------|
| **SearchTree + MCTS** | ❌ 删除 | 改为 MainAgent 线性执行循环 |
| **PlanManager** | `HypothesisOrchestrator` | Python 类，管理假设状态 |
| **Phase0 Sub-Agent** | `SubAgent` (独立进程) | 调用 Task tool 执行，返回结构化假设 |
| **UpdatePlan** | `hypothesis_switch` tool | 显式工具调用，触发假设切换 |
| **VulnRewardFunction** | ❌ 删除 | 改为规则判断（检测 PoC 成功标志） |
| **Blackboard** | `StateManager` | 简化的状态存储，JSON 序列化 |
| **SanitizerParser** | `sanitizer_analysis` tool | 工具化，可在 Agent 内调用 |
| **Knowledge/Discoveries** | `properties` (observation 属性) | 利用 SWE-agent 内置机制 |

---

## 假设驱动工作流设计

### 核心流程

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 0: 初始化与假设生成                                         │
├─────────────────────────────────────────────────────────────────┤
│  1. 解析 Sanitizer 报告                                          │
│     - 工具: sanitizer_analysis                                   │
│     - 输出: crash_location, call_stack, error_type               │
│     - 存储到: StateManager.sanitizer_info                        │
│                                                                   │
│  2. 生成初始假设                                                  │
│     - 工具: Task (调用 Phase0 Sub-Agent)                         │
│     - 输入: Sanitizer info + Ground Truth 指导                   │
│     - 输出: 3-5 个候选假设（JSON 格式）                          │
│       {                                                          │
│         "H0_primary_uaf": {                                      │
│           "description": "Promise reaction UAF",                │
│           "priority": 1,                                         │
│           "suggested_steps": ["Read njs_promise.c:1757", ...], │
│           "expected_evidence": "缺少 njs_is_valid() 检查"       │
│         },                                                       │
│         "H1_fallback_npd": { ... }                              │
│       }                                                          │
│     - 存储到: HypothesisOrchestrator.hypotheses                  │
│                                                                   │
│  3. 激活 Primary 假设                                            │
│     - HypothesisOrchestrator.activate_hypothesis("H0_primary")  │
│     - 更新 Agent Prompt 注入当前假设上下文                       │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: 假设验证循环 (深度优先)                                 │
├─────────────────────────────────────────────────────────────────┤
│  While 当前假设未确认 AND 未达到迭代限制:                        │
│                                                                   │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ 4. Agent 执行验证步骤                                    │ │
│    │    - 根据 current_hypothesis.suggested_steps 执行       │ │
│    │    - 可用工具: Read, Find, Task, DockerScript           │ │
│    │    - 每个 action 后更新 discoveries                     │ │
│    └─────────────────────────────────────────────────────────┘ │
│                          ↓                                       │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ 5. 检测验证结果                                          │ │
│    │    - ✅ PoC 成功: 标记假设为 CONFIRMED → 提交结果       │ │
│    │    - ❌ 发现矛盾: 触发 hypothesis_switch               │ │
│    │    - ⏳ 信息不足: 继续收集证据                          │ │
│    └─────────────────────────────────────────────────────────┘ │
│                          ↓                                       │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │ 6. 假设切换决策 (高门槛)                                 │ │
│    │    触发条件 (满足任一):                                  │ │
│    │    - Agent 显式调用 hypothesis_switch 工具              │ │
│    │    - 连续 5 次验证失败 (DockerScript 无法触发漏洞)     │ │
│    │    - 发现明确矛盾证据 (如：已证明对象已初始化)          │ │
│    │                                                           │ │
│    │    切换流程:                                              │ │
│    │    1. 标记当前假设为 REFUTED                            │ │
│    │    2. 记录反驳原因                                       │ │
│    │    3. 激活 fallback 假设                                │ │
│    │    4. 清空 verification_attempts                        │ │
│    │    5. 更新 Agent Prompt                                 │ │
│    └─────────────────────────────────────────────────────────┘ │
│                                                                   │
│  End While                                                        │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: 结果提交                                                │
├─────────────────────────────────────────────────────────────────┤
│  7. 生成最终报告                                                 │
│     - 已确认假设的验证路径                                       │
│     - 成功的 PoC 代码                                            │
│     - 关键证据和推理链                                           │
│                                                                   │
│  8. 提交                                                         │
│     - 工具: submit_poc (PoC 模式)                                │
│     - 工具: submit_patch (Patch 模式)                            │
└─────────────────────────────────────────────────────────────────┘
```

### 假设状态机

```
           ┌─────────┐
           │ PENDING │  (Phase0 生成的候选假设)
           └────┬────┘
                │
                │ activate_hypothesis()
                ▼
           ┌─────────┐
           │ ACTIVE  │  (当前正在验证)
           └────┬────┘
                │
       ┌────────┼────────┐
       │        │        │
       │ PoC    │ 矛盾   │ 超时/限制
       │ 成功   │ 证据   │
       ▼        ▼        ▼
  ┌──────────┐ ┌──────────┐ ┌──────────────┐
  │CONFIRMED │ │ REFUTED  │ │ INCONCLUSIVE │
  └──────────┘ └──────────┘ └──────────────┘
       │            │              │
       │            │              │
       │       切换到 fallback      │
       │            │              │
       ▼            ▼              ▼
    提交结果      激活下一个假设    尝试下一个假设
```

### 关键设计决策

#### 决策 1：假设切换的高门槛

**原则**：坚持当前假设，只在明确信号时切换

**切换触发条件（必须满足以下之一）**：

1. **Agent 显式请求**
   ```python
   # Agent 调用工具
   hypothesis_switch(
       current_hypothesis_id="H0_primary_uaf",
       reason="发现 Promise handler 实际有 validation 检查",
       next_hypothesis_id="H1_fallback_npd"
   )
   ```

2. **确认死路**（自动检测）
   - 连续 5 次 DockerScript 执行失败（无法触发漏洞）
   - 所有 suggested_steps 已执行完毕，但未找到预期证据
   - 发现直接矛盾的代码（如：假设"缺少检查" → 实际找到检查代码）

3. **迭代限制**（兜底）
   - 当前假设验证超过 30 次 action，仍无进展

**不触发切换的情况**：
- ❌ 单次 action 失败（如文件未找到）
- ❌ 中等 reward（如找到部分相关代码）
- ❌ 探索路径深度增加

#### 决策 2：Sanitizer 作为 Ground Truth 锚点

**原则**：所有分析从已知事实出发

**实现方式**：

1. **强制首个 action 为 sanitizer_analysis**
   ```yaml
   # config/secb_hypothesis_driven.yaml
   agent:
     templates:
       initial_step_requirement: |
         **IMPORTANT**: Your first action MUST be:
         sanitizer_analysis()

         Extract crash location, call stack, and error type.
         Use this Ground Truth as the starting point for all exploration.
   ```

2. **将 Sanitizer info 注入所有 Prompt**
   ```markdown
   ## Ground Truth from Sanitizer Report

   - **Error Type**: null-pointer-dereference
   - **Crash Location**: /home/.../njs_vmcode.c:802
   - **Crash Function**: njs_vmcode_interpreter
   - **Call Stack** (top 5):
     1. njs_vmcode.c:802 (njs_vmcode_interpreter)
     2. njs_async.c:96 (njs_await_fulfilled)
     3. njs_promise.c:1171 (njs_promise_reaction_job)
     ...

   **IMPORTANT**: Start your analysis from these known locations.
   DO NOT blindly search the entire codebase.
   ```

3. **Phase0 Sub-Agent 强制使用 Sanitizer info**
   ```python
   # Phase0 Sub-Agent prompt 模板
   system_prompt = f"""
   You are analyzing a vulnerability with the following Ground Truth:

   Crash Location: {sanitizer_info['crash_location']}
   Error Type: {sanitizer_info['error_type']}
   Call Stack: {sanitizer_info['call_stack']}

   Based on ONLY the information above, generate 3-5 hypotheses about the root cause.

   Each hypothesis must:
   1. Reference specific locations from the call stack
   2. Explain why this location could cause the observed crash
   3. Provide concrete verification steps (e.g., "Read file.c:line")
   """
   ```

#### 决策 3：去除 MCTS，使用线性执行

**原则**：简化探索策略，提升可预测性

**对比**：

| 特性 | MCTS (VulnTree v3.11) | 线性执行 (迁移后) |
|------|----------------------|------------------|
| **节点选择** | UCB/LLMSelector 评估所有候选 | Agent 自主决定下一步 |
| **探索策略** | 树搜索，回溯到高价值节点 | 深度优先，沿当前假设推进 |
| **状态管理** | Node 快照，复杂的恢复逻辑 | StateManager 简单状态 |
| **回退机制** | Backpropagation 更新所有祖先 | 假设切换时清空历史 |
| **可调试性** | 难以追踪决策路径 | 线性日志，易于理解 |

**线性执行循环**：

```python
# 伪代码：MainAgent 执行循环
def run_hypothesis_verification():
    # 1. 初始化
    hypothesis_orchestrator = HypothesisOrchestrator()
    hypothesis_orchestrator.initialize_from_sanitizer(sanitizer_report)

    current_hypothesis = hypothesis_orchestrator.get_active_hypothesis()

    # 2. 验证循环
    for iteration in range(max_iterations):
        # 2.1 构造 Agent prompt（注入当前假设）
        prompt = build_prompt_with_hypothesis(
            hypothesis=current_hypothesis,
            discoveries=state_manager.discoveries,
            verification_attempts=state_manager.verification_attempts
        )

        # 2.2 Agent 生成 action
        action = agent.generate_action(prompt)

        # 2.3 执行 action
        observation = execute_action(action)

        # 2.4 更新状态
        state_manager.add_discovery(observation)

        # 2.5 检测验证结果
        result = detect_verification_result(observation)

        if result == VerificationResult.POC_SUCCESS:
            hypothesis_orchestrator.confirm_hypothesis(current_hypothesis.id)
            return submit_poc()

        elif result == VerificationResult.CONTRADICTION:
            # 触发假设切换
            hypothesis_orchestrator.refute_hypothesis(
                current_hypothesis.id,
                reason=observation.contradiction_reason
            )
            current_hypothesis = hypothesis_orchestrator.activate_fallback()

        elif result == VerificationResult.DEADEND:
            # 确认死路，切换假设
            hypothesis_orchestrator.mark_inconclusive(current_hypothesis.id)
            current_hypothesis = hypothesis_orchestrator.activate_fallback()

        # 2.6 迭代限制保护
        if iteration >= max_iterations:
            return submit_best_effort_result()
```

---

## 配置系统设计

### 新配置文件：`config/secb_hypothesis_driven.yaml`

```yaml
# ============================================================================
# SWE-agent 假设驱动配置 (基于 VulnTree 核心理念)
# ============================================================================

agent:
  # -------------------------------------------------------------------------
  # Prompt 模板
  # -------------------------------------------------------------------------
  templates:
    system_template: |
      You are a security vulnerability analysis agent using a **hypothesis-driven approach**.

      ## Your Mission
      Verify the current hypothesis about a vulnerability's root cause by collecting evidence.

      ## Current Hypothesis (FOCUS HERE)
      **ID**: {{current_hypothesis.id}}
      **Description**: {{current_hypothesis.description}}
      **Priority**: {{current_hypothesis.priority}}
      **Expected Evidence**: {{current_hypothesis.expected_evidence}}

      ## Suggested Verification Steps
      {% for step in current_hypothesis.suggested_steps %}
      {{loop.index}}. {{step}}
      {% endfor %}

      ## Ground Truth from Sanitizer Report
      - **Error Type**: {{sanitizer_info.error_type}}
      - **Crash Location**: {{sanitizer_info.crash_location}}
      - **Crash Function**: {{sanitizer_info.crash_function}}
      - **Call Stack** (top 5):
      {% for frame in sanitizer_info.call_stack[:5] %}
        {{loop.index}}. {{frame.file}}:{{frame.line}} ({{frame.function}})
      {% endfor %}

      ## What We Already Know
      {% if discoveries %}
      ### Key Findings
      {% for discovery in discoveries %}
      {{loop.index}}. {{discovery}}
      {% endfor %}
      {% endif %}

      ## Verification History (Current Hypothesis)
      - **Attempts**: {{verification_attempts|length}}
      - **Recent Actions**:
      {% for attempt in verification_attempts[-3:] %}
        - {{attempt.action}}: {{attempt.outcome}}
      {% endfor %}

      ## 🎯 CRITICAL INSTRUCTIONS

      ### Hypothesis Loyalty
      **HIGH THRESHOLD FOR SWITCHING**: Only request hypothesis_switch when:
      1. You find direct contradictory evidence (e.g., expected missing code actually exists)
      2. You've exhausted all suggested_steps without finding expected evidence
      3. PoC attempts consistently fail (5+ times) with no progress

      **DO NOT switch** just because:
      - One action didn't find useful information
      - The analysis path seems difficult
      - You want to "try something different"

      ### Depth-First Exploration
      Follow the suggested_steps in order. Complete each step fully before moving to the next.

      ### Available Actions
      - **Read**: View file content (use for suggested_steps like "Read file.c:100-200")
      - **Find**: Search for functions/patterns (use when suggested_steps mention "find X")
      - **Task**: Delegate complex analysis to Sub-Agent
      - **DockerScript**: Write and execute PoC (use when enough evidence collected)
      - **hypothesis_switch**: Switch to fallback hypothesis (HIGH THRESHOLD!)

      ### Success Detection
      If your PoC triggers the vulnerability (crash/ASAN report), immediately call:
      submit_poc()

    instance_template: |
      {{problem_statement}}

      **Your first action MUST be**: sanitizer_analysis()
      This will extract the Ground Truth anchor points for your analysis.

    next_step_template: |
      {{observation}}

      Based on the above observation and your current hypothesis, what's your next action?

  # -------------------------------------------------------------------------
  # 模型配置
  # -------------------------------------------------------------------------
  model:
    name: "{{model_name}}"  # 通过 CLI 参数覆盖
    temperature: 0.0
    top_p: 0.95
    per_instance_call_limit: 50  # 减少迭代限制（不再需要 MCTS 扩展）
    per_instance_cost_limit: 2.0

# ============================================================================
# 工具配置
# ============================================================================
tools:
  execution_timeout: 300

  env_variables:
    WINDOW: 100              # 文件窗口大小
    OVERLAP: 2               # 窗口重叠行数

  bundles:
    # 基础工具
    - path: tools/registry             # 状态管理
    - path: tools/defaults             # 文件导航
    - path: tools/search               # 搜索功能
    - path: tools/change               # 文件编辑（Patch 模式需要）

    # SEC-bench 专用工具
    - path: tools/submit_poc           # PoC 提交

    # 新增：假设驱动专用工具
    - path: tools/hypothesis_switch    # 假设切换
    - path: tools/sanitizer_analysis   # Sanitizer 解析

  enable_bash_tool: true

  parse_function:
    type: function_calling

# ============================================================================
# 历史处理器（简化）
# ============================================================================
history_processors:
  - type: last_n_observations
    n: 10  # 保留更多历史（不再需要 MCTS 节点压缩）

# ============================================================================
# 状态管理配置（新增）
# ============================================================================
hypothesis_orchestrator:
  # Phase0 Sub-Agent 配置
  phase0_config:
    max_hypotheses: 5        # 最多生成 5 个假设
    min_hypotheses: 3        # 至少生成 3 个假设
    require_priority: true   # 强制假设带优先级
    require_evidence: true   # 强制假设指定预期证据

  # 假设切换配置
  switching_config:
    # 自动切换触发条件
    auto_switch_on_deadend: true
    deadend_threshold: 5              # 连续失败次数
    max_iterations_per_hypothesis: 30 # 单个假设最大迭代数

    # 矛盾检测规则
    contradiction_keywords:
      - "已初始化"                    # 如假设"未初始化" → 发现已初始化
      - "存在检查"                     # 如假设"缺少检查" → 发现存在检查
      - "不可能触发"                   # 如假设路径不可达

  # 假设状态记录
  logging:
    log_hypothesis_switches: true
    log_verification_attempts: true
    log_discoveries: true

# ============================================================================
# 实例配置（对接 SEC-bench）
# ============================================================================
instances:
  type: secb_poc                       # 或 secb_patch
  dataset_name: "SEC-bench/SEC-bench"
  split: "eval"
  slice: ":80"                         # 前 80 个实例
  shuffle: false
```

### 新工具 1：`tools/hypothesis_switch/`

```
tools/hypothesis_switch/
├── config.yaml
├── bin/
│   └── hypothesis_switch
└── README.md
```

**config.yaml**:
```yaml
name: hypothesis_switch
signatures:
  - name: hypothesis_switch
    description: |
      Switch to a fallback hypothesis when current hypothesis is refuted.

      **HIGH THRESHOLD**: Only use when you have strong evidence that the current
      hypothesis is fundamentally wrong.

      Triggers:
      - Found direct contradictory evidence
      - Exhausted all suggested_steps without progress
      - PoC attempts consistently fail (5+ times)

      DO NOT use just because one action didn't work.

    arguments:
      - name: current_hypothesis_id
        type: string
        required: true
        description: ID of the hypothesis being refuted (e.g., "H0_primary_uaf")

      - name: reason
        type: string
        required: true
        description: Detailed reason for refuting (cite specific evidence)

      - name: next_hypothesis_id
        type: string
        required: false
        description: Optional - specify which fallback to activate (default: next priority)

    returns: |
      Activated Hypothesis:
      ID: H1_fallback_npd
      Description: Null pointer dereference in iterator handling
      Priority: 2
      Suggested Steps:
      1. Read njs_vmcode.c:802-810
      2. Find njs_vmcode_prop_next_t definition
      ...
```

**bin/hypothesis_switch** (Python script):
```python
#!/usr/bin/env python3
"""Hypothesis switching tool for SWE-agent"""
import sys
import json

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--current_hypothesis_id', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument('--next_hypothesis_id', required=False)
    args = parser.parse_args()

    # 1. 加载 HypothesisOrchestrator 状态
    state_file = "/workspace/.hypothesis_state.json"
    with open(state_file, 'r') as f:
        state = json.load(f)

    # 2. 标记当前假设为 REFUTED
    for h in state['hypotheses']:
        if h['id'] == args.current_hypothesis_id:
            h['status'] = 'REFUTED'
            h['refuted_reason'] = args.reason
            break

    # 3. 激活下一个假设
    if args.next_hypothesis_id:
        next_hyp = next((h for h in state['hypotheses'] if h['id'] == args.next_hypothesis_id), None)
    else:
        # 自动选择最高优先级的 PENDING 假设
        pending = [h for h in state['hypotheses'] if h['status'] == 'PENDING']
        next_hyp = sorted(pending, key=lambda h: h['priority'])[0] if pending else None

    if not next_hyp:
        print("ERROR: No fallback hypothesis available!")
        sys.exit(1)

    next_hyp['status'] = 'ACTIVE'
    state['active_hypothesis_id'] = next_hyp['id']
    state['verification_attempts'] = []  # 清空验证历史

    # 4. 保存状态
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)

    # 5. 输出给 Agent
    print(f"✅ Hypothesis switched successfully")
    print(f"\nActivated Hypothesis:")
    print(f"ID: {next_hyp['id']}")
    print(f"Description: {next_hyp['description']}")
    print(f"Priority: {next_hyp['priority']}")
    print(f"\nSuggested Steps:")
    for i, step in enumerate(next_hyp['suggested_steps'], 1):
        print(f"{i}. {step}")

    print(f"\n**IMPORTANT**: You are now verifying a NEW hypothesis. Previous verification attempts are cleared.")

if __name__ == '__main__':
    main()
```

### 新工具 2：`tools/sanitizer_analysis/`

```
tools/sanitizer_analysis/
├── config.yaml
├── bin/
│   └── sanitizer_analysis
└── lib/
    └── sanitizer_parser.py  # 复用 VulnTree 的 SanitizerParser
```

**config.yaml**:
```yaml
name: sanitizer_analysis
signatures:
  - name: sanitizer_analysis
    description: |
      Parse the sanitizer report to extract Ground Truth information.

      **MUST be your first action** in every instance.

      Extracts:
      - Error type (NPD/UAF/Buffer overflow/etc.)
      - Crash location (file:line)
      - Crash function name
      - Complete call stack
      - For UAF: allocation/deallocation stacks

    arguments: []

    returns: |
      Ground Truth Information:

      Error Type: null-pointer-dereference
      Sanitizer: AddressSanitizer
      Crash Location: /home/.../njs_vmcode.c:802
      Crash Function: njs_vmcode_interpreter

      Call Stack (16 frames):
      #0  njs_vmcode.c:802 (njs_vmcode_interpreter)
      #1  njs_async.c:96 (njs_await_fulfilled)
      #2  njs_promise.c:1171 (njs_promise_reaction_job)
      ...

      Unique Files (8):
      - njs_vmcode.c
      - njs_async.c
      - njs_promise.c
      ...
```

**bin/sanitizer_analysis** (Python script):
```python
#!/usr/bin/env python3
"""Sanitizer report parsing tool"""
import sys
import os

# 导入 VulnTree 的 SanitizerParser（需要复制到 lib/）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lib'))
from sanitizer_parser import SanitizerReportParser

def main():
    # 1. 读取 sanitizer report（从 problem_statement 或环境变量）
    report_file = os.getenv('SANITIZER_REPORT_FILE', '/workspace/sanitizer_report.txt')

    with open(report_file, 'r') as f:
        report_text = f.read()

    # 2. 解析
    parser = SanitizerReportParser()
    parsed_info = parser.parse(report_text)

    if not parsed_info:
        print("ERROR: Failed to parse sanitizer report!")
        sys.exit(1)

    # 3. 格式化输出
    print("Ground Truth Information:\n")
    print(f"Error Type: {parsed_info.error_type}")
    print(f"Sanitizer: {parsed_info.sanitizer_type}")
    print(f"Crash Location: {parsed_info.crash_location}")
    print(f"Crash Function: {parsed_info.crash_function}")
    print(f"\nCall Stack ({len(parsed_info.call_stack)} frames):")

    for i, frame in enumerate(parsed_info.call_stack):
        print(f"#{i}  {frame.file}:{frame.line} ({frame.function})")

    unique_files = parsed_info.get_unique_files()
    print(f"\nUnique Files ({len(unique_files)}):")
    for file in unique_files:
        print(f"- {file}")

    # 4. 保存到状态文件（供后续使用）
    import json
    state_file = "/workspace/.hypothesis_state.json"

    state_data = {
        'sanitizer_info': {
            'error_type': parsed_info.error_type,
            'crash_location': parsed_info.crash_location,
            'crash_function': parsed_info.crash_function,
            'call_stack': [
                {'file': f.file, 'line': f.line, 'function': f.function}
                for f in parsed_info.call_stack
            ],
            'unique_files': unique_files
        },
        'hypotheses': [],  # 等待 Phase0 填充
        'active_hypothesis_id': None,
        'discoveries': [],
        'verification_attempts': []
    }

    with open(state_file, 'w') as f:
        json.dump(state_data, f, indent=2)

    print(f"\n✅ Ground Truth extracted and saved to {state_file}")

if __name__ == '__main__':
    main()
```

---

## 工具扩展需求

### 1. Phase0 Sub-Agent 集成

**需求**：复用 VulnTree 的 Phase0 Sub-Agent 逻辑

**实现方式**：

**Option A: 作为独立服务（推荐）**

```
phase0-service/
├── Dockerfile
├── server.py         # Flask/FastAPI 服务
├── phase0_executor.py  # 复用 VulnTree 的 SubAgentExecutor
└── prompts/
    └── phase0_system_prompt_v4.prompt  # 复用 VulnTree prompt
```

**server.py**:
```python
from flask import Flask, request, jsonify
from phase0_executor import SubAgentExecutor

app = Flask(__name__)

@app.route('/generate_hypotheses', methods=['POST'])
def generate_hypotheses():
    data = request.json
    sanitizer_info = data['sanitizer_info']
    vuln_type = data['vuln_type']

    executor = SubAgentExecutor(
        completion_model=get_model(),
        system_prompt_path='prompts/phase0_system_prompt_v4.prompt'
    )

    result = executor.execute_task(
        task_description=f"Generate hypotheses for {vuln_type} vulnerability",
        context={
            'sanitizer_info': sanitizer_info,
            'mode': 'hypothesis_generation'
        }
    )

    # 解析 Sub-Agent 输出为结构化假设
    hypotheses = parse_hypotheses_from_output(result.full_report)

    return jsonify({'hypotheses': hypotheses})

def parse_hypotheses_from_output(report):
    """从 Phase0 输出提取结构化假设"""
    # 解析 Markdown 表格或 JSON block
    # 返回:
    # [
    #   {
    #     "id": "H0_primary_uaf",
    #     "description": "...",
    #     "priority": 1,
    #     "suggested_steps": [...],
    #     "expected_evidence": "..."
    #   },
    #   ...
    # ]
    ...
```

**在 SWE-agent 中调用**：

```python
# tools/defaults/bin/init_hypotheses (新增工具)
import requests

def call_phase0_service():
    # 1. 读取 sanitizer_info（由 sanitizer_analysis 工具生成）
    with open('/workspace/.hypothesis_state.json') as f:
        state = json.load(f)
    sanitizer_info = state['sanitizer_info']

    # 2. 调用 Phase0 服务
    response = requests.post(
        'http://phase0-service:5000/generate_hypotheses',
        json={
            'sanitizer_info': sanitizer_info,
            'vuln_type': os.getenv('VULN_TYPE', 'UAF')
        }
    )

    hypotheses = response.json()['hypotheses']

    # 3. 更新状态文件
    state['hypotheses'] = hypotheses
    state['active_hypothesis_id'] = hypotheses[0]['id']  # 激活第一个假设

    with open('/workspace/.hypothesis_state.json', 'w') as f:
        json.dump(state, f, indent=2)

    # 4. 输出给 Agent
    print("✅ Generated Hypotheses:\n")
    for hyp in hypotheses:
        print(f"\n{'='*60}")
        print(f"ID: {hyp['id']}")
        print(f"Priority: {hyp['priority']}")
        print(f"Description: {hyp['description']}")
        print(f"Expected Evidence: {hyp['expected_evidence']}")
        print(f"\nSuggested Steps:")
        for i, step in enumerate(hyp['suggested_steps'], 1):
            print(f"  {i}. {step}")

    print(f"\n{'='*60}")
    print(f"✅ Activated Primary Hypothesis: {hypotheses[0]['id']}")
```

**Option B: 内嵌到 SWE-agent Task tool**

- 修改 Task tool 检测 `task_description` 包含 "generate hypotheses"
- 内部调用 Phase0 逻辑
- 返回结构化假设

### 2. 状态持久化工具

**需求**：在容器化环境中持久化假设状态

**实现**：

```bash
# tools/registry/bin/save_state
#!/bin/bash
# 保存 .hypothesis_state.json 到主机
cp /workspace/.hypothesis_state.json /trajectory_output/hypothesis_state_$(date +%s).json

# tools/registry/bin/load_state
#!/bin/bash
# 从主机恢复状态（用于断点续传）
latest_state=$(ls -t /trajectory_output/hypothesis_state_*.json | head -1)
if [ -f "$latest_state" ]; then
    cp "$latest_state" /workspace/.hypothesis_state.json
    echo "✅ Restored hypothesis state from $latest_state"
fi
```

### 3. 成功检测工具

**需求**：自动检测 PoC 是否成功触发漏洞

**实现**：

```python
# tools/submit_poc/bin/detect_success (新增)
#!/usr/bin/env python3
"""检测 DockerScript 执行是否成功触发漏洞"""
import re
import sys

def detect_vulnerability_triggered(output):
    """从 bash 输出检测漏洞触发信号"""

    # ASAN 报告特征
    asan_patterns = [
        r'ERROR: AddressSanitizer',
        r'SEGV on unknown address',
        r'heap-use-after-free',
        r'null-pointer-dereference'
    ]

    # 崩溃信号
    crash_patterns = [
        r'Segmentation fault',
        r'core dumped',
        r'killed by signal'
    ]

    for pattern in asan_patterns + crash_patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return True

    return False

if __name__ == '__main__':
    # 读取最近一次 DockerScript 的输出
    with open('/workspace/.last_docker_output.txt', 'r') as f:
        output = f.read()

    if detect_vulnerability_triggered(output):
        print("✅ SUCCESS: Vulnerability triggered!")
        print("\nDetected signals:")
        for line in output.split('\n'):
            if any(p in line for p in ['ERROR:', 'SEGV', 'fault']):
                print(f"  {line}")
        sys.exit(0)
    else:
        print("❌ FAIL: Vulnerability not triggered")
        sys.exit(1)
```

---

## 简化探索策略

### 对比：MCTS vs 线性执行

| 维度 | MCTS (VulnTree) | 线性执行 (迁移后) | 优势 |
|------|----------------|------------------|------|
| **决策复杂度** | UCB 公式，LLM 评估多个节点 | Agent 单次决策下一步 | 降低计算开销 |
| **状态管理** | 树结构，节点快照，复杂恢复 | 简单字典，JSON 序列化 | 易于实现和调试 |
| **探索策略** | 平衡探索/利用，可能跳回浅层 | 深度优先，坚持当前假设 | 更彻底的假设验证 |
| **失败处理** | Backpropagation 惩罚路径 | 计数失败次数，达阈值切换假设 | 明确的切换逻辑 |
| **可预测性** | 树搜索路径难以预测 | 线性日志，容易追踪 | 提升可调试性 |
| **token 使用** | 每次选择需要评估多个候选 | 每次只生成一个 action | 降低 API 成本 |

### 新探索策略：深度优先 + 显式切换

**核心思想**：信任假设，深度探索，只在强信号时切换

```python
def exploration_strategy():
    """
    伪代码：深度优先探索策略
    """
    current_hypothesis = get_active_hypothesis()
    consecutive_failures = 0

    while True:
        # 1. 根据当前假设生成 action
        action = agent.generate_action(
            hypothesis=current_hypothesis,
            suggested_steps=current_hypothesis.suggested_steps,
            discoveries=state.discoveries
        )

        # 2. 执行 action
        observation = execute(action)
        state.add_discovery(observation)

        # 3. 检测结果
        if is_poc_success(observation):
            # ✅ 假设确认
            confirm_hypothesis(current_hypothesis)
            return SUCCESS

        elif is_contradiction(observation, current_hypothesis):
            # ❌ 发现矛盾，显式切换
            refute_hypothesis(current_hypothesis, reason=observation.contradiction)
            current_hypothesis = activate_fallback()
            consecutive_failures = 0  # 重置计数

        elif is_action_failure(observation):
            # ⚠️ 单次失败，计数
            consecutive_failures += 1

            if consecutive_failures >= DEADEND_THRESHOLD:
                # 确认死路，切换假设
                mark_inconclusive(current_hypothesis)
                current_hypothesis = activate_fallback()
                consecutive_failures = 0

        else:
            # ⏳ 正常探索，重置失败计数
            consecutive_failures = 0

        # 4. 迭代保护
        if state.iterations >= MAX_ITERATIONS:
            return TIMEOUT
```

### 假设切换的智能判断

**规则 1：矛盾检测**

```python
def is_contradiction(observation, hypothesis):
    """
    检测观察结果是否与假设矛盾
    """
    # 假设：缺少 X 检查
    if "缺少" in hypothesis.description or "missing" in hypothesis.description.lower():
        # 实际：找到了 X 检查
        if "已存在" in observation.message or "found check" in observation.message.lower():
            return True

    # 假设：变量未初始化
    if "未初始化" in hypothesis.description or "uninitialized" in hypothesis.description.lower():
        # 实际：找到初始化代码
        if re.search(r'(初始化|initialized)', observation.message):
            return True

    # 假设：特定函数触发
    if "function" in hypothesis.description and "triggers" in hypothesis.description:
        # 实际：函数不可达或不存在
        if "not found" in observation.message or "unreachable" in observation.message:
            return True

    return False
```

**规则 2：死路检测**

```python
def is_deadend(current_hypothesis, state):
    """
    检测是否到达死路（无法继续验证当前假设）
    """
    # 条件 1：连续失败
    recent_attempts = state.verification_attempts[-5:]
    if len(recent_attempts) == 5 and all(a.outcome == 'failure' for a in recent_attempts):
        return True

    # 条件 2：所有 suggested_steps 已完成，但无预期证据
    completed_steps = [s for s in current_hypothesis.suggested_steps
                       if is_step_completed(s, state.discoveries)]

    if len(completed_steps) == len(current_hypothesis.suggested_steps):
        # 检查是否找到预期证据
        expected = current_hypothesis.expected_evidence
        found = any(expected in d for d in state.discoveries)

        if not found:
            return True  # 所有步骤完成但无预期证据 = 假设错误

    # 条件 3：迭代次数过多
    hypothesis_iterations = len([a for a in state.verification_attempts
                                 if a.hypothesis_id == current_hypothesis.id])
    if hypothesis_iterations >= 30:
        return True

    return False
```

**规则 3：PoC 成功检测**

```python
def is_poc_success(observation):
    """
    检测 PoC 是否成功触发漏洞
    """
    # 检查 observation 中的 ASAN 报告特征
    success_indicators = [
        'ERROR: AddressSanitizer',
        'SEGV on unknown address',
        'heap-use-after-free',
        'null-pointer-dereference',
        'Segmentation fault',
        'core dumped'
    ]

    message = observation.message.lower()
    return any(indicator.lower() in message for indicator in success_indicators)
```

---

## 实施路线图

### Phase 1: 基础设施搭建（1-2 周）

**目标**：建立最小可行架构

**任务**：

1. **复制 SWE-agent 代码库**
   ```bash
   git clone https://github.com/SWE-agent/SWE-agent.git vulntree-swe
   cd vulntree-swe
   git checkout -b hypothesis-driven
   ```

2. **创建新配置文件**
   - `config/secb_hypothesis_driven.yaml`（基于 `secb_poc.yaml` 修改）
   - 添加假设驱动的 Prompt 模板
   - 配置工具 bundles

3. **实现状态管理**
   ```python
   # 新文件：sweagent/state/hypothesis_orchestrator.py
   class HypothesisOrchestrator:
       def __init__(self):
           self.hypotheses = []
           self.active_hypothesis_id = None
           self.state_file = "/workspace/.hypothesis_state.json"

       def load_state(self):
           """从文件加载状态"""
           ...

       def save_state(self):
           """保存状态到文件"""
           ...

       def activate_hypothesis(self, hypothesis_id):
           """激活指定假设"""
           ...

       def refute_hypothesis(self, hypothesis_id, reason):
           """标记假设为 REFUTED"""
           ...

       def get_active_hypothesis(self):
           """获取当前活跃假设"""
           ...
   ```

4. **创建新工具**
   - `tools/sanitizer_analysis/`
     - 复制 VulnTree 的 `sanitizer_parser.py`
     - 包装为 SWE-agent tool

   - `tools/hypothesis_switch/`
     - 实现假设切换逻辑
     - 更新状态文件

5. **测试基础流程**
   ```bash
   # 测试 sanitizer_analysis 工具
   sweagent run \
     --config config/secb_hypothesis_driven.yaml \
     --instances.type secb_poc \
     --instances.slice 0:1
   ```

**里程碑**：能够解析 Sanitizer 报告并初始化状态

---

### Phase 2: Phase0 Sub-Agent 集成（2-3 周）

**目标**：实现假设生成流程

**任务**：

1. **搭建 Phase0 服务**
   ```
   phase0-service/
   ├── Dockerfile
   ├── server.py
   ├── phase0_executor.py  # 从 VulnTree 复制
   ├── requirements.txt
   └── prompts/
       └── phase0_system_prompt_v4.prompt  # 从 VulnTree 复制
   ```

2. **适配 Phase0 输出格式**
   - 修改 Phase0 prompt，强制输出结构化 JSON
   - 示例输出格式：
     ```json
     {
       "hypotheses": [
         {
           "id": "H0_primary_uaf",
           "description": "Promise reaction UAF",
           "priority": 1,
           "suggested_steps": [
             "Read njs_promise.c:1757-1770",
             "Find njs_promise_perform_race_handler",
             "Task: Analyze Promise lifecycle"
           ],
           "expected_evidence": "缺少 njs_is_valid() 调用"
         }
       ]
     }
     ```

3. **创建 init_hypotheses 工具**
   - 调用 Phase0 服务
   - 解析假设并保存到状态文件
   - 激活 Primary 假设

4. **更新 Agent Prompt 注入**
   - 修改 `config/secb_hypothesis_driven.yaml` 的 `system_template`
   - 使用 Jinja2 模板从状态文件注入假设

5. **端到端测试**
   ```bash
   # 完整流程：Sanitizer 解析 → 假设生成 → 验证开始
   sweagent run \
     --config config/secb_hypothesis_driven.yaml \
     --instances.type secb_poc \
     --instances.slice 0:5
   ```

**里程碑**：Agent 能够接收到结构化假设并开始验证

---

### Phase 3: 验证循环实现（2 周）

**目标**：实现深度优先验证流程

**任务**：

1. **实现验证历史追踪**
   ```python
   # sweagent/state/verification_tracker.py
   class VerificationTracker:
       def record_attempt(self, hypothesis_id, action, outcome):
           """记录验证尝试"""
           self.attempts.append({
               'hypothesis_id': hypothesis_id,
               'action': str(action),
               'outcome': outcome,
               'timestamp': time.time()
           })

       def get_consecutive_failures(self, hypothesis_id):
           """计算连续失败次数"""
           recent = [a for a in self.attempts[-10:]
                     if a['hypothesis_id'] == hypothesis_id]

           failures = 0
           for a in reversed(recent):
               if a['outcome'] == 'failure':
                   failures += 1
               else:
                   break
           return failures
   ```

2. **实现矛盾检测**
   ```python
   # sweagent/state/contradiction_detector.py
   class ContradictionDetector:
       def __init__(self, hypothesis_orchestrator):
           self.orchestrator = hypothesis_orchestrator

       def check(self, observation):
           """检测观察结果是否与当前假设矛盾"""
           current_hyp = self.orchestrator.get_active_hypothesis()

           # 规则检测（见前文"假设切换的智能判断"）
           if self._check_missing_vs_found(current_hyp, observation):
               return True, "Expected missing code was found"

           if self._check_uninitialized_vs_initialized(current_hyp, observation):
               return True, "Variable is actually initialized"

           return False, None
   ```

3. **实现死路检测**
   ```python
   # sweagent/state/deadend_detector.py
   class DeadendDetector:
       CONSECUTIVE_FAILURE_THRESHOLD = 5
       MAX_ITERATIONS_PER_HYPOTHESIS = 30

       def check(self, hypothesis_id, tracker):
           """检测是否到达死路"""
           # 检测连续失败
           if tracker.get_consecutive_failures(hypothesis_id) >= self.CONSECUTIVE_FAILURE_THRESHOLD:
               return True, "Too many consecutive failures"

           # 检测迭代次数
           iterations = tracker.get_hypothesis_iterations(hypothesis_id)
           if iterations >= self.MAX_ITERATIONS_PER_HYPOTHESIS:
               return True, "Max iterations reached"

           # 检测建议步骤完成但无预期证据
           # ...

           return False, None
   ```

4. **集成到 Agent 循环**
   - 修改 `sweagent/agent/agents.py` 的 `run()` 方法
   - 在每个 action 执行后：
     1. 更新 verification_tracker
     2. 检查矛盾
     3. 检查死路
     4. 检查 PoC 成功
     5. 根据检测结果触发假设切换

5. **测试验证流程**
   - 使用已知的 SEC-bench 实例
   - 验证能够正确检测成功/失败/矛盾

**里程碑**：Agent 能够深度验证假设并正确切换

---

### Phase 4: PoC 成功检测与提交（1 周）

**目标**：自动识别漏洞触发并提交

**任务**：

1. **实现 PoC 成功检测器**
   ```python
   # sweagent/detectors/poc_success_detector.py
   class PoCSuccessDetector:
       ASAN_PATTERNS = [
           r'ERROR: AddressSanitizer',
           r'SEGV on unknown address',
           r'heap-use-after-free'
       ]

       def detect(self, observation):
           """从 observation 中检测漏洞触发信号"""
           if observation.expect_correction:
               # 有错误，可能是 PoC 成功导致的崩溃
               for pattern in self.ASAN_PATTERNS:
                   if re.search(pattern, observation.message):
                       return True, self._extract_crash_signature(observation)
           return False, None
   ```

2. **自动提交流程**
   ```python
   # 在 Agent 循环中集成
   if poc_detector.detect(observation):
       # 1. 标记假设为 CONFIRMED
       orchestrator.confirm_hypothesis(active_hypothesis.id)

       # 2. 收集 PoC 文件
       poc_files = collect_testcase_files()

       # 3. 调用 submit_poc 工具
       action = SubmitPoCAction()
       result = action.execute()

       # 4. 返回成功
       return Success(result)
   ```

3. **测试提交流程**
   - 使用已复现的漏洞实例
   - 验证能够正确识别成功并提交

**里程碑**：完整的 PoC 生成和提交流程

---

### Phase 5: 批量评估与优化（2-3 周）

**目标**：在 SEC-bench 上运行并优化

**任务**：

1. **批量运行脚本**
   ```bash
   # 新脚本：run_hypothesis_driven.sh
   #!/bin/bash

   MODEL=${1:-"deepseek"}
   SLICE=${2:-":80"}

   sweagent run-batch \
     --config config/secb_hypothesis_driven.yaml \
     --agent.model.name $MODEL \
     --instances.type secb_poc \
     --instances.split eval \
     --instances.slice $SLICE \
     --num_workers 4 \
     --output_dir results/hypothesis_driven_$(date +%Y%m%d)
   ```

2. **结果分析**
   - 成功率统计
   - 平均迭代次数
   - 假设切换频率
   - 失败原因分类

3. **Prompt 优化**
   - 根据失败案例调整 system_template
   - 优化假设切换的触发条件
   - 改进矛盾检测规则

4. **性能优化**
   - 减少不必要的 LLM 调用
   - 优化状态文件读写
   - 并行处理多个实例

**里程碑**：在 SEC-bench 上达到或超过 VulnTree 的性能

---

### Phase 6: 文档与发布（1 周）

**目标**：整理文档，准备发布

**任务**：

1. **编写使用文档**
   - `docs/hypothesis_driven.md`：架构说明
   - `docs/tools/hypothesis_switch.md`：工具使用指南
   - `examples/hypothesis_driven_walkthrough.md`：完整示例

2. **代码清理**
   - 移除调试代码
   - 添加类型注解
   - 完善注释

3. **测试覆盖**
   - 单元测试（状态管理、检测器）
   - 集成测试（完整流程）

4. **发布**
   - 合并到主分支
   - 打 tag：`v1.0-hypothesis-driven`

**里程碑**：可供他人使用的稳定版本

---

## 风险与挑战

### 风险 1：Phase0 Sub-Agent 的适配复杂度

**风险描述**：VulnTree 的 Phase0 Sub-Agent 有复杂的状态机和多轮对话逻辑，可能难以迁移

**缓解措施**：

1. **简化 Phase0 输出**：只要求输出结构化假设，去除 Round 1-3 的复杂流程
2. **单轮生成**：让 Phase0 在一次调用中生成所有假设，而非多轮对话
3. **备用方案**：如果 Sub-Agent 过于复杂，使用简单的 Prompt 让 MainAgent 直接生成假设

**降级策略**：

```yaml
# config/secb_simple_hypothesis.yaml (备用配置)
agent:
  templates:
    instance_template: |
      {{problem_statement}}

      Based on the sanitizer report above, generate 3 hypotheses about the root cause.

      For each hypothesis, provide:
      1. ID (e.g., H0_primary)
      2. Description
      3. 3-5 verification steps
      4. Expected evidence

      Output in JSON format.
```

---

### 风险 2：假设切换的触发时机难以把握

**风险描述**：切换太早浪费探索，切换太晚浪费资源

**缓解措施**：

1. **保守阈值**：初始设置高门槛（连续 5 次失败），根据实验调整
2. **多维度检测**：结合矛盾检测、死路检测、迭代限制，三重保险
3. **日志分析**：详细记录每次切换的原因，回溯优化

**实验验证**：

```python
# 实验不同阈值的影响
thresholds = [3, 5, 7, 10]
for t in thresholds:
    run_experiment(deadend_threshold=t)
    analyze_results()  # 对比成功率、平均迭代数
```

---

### 风险 3：去除 MCTS 后探索能力下降

**风险描述**：MCTS 能够回溯到高价值节点，线性执行可能陷入局部

**缓解措施**：

1. **假设多样性**：Phase0 生成 3-5 个不同方向的假设，覆盖多种可能性
2. **fallback 链**：每个假设可以有多个 fallback，形成探索树（但不是 MCTS）
3. **中间检查点**：在假设验证过程中定期保存状态，支持手动回溯

**对比实验**：

- 运行相同实例，对比 VulnTree (MCTS) vs 新系统（线性）
- 指标：成功率、平均成本、平均时间

---

### 风险 4：SWE-agent 框架的限制

**风险描述**：SWE-agent 可能缺少 VulnTree 的某些能力（如状态快照、复杂上下文管理）

**缓解措施**：

1. **最小侵入**：优先使用 SWE-agent 的扩展机制（tools、config），避免修改核心代码
2. **状态外置**：通过文件系统（`.hypothesis_state.json`）持久化状态，而非依赖内存
3. **渐进式迁移**：先实现核心流程，再逐步添加高级功能

**兼容性检查**：

- ✅ Prompt 模板：SWE-agent 支持 Jinja2，可注入假设上下文
- ✅ 工具扩展：通过 tools bundles 添加自定义工具
- ✅ 批量处理：`run-batch` 支持并行和进度管理
- ⚠️ 状态管理：需要自行实现 `HypothesisOrchestrator`
- ⚠️ 中间结果：需要通过 observation properties 传递

---

## 总结

### 核心设计要点

1. **假设驱动**：Phase0 生成结构化假设 → MainAgent 深度验证 → 高门槛切换
2. **Sanitizer 高起点**：首个 action 必须解析 Ground Truth → 所有分析从已知事实出发
3. **简化架构**：去除 MCTS 和 LLM 评估器 → 线性执行 + 规则判断
4. **显式切换**：只在矛盾/死路/迭代限制时切换 → 避免浅层跳跃

### 预期收益

| 维度 | VulnTree v3.11 | 迁移后 | 改进 |
|------|---------------|-------|------|
| **代码复杂度** | ~15k 行（MCTS + Memory + Selector） | ~5k 行（HypothesisOrchestrator + 简单状态） | -67% |
| **可调试性** | 树搜索路径难追踪 | 线性日志，易于理解 | ✅ 显著提升 |
| **token 使用** | 每次 MCTS 迭代评估多个节点 | 每次只生成一个 action | -30% |
| **假设验证深度** | 可能提前跳出当前假设 | 坚持深度探索，高门槛切换 | ✅ 更彻底 |
| **批量处理能力** | 自建并行逻辑 | 利用 SWE-agent run-batch | ✅ 更成熟 |

### 下一步行动

1. **立即开始**：Phase 1（基础设施搭建）
2. **关键里程碑**：Phase 2（Phase0 集成）
3. **验证点**：Phase 5（批量评估）

---

**文档版本**：v1.0
**作者**：Claude
**日期**：2025-01-27
