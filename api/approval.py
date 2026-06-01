"""
HITL (Human-in-the-Loop) 审批注册表

核心机制：
- 工具函数中创建审批请求 → await Future 阻塞等待
- 前端 WebSocket 回传审批结果 → resolve Future 解除阻塞
- 超时自动拒绝，客户端断连自动清理

隔离保证：每个审批请求都有唯一的 approval_id，通过 thread_id 做会话隔离。
"""

import asyncio
import uuid
import datetime
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class ApprovalRequest:
    """单个审批请求的数据结构"""
    approval_id: str
    approval_type: str          # "sql_write" | "content_review" | "plan_confirmation"
    thread_id: str
    future: asyncio.Future
    payload: Dict[str, Any]     # 展示给用户的数据
    created_at: str
    timeout: int = 120          # 超时秒数


class ApprovalRegistry:
    """
    审批注册表单例。

    生命周期：
    1. 工具函数 create_approval() → Future 存入 _pending
    2. 工具函数 await wait_for_approval() → 协程挂起
    3. 前端 WebSocket → resolve() → Future.set_result() → 协程恢复
    4. 超时或断连 → Future 被取消/拒绝
    """

    _instance: Optional["ApprovalRegistry"] = None

    def __new__(cls) -> "ApprovalRegistry":
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._pending: Dict[str, ApprovalRequest] = {}
            obj._lock = asyncio.Lock()
            cls._instance = obj
        return cls._instance

    async def create_approval(
        self,
        approval_type: str,
        thread_id: str,
        payload: Dict[str, Any],
        timeout: int = 120,
    ) -> ApprovalRequest:
        """
        创建一个待审批请求并返回。

        Args:
            approval_type: 审批类型标识（如 "sql_write"）
            thread_id: 所属会话 ID
            payload: 展示给用户的数据（SQL 语句等）
            timeout: 超时秒数

        Returns:
            创建好的 ApprovalRequest 对象（含 future，尚未等待）
        """
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        req = ApprovalRequest(
            approval_id=approval_id,
            approval_type=approval_type,
            thread_id=thread_id,
            future=future,
            payload=payload,
            created_at=datetime.datetime.now().isoformat(),
            timeout=timeout,
        )

        async with self._lock:
            self._pending[approval_id] = req

        return req

    async def wait_for_approval(self, approval_id: str) -> Dict[str, Any]:
        """
        等待审批结果。会阻塞当前协程直到审批完成或超时。

        Returns:
            {"action": "approve"|"reject", "reason": "...", "modifications": {...}}
        """
        req = self._pending.get(approval_id)
        if not req:
            return {"action": "reject", "reason": "审批请求不存在或已过期"}

        try:
            result = await asyncio.wait_for(req.future, timeout=req.timeout)
            return result
        except asyncio.TimeoutError:
            return {"action": "reject", "reason": "审批超时，已自动拒绝"}
        finally:
            async with self._lock:
                self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, result: Dict[str, Any]) -> bool:
        """
        用前端返回的结果解析一个待审批请求。

        Returns:
            True 表示成功解析，False 表示审批不存在或已处理
        """
        req = self._pending.get(approval_id)
        if not req or req.future.done():
            return False

        req.future.set_result(result)
        return True

    def cancel_all_for_thread(self, thread_id: str) -> int:
        """
        取消指定会话的所有待审批请求（客户端断连时调用）。

        Returns:
            取消的审批数量
        """
        cancelled = 0
        for req in list(self._pending.values()):
            if req.thread_id == thread_id and not req.future.done():
                req.future.set_result({
                    "action": "reject",
                    "reason": "客户端已断开连接"
                })
                cancelled += 1
        return cancelled


# 全局单例
approval_registry = ApprovalRegistry()
