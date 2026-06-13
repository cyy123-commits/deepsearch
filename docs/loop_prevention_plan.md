# 工具调用死循环防护机制 — 实现方案

## 概览

本文档针对当前项目在智能体工具调用死循环防护方面的 5 个薄弱环节，给出具体的实现方案（不含代码）。所有方案均基于项目现有架构设计，可直接落地。

**当前项目的防护状态回顾：**

| 层级 | 机制 | 状态 |
|------|------|------|
| 框架 | DeepAgents 内置 `recursion_limit: 1000` | 有，但过大 |
| 代码 | 任何自行实现的限制/超时/去重 | 无 |
| 提示词 | 网络搜索"最多5次检索" | 仅软约束，无代码强制 |

---

## 方案一：ToolCallLimitMiddleware — 工具调用次数限制

### 目标

对每个工具（或全局全部工具）设定最大调用次数，超过后按策略终止或阻止。

### 原理

LangChain 已内置 `ToolCallLimitMiddleware`（位于 `langchain.agents.middleware.tool_call_limit`），无需自己编写中间件逻辑。该中间件 hook 在 `after_model` 阶段，当 LLM 生成 tool_call 后自动检查计数并决定放行/阻止/终止。

### 配置参数

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `tool_name` | 限定某个工具名，`None` 表示追踪全部工具 | 按需 |
| `thread_limit` | 同一会话(thread)内累计上限，跨多次 run 持久化 | 30 |
| `run_limit` | 单次 run 内的调用上限 | 20 |
| `exit_behavior` | 超限后的行为：`"continue"` / `"error"` / `"end"` | `"continue"` |

### 三种退出策略对比

| 策略 | 行为 | 适用场景 |
|------|------|----------|
| `"continue"` | 超限的工具调用返回错误 ToolMessage，告知 LLM 不要再调，但其他工具继续执行 | **推荐**：温和降级，给 LLM 机会自行收尾 |
| `"error"` | 抛出 `ToolCallLimitExceededError` 异常，由外层 try/except 捕获 | 需要严格控制的场景 |
| `"end"` | 立即跳转到 graph 终点，注入一条总结性的 AIMessage | 仅适用于单一超限 tool_call、无并行调用的场景 |

### 实现位置

**文件**：`agent/main_agent.py`

**修改点**：

1. **导入**：从 `langchain.agents.middleware.tool_call_limit` 导入 `ToolCallLimitMiddleware`
2. **实例化**：在模块顶层（`create_deep_agent` 调用之前）创建中间件实例。按项目需求建议创建两个实例：
   - 全局限制：`tool_name=None, run_limit=20, thread_limit=30, exit_behavior="continue"` — 控制所有工具的总调用次数
   - 网络搜索限制：`tool_name="internet_search", run_limit=5, exit_behavior="continue"` — 将提示词中的"最多5次"软约束升级为代码硬限制
3. **传入 agent**：在 `create_deep_agent()` 调用中增加 `middleware=[...]` 参数，将中间件实例列表传入。**注意：**`create_deep_agent` 内部已经自带了 `TodoListMiddleware`、`SummarizationMiddleware`、`SubAgentMiddleware` 等，传入的 middleware 会与内置中间件合并

### 注意事项

- 中间件的 `state_schema` 会自动合并到 Agent 的 state 中（通过 `ToolCallLimitState` 增加 `thread_tool_call_count` 和 `run_tool_call_count` 字段），无需手动处理 state
- 如果 `create_deep_agent` 不支持直接传 `middleware` 参数，则需要在调用后通过 `main_agent.middleware.append()` 添加，或查看 DeepAgents 的具体 API
- `run_limit` 不能大于 `thread_limit`

---

## 方案二：ModelCallLimitMiddleware — 模型调用次数限制

### 目标

限制 LLM 被调用的总次数（每次 LLM 思考-输出为一个 model call），防止 Agent 无限"思考-调用工具-思考-调用工具"循环。

### 原理

LangChain 内置 `ModelCallLimitMiddleware`（`langchain.agents.middleware.model_call_limit`）。该中间件 hook 在 `before_model`（调用前检查）和 `after_model`（调用后递增计数）两个阶段。

### 与 ToolCallLimitMiddleware 的区别

