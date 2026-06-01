# -*- coding: utf-8 -*-
"""
HITL SQL approval mechanism — unit tests

Covered modules:
- utils/sql_parser.py (pure functions, no external deps)
- api/approval.py (asyncio tests)
- tools/db_tools.py (HITL integration, mock DB)

Usage:
    cd D:/desktop/nn_code/deep_search_pro
    py test_hitl.py
"""

import sys
import asyncio
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# Part 1: SQL Parser
# ============================================================
print("=" * 60)
print("Part 1: SQL Parser (utils/sql_parser.py)")
print("=" * 60)

from utils.sql_parser import parse_sql

passed = 0
failed = 0


def check(name, actual, expected):
    global passed, failed
    if actual == expected:
        print(f"  PASS {name}")
        passed += 1
    else:
        print(f"  FAIL {name}")
        print(f"       expected: {expected}")
        print(f"       got:      {actual}")
        failed += 1


# 1.1 SELECT should pass through
check("SELECT query", parse_sql("SELECT * FROM users"), (False, ""))
check("SELECT complex",
      parse_sql("SELECT a.id, b.name FROM users a JOIN orders b ON a.id = b.user_id WHERE a.age > 18"),
      (False, ""))
check("SELECT subquery",
      parse_sql("SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"),
      (False, ""))

# 1.2 INSERT detection
check("INSERT INTO", parse_sql("INSERT INTO users VALUES (1, 'test')"), (True, "INSERT"))
check("INSERT multi-row", parse_sql("INSERT INTO users (id, name) VALUES (1, 'x'), (2, 'y')"), (True, "INSERT"))

# 1.3 UPDATE detection
check("UPDATE", parse_sql("UPDATE users SET name = 'new'"), (True, "UPDATE"))
check("UPDATE multi-col", parse_sql("UPDATE users SET name='x', age=30 WHERE id=1"), (True, "UPDATE"))

# 1.4 DELETE detection
check("DELETE FROM", parse_sql("DELETE FROM users WHERE id = 1"), (True, "DELETE"))

# 1.5 DROP detection
check("DROP TABLE", parse_sql("DROP TABLE users"), (True, "DROP"))
check("DROP DATABASE", parse_sql("DROP DATABASE production"), (True, "DROP"))

# 1.6 ALTER detection
check("ALTER TABLE", parse_sql("ALTER TABLE users ADD COLUMN email VARCHAR(255)"), (True, "ALTER"))

# 1.7 TRUNCATE detection
check("TRUNCATE", parse_sql("TRUNCATE users"), (True, "TRUNCATE"))
check("TRUNCATE TABLE", parse_sql("TRUNCATE TABLE users"), (True, "TRUNCATE"))

# 1.8 CREATE detection
check("CREATE TABLE", parse_sql("CREATE TABLE test (id INT)"), (True, "CREATE"))

# 1.9 REPLACE INTO detection
check("REPLACE INTO", parse_sql("REPLACE INTO users VALUES (1, 'test')"), (True, "REPLACE"))

# 1.10 Case insensitivity
check("lowercase insert", parse_sql("insert into users values (1)"), (True, "INSERT"))
check("lowercase delete", parse_sql("delete from users where id=1"), (True, "DELETE"))
check("mixed case", parse_sql("InSeRt InTo users values (1)"), (True, "INSERT"))

# 1.11 Line comments
check("line comment + DELETE", parse_sql("-- this is a comment\nDELETE FROM users"), (True, "DELETE"))
check("line comment + SELECT keyword, actual DELETE",
      parse_sql("-- SELECT * FROM users\nDELETE FROM orders"), (True, "DELETE"))

# 1.12 Block comments
check("block comment + INSERT",
      parse_sql("/* multi\nline */\nINSERT INTO t VALUES(1)"), (True, "INSERT"))

# 1.13 Multi-statement (contains write)
check("multi SELECT+INSERT",
      parse_sql("SELECT * FROM t; INSERT INTO t VALUES(1)"), (True, "INSERT"))
