"""
SQL 解析工具 — 检测写操作。

用于 HITL 审批流程：在 excute_sql_query 执行前，
判断 SQL 是否为写操作（INSERT/UPDATE/DELETE/DROP 等），
若为写操作则需要走人工审批。
"""

import re
from typing import Tuple

# 写操作关键字及其正则模式
# 顺序重要：更具体的放前面，避免误匹配
WRITE_PATTERNS = [
    (r'\bINSERT\s+INTO\b', "INSERT"),
    (r'\bUPDATE\b', "UPDATE"),
    (r'\bDELETE\s+FROM\b', "DELETE"),
    (r'\bDROP\s+(TABLE|DATABASE|INDEX|VIEW|SCHEMA)\b', "DROP"),
    (r'\bALTER\s+(TABLE|DATABASE)\b', "ALTER"),
    (r'\bTRUNCATE\s+(TABLE\s+)?\b', "TRUNCATE"),
    (r'\bCREATE\s+(TABLE|DATABASE|INDEX|VIEW)\b', "CREATE"),
    (r'\bREPLACE\s+INTO\b', "REPLACE"),
    (r'\bRENAME\s+(TABLE)\b', "RENAME"),
    (r'\bGRANT\b', "GRANT"),
    (r'\bREVOKE\b', "REVOKE"),
]


def parse_sql(query: str) -> Tuple[bool, str]:
    """
    检测 SQL 是否包含写操作。

    处理能力：
    - 行注释 (-- ...)
    - 块注释 (/* ... */)
    - 大小写不敏感
    - 多语句（分号分隔，任一语句含写操作即判定为写）

    Args:
        query: 原始 SQL 语句

    Returns:
        (is_write: bool, detected_operation: str)
        - is_write: True 表示包含写操作
        - detected_operation: 匹配到的操作类型（如 "INSERT", "DROP"），无则为空字符串
    """
    if not query or not query.strip():
        return False, ""

    # 清除注释
    cleaned = re.sub(r'--.*?$', '', query, flags=re.MULTILINE)   # 行注释
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)  # 块注释

    # 按分号拆分为多条语句
    statements = [s.strip() for s in cleaned.split(';') if s.strip()]

    for stmt in statements:
        stmt_upper = stmt.upper()
        for pattern, label in WRITE_PATTERNS:
            if re.search(pattern, stmt_upper):
                return True, label

    return False, ""