| 维度 | ToolCallLimitMiddleware | ModelCallLimitMiddleware |
|------|------------------------|--------------------------|
| 计数对象 | 工具被调用的次数 | LLM 被调用的次数（每轮思考） |
| Hook 时机 | `after_model` | `before_model` + `after_model` |
| 粒度 | 可按工具名分别限制 | 全局，不分工具 |
| 退出策略 | `continue` / `error` / `end` | 仅 `end` / `error`（无 `continue`） |

两者的关系：一次 model call 可能产生多个 tool_call（并行调用），每个 tool_call 会触发一次 tool 执行，然后又回到 model call。因此 **ModelCallLimit 是更根本的循环限制** — 它直接限制"思考轮次"。

### 配置参数

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `thread_limit` | 同一会话内累计模型调用上限 | 50 |
| `run_limit` | 单次 run 内的调用上限 | 30 |
| `exit_behavior` | `"end"` 或 `"error"` | `"end"` |

### 实现位置

**文件**：`agent/main_agent.py`

**修改点**：

1. **导入**：从 `langchain.agents.middleware.model_call_limit` 导入 `ModelCallLimitMiddleware`
2. **实例化**：`ModelCallLimitMiddleware(run_limit=30, thread_limit=50, exit_behavior="end")`
3. **传入 agent**：与方案一的中间件一起放入 middleware 列表

### 注意事项

- `exit_behavior="end"` 会在超限时注入一条 AIMessage 告知用户"模型调用次数已达上限"，然后优雅退出。这比 `"error"` 的用户体验更好
- `exit_behavior="error"` 更适合需要外层捕获异常做特殊处理的场景

---

## 方案三：显式 recursion_limit — 在项目代码中设置

### 目标

当前仅依赖 DeepAgents 框架内部的 `recursion_limit: 1000`（位于 `D:/anaconda3/envs/deepagent/Lib/site-packages/deepagents/graph.py`）。该值过大（1000 步足够消耗大量 token 和时间），且不经过项目代码控制。本方案在项目自身代码中显式设置一个更合理的值。

### 什么是 recursion_limit

LangGraph 的 `recursion_limit` 统计的是图中的**节点执行次数**（每次 model 调用、每次 tool 执行、每次 middleware hook 都算一次）。到达上限时 LangGraph 抛出 `GraphRecursionError`。

当前项目中一次典型的"模型思考→调用工具→工具返回→模型再思考"循环大约消耗 3-5 个节点步骤。按 1000 步算，可执行约 200-300 轮，远超合理范围。

### 实现位置

**文件**：`agent/main_agent.py`，`run_main_agent` 函数的 `config` 字典

**当前代码：**

```python
config = {
    "configurable": {
        "thread_id": session_id
    }
}
```

**修改为：**

在 `configurable` 同级（注意：不是 `configurable` 内部）增加 `"recursion_limit"` 键。**正确位置是 config 根级**，即：

```python
config = {
    "recursion_limit": 50,   # ← 新增，在 config 根级
    "configurable": {
        "thread_id": session_id
    }
}
```

### 推荐值

| 场景 | 推荐值 | 说明 |
|------|--------|------|
| 常规查询 | `50` | 大约 10-15 轮模型交互，足够完成大多数搜索+生成任务 |
| 复杂研究 | `100` | 涉及多个子代理并行调用的情况 |
| 生产环境 | `30-50` | 更保守，避免异常时消耗过多资源 |

推荐初始值：**50**。该值可在后续根据实际运行情况调整。

### 注意事项

- **键名位置敏感**：必须在 config 根级别，不在 `configurable` 内部。放错位置则 graph 忽略该设置，仍使用默认的 1000
- **与中间件的关系**：`recursion_limit` 是 LangGraph 层的硬限制，优先级最高；`ToolCallLimitMiddleware` 和 `ModelCallLimitMiddleware` 是 LangChain Agent 层的软限制，可以给出更友好的退出消息。建议三者叠加使用：中间件提供友好提示，recursion_limit 作为最后兜底

---

## 方案四：令牌消耗监控

### 目标

监控每次 agent 执行消耗的 token 数量，超过阈值时主动终止任务，防止因死循环导致的 token 浪费和 API 费用失控。

### 实现思路

本项目**不需要**自己实现 token 计数器（如 tiktoken），而是利用 LangChain 模型调用返回的 `usage_metadata`，通过自定义 middleware 在每次模型调用后累加 token 消耗。

### 实现方式