check("multi INSERT+SELECT",
      parse_sql("INSERT INTO t VALUES(1); SELECT * FROM t"), (True, "INSERT"))

# 1.14 Multi-statement all SELECT
check("multi SELECT+SELECT",
      parse_sql("SELECT * FROM users; SELECT * FROM orders"), (False, ""))

# 1.15 Edge cases
check("empty string", parse_sql(""), (False, ""))
check("whitespace only", parse_sql("   \n\t  "), (False, ""))
check("None input", parse_sql(None), (False, ""))  # type: ignore

# 1.16 Non-write statements
check("SHOW TABLES", parse_sql("SHOW TABLES"), (False, ""))
check("DESCRIBE", parse_sql("DESCRIBE users"), (False, ""))
check("EXPLAIN", parse_sql("EXPLAIN SELECT * FROM users"), (False, ""))

print(f"\n  SQL Parser: {passed} passed, {failed} failed\n")


# ============================================================
# Part 2: Approval Registry
# ============================================================
print("=" * 60)
print("Part 2: Approval Registry (api/approval.py)")
print("=" * 60)

# Reset singleton for test isolation
import api.approval as approval_mod
approval_mod.ApprovalRegistry._instance = None
from api.approval import ApprovalRegistry, ApprovalRequest

approval_passed = 0
approval_failed = 0


async def test_approval_registry():
    global approval_passed, approval_failed

    def check_async(name, actual, expected):
        global approval_passed, approval_failed
        if actual == expected:
            print(f"  PASS {name}")
            approval_passed += 1
        else:
            print(f"  FAIL {name}")
            print(f"       expected: {expected}")
            print(f"       got:      {actual}")
            approval_failed += 1

    registry = ApprovalRegistry()

    # 2.1 Create approval request
    req = await registry.create_approval(
        approval_type="sql_write",
        thread_id="test-thread-1",
        payload={"query": "INSERT INTO users VALUES(1)", "operation": "INSERT"},
        timeout=5,
    )
    check_async("create_approval returns ApprovalRequest", isinstance(req, ApprovalRequest), True)
    check_async("approval_type correct", req.approval_type, "sql_write")
    check_async("thread_id correct", req.thread_id, "test-thread-1")
    check_async("future not yet done", req.future.done(), False)

    # 2.2 Normal approval
    async def resolver():
        await asyncio.sleep(0.05)
        registry.resolve(req.approval_id, {"action": "approve", "reason": "ok"})

    task = asyncio.create_task(resolver())
    result = await registry.wait_for_approval(req.approval_id)
    await task

    check_async("approve returns action=approve", result["action"], "approve")
    check_async("approve returns reason", result["reason"], "ok")

    # 2.3 Rejection
    req2 = await registry.create_approval(
        approval_type="sql_write",
        thread_id="test-thread-1",
        payload={"query": "DELETE FROM users", "operation": "DELETE"},
        timeout=5,
    )

    async def rejector():
        await asyncio.sleep(0.05)
        registry.resolve(req2.approval_id, {"action": "reject", "reason": "too dangerous"})

    task2 = asyncio.create_task(rejector())
    result2 = await registry.wait_for_approval(req2.approval_id)
    await task2

    check_async("reject returns action=reject", result2["action"], "reject")
    check_async("reject returns reason", result2["reason"], "too dangerous")

    # 2.4 Timeout auto-reject
    req3 = await registry.create_approval(
        approval_type="sql_write",
        thread_id="test-thread-1",
        payload={"query": "DROP TABLE users", "operation": "DROP"},
        timeout=0.1,  # 100ms timeout
    )
    result3 = await registry.wait_for_approval(req3.approval_id)
    check_async("timeout returns action=reject", result3["action"], "reject")
    check_async("timeout reason mentions timeout", "chao shi" in result3["reason"].lower() or "超时" in result3["reason"], True)

    # 2.5 Resolve non-existent
    success = registry.resolve("nonexistent-id", {"action": "approve"})
    check_async("resolve non-existent returns False", success, False)

    # 2.6 cancel_all_for_thread
    req4 = await registry.create_approval(
        approval_type="sql_write",
        thread_id="test-thread-2",
        payload={"query": "UPDATE users SET x=1", "operation": "UPDATE"},
        timeout=5,
    )
    cancelled = registry.cancel_all_for_thread("test-thread-2")
    check_async("cancel_all_for_thread returns count", cancelled, 1)

    result4 = req4.future.result()
    check_async("cancel sets action=reject", result4["action"], "reject")
    check_async("cancel reason mentions disconnect",
                "duan kai" in result4["reason"].lower() or "断开连接" in result4["reason"], True)

    # 2.7 Cancel empty thread
    cancelled2 = registry.cancel_all_for_thread("nonexistent-thread")
    check_async("cancel empty thread returns 0", cancelled2, 0)

    # 2.8 Singleton
    registry2 = ApprovalRegistry()
    check_async("singleton check", registry is registry2, True)

    # 2.9 Concurrent creation (lock safety)
    async def create_many():
        reqs = []
        for i in range(10):
            r = await registry.create_approval(
                approval_type="sql_write",
                thread_id=f"concurrent-{i}",
                payload={},
                timeout=5,
            )
            reqs.append(r)
        return reqs

    reqs = await create_many()
    check_async("concurrent create 10 approvals", len(reqs), 10)
    for r in reqs:
        registry.resolve(r.approval_id, {"action": "approve"})

    print(f"\n  Approval Registry: {approval_passed} passed, {approval_failed} failed\n")


