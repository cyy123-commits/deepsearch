"""工具返回去重中间件。

检测 LLM 是否反复用相同参数调用同一工具并得到相同结果，
一旦检测到连续重复则阻断调用，提示 LLM 更换策略。

历史记录存储在中间件实例上（按 thread_id 隔离），
每个 run 开始时的首次调用自动作为新起点的基准。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import ToolMessage
from typing_extensions import override

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ResponseT,
)


def _canonicalize_args(args: dict[str, Any]) -> str:
    """将工具参数规范化为排序后的 JSON 字符串，用于哈希比较。

    处理:
    1. 剔除 None 值
    2. 字符串值做 strip()
    3. 按 key 排序
    """
    cleaned = {}
    for k, v in args.items():
        if v is None:
            continue
        if isinstance(v, str):
            cleaned[k] = v.strip()
        elif isinstance(v, (int, float, bool)):
            cleaned[k] = v
        elif isinstance(v, (list, tuple)):
            cleaned[k] = [
                (item.strip() if isinstance(item, str) else item) for item in v
            ]
        elif isinstance(v, dict):
            cleaned[k] = _canonicalize_args(v)
        else:
            cleaned[k] = str(v)

    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False)


def _hash_content(content: str) -> str:
    """对内容计算 MD5 哈希（短哈希，够用于去重检测）。"""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


def _extract_result_text(result: Any) -> str:
    """从工具返回结果中提取文本用于哈希比较。

    只取前 4096 字节用于哈希（大结果场景下避免性能问题）。
    """
    if isinstance(result, ToolMessage):
        content = result.content
    elif isinstance(result, dict):
        content = json.dumps(result, sort_keys=True, ensure_ascii=False)
    else:
        content = str(result)

    if isinstance(content, str):
        return content[:4096]
    if isinstance(content, list):
        text_parts = [str(c) for c in content if isinstance(c, str)]
        return "".join(text_parts)[:4096]
    return str(content)[:4096]


class DeduplicationMiddleware(
    AgentMiddleware[AgentState[ResponseT], Any, ResponseT]
):
    """检测并阻断重复工具调用。

    当同一工具以相同参数被调用 >=max_identical_calls 次时，
    返回错误 ToolMessage 阻断调用，提示 LLM 更换策略。

    使用方式:
        ```python
        from agent.middleware.dedup import DeduplicationMiddleware

        dedup = DeduplicationMiddleware(
            max_identical_calls=3,
            dedup_window=20,
        )
        agent = create_deep_agent(..., middleware=[dedup])
        ```
    """

    def __init__(
        self,
        max_identical_calls: int = 3,
        dedup_window: int = 20,
    ) -> None:
        """初始化去重中间件。

        Args:
            max_identical_calls: 允许相同参数调用的最大次数（含首次）。
                设为 3 表示：第 1-2 次放行，第 3 次阻断。
            dedup_window: 滑动窗口大小，每个 thread 最多记忆 N 条记录。
        """
        super().__init__()
        if max_identical_calls < 2:
            raise ValueError(
                "max_identical_calls 至少为 2（否则无法区分正常调用和重复）"
            )
        if dedup_window < 1:
            raise ValueError("dedup_window 至少为 1")

        self.max_identical_calls = max_identical_calls
        self.dedup_window = dedup_window

        # 按 thread_id 隔离的历史存储
        # 结构: {thread_id: [{"tool_name": str, "args_hash": str, "result_hash": str, "count": int}, ...]}
        self._history: dict[str, list[dict[str, Any]]] = {}

    # ---------- thread_id 提取 ----------

    def _get_thread_id(self, request: Any) -> str:
        """从 ToolCallRequest 中提取 thread_id。"""
        try:
            runtime = request.runtime
            configurable = getattr(runtime, "configurable", {}) or {}
            return configurable.get("thread_id", "__default__")
        except Exception:
            return "__default__"

    # ---------- 历史查询与更新 ----------

    def _get_history(self, thread_id: str) -> list[dict[str, Any]]:
        """获取指定 thread 的调用历史（惰性初始化）。"""
        if thread_id not in self._history:
            self._history[thread_id] = []
        return self._history[thread_id]

    def _find_in_history(
        self,
        history: list[dict[str, Any]],
        tool_name: str,
        args_hash: str,
    ) -> dict[str, Any] | None:
        """在历史中查找匹配记录，返回找到的记录或 None。"""
        for record in history:
            if record["tool_name"] == tool_name and record["args_hash"] == args_hash:
                return record
        return None

    def _prune_history(self, history: list[dict[str, Any]]) -> None:
        """滑动窗口裁剪。"""
        if len(history) > self.dedup_window:
            del history[: len(history) - self.dedup_window]

    # ---------- 核心 hook ----------

    @override
    async def awrap_tool_call(
        self,
        request: Any,   # ToolCallRequest
        handler: Any,   # Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]
    ) -> ToolMessage | Any:
        """异步拦截工具调用，检测并阻断重复调用。

        流程:
        1. 计算 (tool_name, args) 的规范化哈希
        2. 查询该 thread 的历史记录
        3. 若相同参数已达上限 → 阻断，返回 error ToolMessage
        4. 若接近上限且上次结果相同 → 放行，但在结果后追加警告
        5. 否则正常放行，记录结果哈希到历史
        """
        tool_call = request.tool_call
        tool_name = tool_call.get("name", "unknown")
        args = tool_call.get("args", {})

        thread_id = self._get_thread_id(request)

        # 规范化参数并哈希
        try:
            canonical_args = _canonicalize_args(args)
            args_hash = _hash_content(canonical_args)
        except Exception:
            return await handler(request)

        history = self._get_history(thread_id)
        record = self._find_in_history(history, tool_name, args_hash)

        # --- 阻断判断 ---
        if record is not None and record["count"] >= self.max_identical_calls:
            blocked_msg = (
                f"工具调用被去重中间件阻止：你已连续 {record['count']} 次使用相同参数调用 "
                f"'{tool_name}' 且结果相同。请立即停止调用此工具，改用其他策略或基于已有信息给出最终答案。"
            )
            return ToolMessage(
                content=blocked_msg,
                tool_call_id=tool_call["id"],
                name=tool_name,
                status="error",
            )

        # --- 放行：执行工具 ---
        result = await handler(request)

        # --- 记录结果 ---
        result_text = _extract_result_text(result)
        result_hash = _hash_content(result_text)

        if record is not None:
            # 已有记录：递增计数
            old_result_hash = record["result_hash"]
            record["count"] += 1
            record["result_hash"] = result_hash

            # 接近上限 + 结果相同 → 追加警告
            if record["count"] >= self.max_identical_calls - 1 and result_hash == old_result_hash:
                warning = (
                    f"\n\n[系统提示] 你已经 {record['count']} 次使用相同参数调用 '{tool_name}' "
                    f"且结果相同。如果再次重复调用，将被系统阻止。请换一种策略。"
                )
                if isinstance(result, ToolMessage):
                    result = ToolMessage(
                        content=(result.content or "") + warning,
                        tool_call_id=result.tool_call_id,
                        name=getattr(result, "name", tool_name),
                        status=result.status,
                    )
        else:
            # 新记录
            history.append({
                "tool_name": tool_name,
                "args_hash": args_hash,
                "result_hash": result_hash,
                "count": 1,
            })

        self._prune_history(history)
        return result