**创建新文件**：`agent/middleware/token_monitor.py`

**自定义中间件**：`TokenMonitorMiddleware`

**核心逻辑**：

1. **Hook `after_model`**：在每次 LLM 调用后，从返回的 `AIMessage` 中提取 `usage_metadata` 字段。该字段由 LangChain 的 OpenAI-compatible 模型自动填充，包含 `input_tokens`、`output_tokens`、`total_tokens` 等
2. **累加计数**：将当次消耗累加到 state 中的累计值
3. **阈值检查**：
   - 如果累计 token 超过 `max_total_tokens`（如 200,000），触发限流
   - 如果累计 input token 超过 `max_input_tokens`，触发限流
   - 如果 run 级别的 token 超过 `max_run_tokens`，触发限流
4. **超限处理**：
   - `exit_behavior="warn"`：通过 monitor 向前端推送警告，但继续执行
   - `exit_behavior="end"`：跳转到 graph 终点，注入总结消息
   - `exit_behavior="error"`：抛出异常

**State 扩展**：需要新增 state 字段存储累计值：
- `total_token_usage`：thread 级累计
- `run_token_usage`：run 级累计

**与 monitor 的集成**：在 `after_model` hook 中调用 `monitor._emit("token_usage", ...)` 将实时用量推送到前端 WebSocket，前端可展示 token 消耗进度条。

### 配置参数建议

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `max_total_tokens` | `200,000` | 单次会话累计 token 上限 |
| `max_run_tokens` | `100,000` | 单次 run 的 token 上限 |
| `exit_behavior` | `"end"` | 优雅退出 |

### 注意事项

- `usage_metadata` 是否可用取决于模型提供商是否返回 usage 信息。DeepSeek（OpenAI-compatible）通常会在 streaming 模式的最后 chunk 中返回 usage
- 流式场景下 usage 信息在流结束后才能获得，因此需要在 `after_model` 整个完成后读取，不能在 streaming 中途获取
- 如果模型不返回 usage_metadata，可退化为保守估算：按 `(消息字符数 / 4)` 粗略估算 input token，`(生成字符数 / 2)` 估算 output token
- 需要在 `server.py` 中配合方案五的任务超时，确保即使 middleware 未触发也能终止

---

## 方案五：工具返回去重检测

### 目标

检测 LLM 是否反复用相同参数调用同一工具并得到相同结果（这是死循环的最常见症状），一旦检测到则主动干预，提示 LLM 更换策略。

### 实现思路

**创建新文件**：`agent/middleware/dedup.py`

**自定义中间件**：`DeduplicationMiddleware`

### 核心逻辑

**Hook `after_model`（或 `wrap_tool_call`）**：

1. **记录历史**：维护一个字典，key 为 `(tool_name, canonical_args_hash)`，value 为 `(tool_result_hash, timestamp, count)`
   - `canonical_args_hash`：将 tool_call 的 args 序列化为排序后的 JSON 字符串，计算哈希值（消除参数顺序差异）
   - `tool_result_hash`：将 tool 返回结果序列化后计算哈希值
2. **检测重复**：在 LLM 准备发起新一轮 tool_call 时：
   - 查找历史中是否存在相同的 `(tool_name, args_hash)`
   - 如果是第 1 次重复（count=1）：不阻止，放行
   - 如果是第 2 次重复（count=2）：在 tool 执行完成后比较结果哈希。若结果也相同，向消息列表注入一条 `ToolMessage` 警告："你已连续2次使用相同参数调用该工具并得到相同结果，请换一种策略"
   - 如果是第 3 次及以上（count>=3）：直接阻止该 tool_call，返回错误 ToolMessage："该工具调用已被阻止，因为你已连续多次使用相同参数且结果相同。请立即停止调用此工具，改用其他方法或总结现有信息"

### 参数设计

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `max_identical_calls` | 允许相同参数调用的最大次数（含首次） | `3` |
| `dedup_window` | 滑动窗口大小，只记忆最近 N 次调用 | `20` |
| `identical_result_threshold` | 结果相似度阈值（仅当结果也相同时才算重复） | 哈希相等 |

### 实现位置

**文件**：`agent/middleware/dedup.py`（新文件）

**集成方式**：作为 middleware 传入 `create_deep_agent()`

### 补充：提示词层面的配合