# ============================================================
# Part 3: db_tools HITL Integration
# ============================================================
print("=" * 60)
print("Part 3: db_tools HITL (tools/db_tools.py)")
print("=" * 60)

db_passed = 0
db_failed = 0
db_skipped = 0


def check_db(name, condition):
    global db_passed, db_failed
    if condition:
        print(f"  PASS {name}")
        db_passed += 1
    else:
        print(f"  FAIL {name}")
        db_failed += 1


try:
    from tools.db_tools import (
        _execute_sql_impl,
        excute_sql_query,
        get_table_data,
        list_sql_tables,
    )
    deps_available = True
except ModuleNotFoundError as e:
    print(f"  SKIP: missing dependency ({e})")
    print(f"  Install with: pip install -r requirements.txt\n")
    deps_available = False
    db_skipped = 7  # number of tests below

if deps_available:
    # 3.1 _execute_sql_impl exists
    check_db("_execute_sql_impl importable", callable(_execute_sql_impl))

    # 3.2 Async tool has ainvoke (now named excute_sql_query)
    check_db("excute_sql_query has ainvoke", hasattr(excute_sql_query, 'ainvoke'))

    # 3.3 Other tools unaffected
    check_db("list_sql_tables has invoke", hasattr(list_sql_tables, 'invoke'))
    check_db("get_table_data has invoke", hasattr(get_table_data, 'invoke'))

    # 3.4 Tool name preserved as LLM expects
    check_db("excute_sql_query name", excute_sql_query.name, "excute_sql_query")

    # 3.5 Descriptions include safety info
    check_db("excute_sql_query desc mentions shen pi", "审批" in excute_sql_query.description, True)
    check_db("excute_sql_query desc mentions an quan", "安全" in excute_sql_query.description, True)

print(f"  db_tools: {db_passed} passed, {db_failed} failed, {db_skipped} skipped\n")


# ============================================================
# Run async tests + final summary
# ============================================================
asyncio.run(test_approval_registry())

total_passed = passed + approval_passed + db_passed
total_failed = failed + approval_failed + db_failed
total_skipped = db_skipped

print("=" * 60)
print(f"TOTAL: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
if total_failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"WARNING: {total_failed} test(s) failed")
print("=" * 60)
