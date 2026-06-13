"""Token 消耗监控中间件。

在每次模型调用后累加 token 消耗，超过阈值时主动终止任务，
防止死循环导致的 token 浪费和 API 费用失控。

通过 monitor 推送实时用量到前端 WebSocket。

会话累计 (thread) 使用实例级字典存储，按 thread_id 隔离，
不依赖 Graph State 持久化，确保跨多次 astream() 调用也能正确累加。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage
from typing_extensions import override

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ResponseT,
    hook_config,
)

if TYPE_CHECKING:
    from langgraph.runtime import Runtime


def _build_limit_exceeded_message(
    thread_total: int,
    max_thread_tokens: int | None,
) -> str:
    """构建超限提示消息。"""
    return (
        f"Token 消耗超限：会话累计 Token 已达上限 "
        f"({thread_total}/{max_thread_tokens})。"
        "请基于已有信息给出最终答案，不要再调用工具。"
    )


class TokenLimitExceededError(Exception):
    """Token 超限异常（exit_behavior="error" 时抛出）。"""

    def __init__(
        self,
        thread_total: int,
        max_thread_tokens: int | None,
    ) -> None:
        self.thread_total = thread_total
        self.max_thread_tokens = max_thread_tokens
        super().__init__(
            _build_limit_exceeded_message(thread_total, max_thread_tokens)
        )


class TokenMonitorMiddleware(
    AgentMiddleware[AgentState[ResponseT], ContextT, ResponseT]
):
    """监控 Token 消耗并在超限时终止执行。

    - **会话累计** (thread)：存储在实例级 `self._thread_totals[thread_id]`，
      跨多次 astream() 调用持续累加。
    - **本轮消耗** (run)：每次 astream() 内从 0 开始计数。
    - 推送事件到前端 WebSocket 供实时展示。

    使用方式:
        ```python
        token_monitor = TokenMonitorMiddleware(
            max_thread_tokens=300_000,
            exit_behavior="end",
        )
        agent = create_deep_agent(..., middleware=[token_monitor])
        ```
    """

    def __init__(
        self,
        *,
        max_run_tokens: int | None = None,
        max_thread_tokens: int | None = 300_000,
        exit_behavior: Literal["end", "error", "warn"] = "end",
    ) -> None:
        """初始化 Token 监控中间件。

        Args:
            max_run_tokens: 单次 run 的 token 消耗上限（None 表示不限制）
            max_thread_tokens: 同一会话累计 token 上限（None 表示不限制）
            exit_behavior:
                - "end": 跳转到终点，注入总结消息
                - "error": 抛出 TokenLimitExceededError 异常
                - "warn": 仅通过 monitor 推送警告，不阻断执行
        """
        super().__init__()

        if max_run_tokens is None and max_thread_tokens is None:
            msg = "至少需要设置 max_run_tokens 或 max_thread_tokens 中的一个"
            raise ValueError(msg)

        if exit_behavior not in ("end", "error", "warn"):
            msg = f"无效的 exit_behavior: {exit_behavior!r}，可选值: 'end', 'error', 'warn'"
            raise ValueError(msg)

        self.max_run_tokens = max_run_tokens
        self.max_thread_tokens = max_thread_tokens
        self.exit_behavior = exit_behavior

        # 实例级存储：按 thread_id 隔离，不依赖 Graph State 持久化
        # thread_totals: 会话累计 token（跨 astream() 持续累加）
        # model_call_count: 会话累计模型调用次数（前端用于判断是否度过初始提示词阶段）
        self._thread_totals: dict[str, dict[str, int]] = {}
        self._model_call_counts: dict[str, int] = {}

    # ---------- thread_id 提取 ----------

    def _get_thread_id(self, runtime: Runtime[ContextT]) -> str:
        """从 runtime 中提取 thread_id。"""
        try:
            configurable = getattr(runtime, "configurable", {}) or {}
            return configurable.get("thread_id", "__default__")
        except Exception:
            return "__default__"

    # ---------- token 提取 ----------

    def _extract_token_usage(self, message: AIMessage) -> dict[str, int] | None:
        """从 AIMessage 中提取 token 消耗信息。

        优先读取 usage_metadata，若不可用则用字符数粗略估算。
        """
        # 方式 1: usage_metadata（LangChain 标准属性）
        usage = getattr(message, "usage_metadata", None)
        if usage and isinstance(usage, dict):
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
            if total_tokens > 0:
                return {
                    "input": input_tokens,
                    "output": output_tokens,
                    "total": total_tokens,
                }

        # 方式 2: response_metadata 中的 token_usage（OpenAI 格式）
        resp_meta = getattr(message, "response_metadata", {}) or {}
        token_usage = resp_meta.get("token_usage", {})
        if token_usage:
            input_t = token_usage.get("prompt_tokens", 0)
            output_t = token_usage.get("completion_tokens", 0)
            total_t = token_usage.get("total_tokens", input_t + output_t)
            if total_t > 0:
                return {"input": input_t, "output": output_t, "total": total_t}

        # 方式 3: 退化为字符估算
        content = message.content
        if isinstance(content, str) and len(content) > 0:
            estimated = max(1, len(content) // 2)
            return {"input": 0, "output": estimated, "total": estimated}

        return None

    # ---------- 前端推送 ----------

    def _emit_monitor_event(
        self,
        run_total: int,
        thread_total: int,
        model_call_count: int,
    ) -> None:
        """通过 monitor 向前端推送 token 用量更新。"""
        try:
            from api.monitor import monitor

            monitor._emit(
                "token_usage",
                f"Token 用量: 本轮 {run_total} / 累计 {thread_total}",
                {
                    "run_total": run_total,
                    "thread_total": thread_total,
                    "max_run_tokens": self.max_run_tokens,
                    "max_thread_tokens": self.max_thread_tokens,
                    "model_call_count": model_call_count,
                },
            )
        except Exception:
            pass

    # ---------- 核心 hook ----------

    @hook_config(can_jump_to=["end"])
    @override
    def after_model(
        self,
        state: AgentState[ResponseT],
        runtime: Runtime[ContextT],
    ) -> dict[str, Any] | None:
        """模型调用后累加 token 消耗并检查阈值。"""
        messages = state.get("messages", [])
        if not messages:
            return None

        # 找到最新的 AIMessage
        last_ai = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_ai = msg
                break

        if last_ai is None:
            return None

        # 提取本次 token 消耗
        usage = self._extract_token_usage(last_ai)
        if usage is None:
            return None

        thread_id = self._get_thread_id(runtime)

        # --- 本轮累计 (run)：从 state 读取，每次 astream() 自动重置 ---
        run_usage = state.get("run_token_usage", {"input": 0, "output": 0, "total": 0}).copy()
        for key in ("input", "output", "total"):
            run_usage[key] = run_usage.get(key, 0) + usage.get(key, 0)

        # --- 会话累计 (thread)：实例级存储，跨 astream() 持久化 ---
        if thread_id not in self._thread_totals:
            self._thread_totals[thread_id] = {"input": 0, "output": 0, "total": 0}
        thread_usage = self._thread_totals[thread_id]
        for key in ("input", "output", "total"):
            thread_usage[key] = thread_usage.get(key, 0) + usage.get(key, 0)

        # 会话累计模型调用次数
        self._model_call_counts[thread_id] = self._model_call_counts.get(thread_id, 0) + 1
        model_call_count = self._model_call_counts[thread_id]

        # 推送实时用量到前端
        self._emit_monitor_event(
            run_total=run_usage["total"],
            thread_total=thread_usage["total"],
            model_call_count=model_call_count,
        )

        # 检查是否超限
        run_exceeded = (
            self.max_run_tokens is not None
            and run_usage["total"] >= self.max_run_tokens
        )
        thread_exceeded = (
            self.max_thread_tokens is not None
            and thread_usage["total"] >= self.max_thread_tokens
        )

        result: dict[str, Any] = {
            "run_token_usage": run_usage,
            "model_call_count": model_call_count,
        }

        if run_exceeded or thread_exceeded:
            if self.exit_behavior == "warn":
                return result

            if self.exit_behavior == "error":
                raise TokenLimitExceededError(
                    thread_total=thread_usage["total"],
                    max_thread_tokens=self.max_thread_tokens,
                )

            if self.exit_behavior == "end":
                limit_msg = _build_limit_exceeded_message(
                    thread_usage["total"],
                    self.max_thread_tokens,
                )
                result["jump_to"] = "end"
                result["messages"] = [AIMessage(content=limit_msg)]
                return result

        return result

    @hook_config(can_jump_to=["end"])
    async def aafter_model(
        self,
        state: AgentState[ResponseT],
        runtime: Runtime[ContextT],
    ) -> dict[str, Any] | None:
        """异步版本。"""
        return self.after_model(state, runtime)