除了代码层面的去重，还可在 `prompts.yml` 的主 agent system_prompt 中增加指令：

> 如果你发现自己连续两次使用相同的参数调用同一个工具，且结果相同，说明进入了循环。必须立即停止调用该工具，改用其他策略或直接基于已有信息给出答案。

### 注意事项

- **参数规范化**：同一工具的参数可能有不同写法（如 `{"query": "天气 北京"}` vs `{"query": "天气 北京 "}`, trailing space），哈希前需要 canonicalize：trim 字符串值、排序 keys、忽略 `None` 值
- **工具返回规范化**：工具返回可能是 dict、list、string，需要统一序列化后哈希。大结果可以只取前 N 字节（如前 4096 字节）做哈希
- **不过度拦截**：`count <= 2` 时放行，因为有时确实需要重试（如网络波动导致的空结果）。只有连续 3 次相同才判定为死循环
- **子代理边界**：子代理（subagent）是独立的 agent 实例，有自己的 middleware 栈。如果希望去重也应用于子代理，需要将 `DeduplicationMiddleware` 也传入选用的子代理配置中（或在 DeepAgents 的 subagent middleware 注入机制中处理）

---

## 方案汇总与优先级

| 优先级 | 方案 | 实现难度 | 文件变更 | 效果 |
|--------|------|----------|----------|------|
| **P0 立即** | 方案三：显式 `recursion_limit` | 极低（1 行改动） | `agent/main_agent.py` | 提供硬兜底，防止极端情况 |
| **P0 立即** | 方案一：`ToolCallLimitMiddleware` | 低（导入+配置） | `agent/main_agent.py` | 按工具限次，温和降级 |
| **P1 推荐** | 方案二：`ModelCallLimitMiddleware` | 低（导入+配置） | `agent/main_agent.py` | 限制思考总轮次 |
| **P1 推荐** | 方案五：工具返回去重 | 中（新文件+逻辑） | 新建 `agent/middleware/dedup.py` | 精准检测并阻断死循环 |
| **P2 可选** | 方案四：Token 消耗监控 | 中（新文件+集成） | 新建 `agent/middleware/token_monitor.py` | 成本控制，前端可视化 |

### 推荐实施顺序

1. **第一步**（5 分钟）：修改 `main_agent.py` 的 config，添加 `recursion_limit: 50`
2. **第二步**（15 分钟）：添加 `ToolCallLimitMiddleware` 和 `ModelCallLimitMiddleware` 到 `create_deep_agent()` 的 middleware 参数
3. **第三步**（30 分钟）：实现 `DeduplicationMiddleware`
4. **第四步**（30 分钟）：实现 `TokenMonitorMiddleware`

前三步完成后，项目将拥有从"硬兜底 → 轮次限制 → 精准拦截"的三层防护体系。

---

## 架构示意

```
用户请求
    │
    ▼
┌──────────────────────────────────────────┐
│  run_main_agent(config)                   │
│  ┌────────────────────────────────────┐   │
│  │ config.recursion_limit = 50  ◄────│───│── 方案三：硬兜底（LangGraph 层）
│  └────────────────────────────────────┘   │
│           │                               │
│           ▼                               │
│  main_agent.astream()                     │
│  ┌────────────────────────────────────┐   │
│  │ Middleware 栈（按执行顺序）:        │   │
│  │                                    │   │
│  │ 1. ModelCallLimitMiddleware  ◄─────│───│── 方案二：限制 LLM 调用轮次
│  │    run_limit=30, thread_limit=50    │   │
│  │                                    │   │
│  │ 2. ToolCallLimitMiddleware   ◄─────│───│── 方案一：限制工具调用次数
│  │    (all: run_limit=20)             │   │
│  │    (internet_search: run_limit=5)  │   │
│  │                                    │   │
│  │ 3. DeduplicationMiddleware   ◄─────│───│── 方案五：检测重复调用并阻断
│  │    max_identical_calls=3           │   │
│  │                                    │   │
│  │ 4. TokenMonitorMiddleware    ◄─────│───│── 方案四：Token 消耗监控
│  │    max_run_tokens=100000           │   │
│  │                                    │   │
│  │ 5. [DeepAgents 内置]               │   │
│  │    TodoList / Summarization        │   │
│  │    / SubAgent middleware           │   │
│  └────────────────────────────────────┘   │
└──────────────────────────────────────────┘
```
