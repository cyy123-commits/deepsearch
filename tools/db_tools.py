import os
import asyncio
from dotenv import load_dotenv
from api.monitor import monitor
from api.approval import approval_registry
from api.context import get_thread_context
from utils.sql_parser import parse_sql
from mysql.connector import connect, Error
from typing import Annotated, List
from langchain_core.tools import tool

load_dotenv()


# 加载配置文件方便后续使用
def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),
        "collation": os.getenv("MYSQL_COLLATION", "utf8mb4_unicode_ci"),
        "autocommit": True,
        "sql_mode": os.getenv("MYSQL_SQL_MODE", "TRADITIONAL")
    }
    # 移除 None 值（核心必要操作）
    config = {k: v for k, v in config.items() if v is not None}

    # 补充：校验核心配置是否存在（可选但推荐）
    required_keys = ["user", "password", "database"]
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        raise ValueError(f"缺失数据库核心配置：{', '.join(missing_keys)}")

    return config

@tool
#工具1获取数据库中的表
def list_sql_tables() -> str:
    """
        列出配置的 MySQL 数据库中所有可用的表。
    核心用途：
        AI Agent 需要查看数据库中有哪些表时调用，为后续执行 SQL 查询提供基础信息。
    返回值：
        str: 成功时返回 "可用数据表：表1, 表2, ..."；
             配置缺失时返回错误提示；
             执行异常时返回具体错误信息。
    异常处理：
        捕获数据库连接/执行 SQL 时的所有 Error 异常，返回可读的错误信息，避免 Agent 崩溃。
    :return:
    """

    config=get_db_config()
    #websocket向前端返回消息
    monitor.report_tool(tool_name="获取数据库表名工具")
    try:
        #建立数据库连接
        with connect(**config) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                tables= cursor.fetchall()  # 获取所有查询结果（返回格式：列表嵌套元组，如 [('user',), ('order',)]）
                if not tables:
                    return "数据库中未找到任何数据表。"
                tables_names=[table[0] for table in tables]
                return f"可用数据表:{", ".join(tables_names)}"
    except Error as e:
        print(f"数据库连接失败{str(e)}")

@tool
# 工具2
def get_table_data(table_name: str) -> str:
    """
    查询指定表名的数据，当前工具调用之前必须调用list_sql_tables完成表明的校验。
    此工具的作用：1，可以对单表进行查询。2，可以为多表查询日工表结果信息（列名&表结构）

    :param table_name: 表名
    :return: csv格式的数据（模拟表格数据格式）
                1.第一行是列信息，列之间使用英文逗号分隔
                2.第二行开始是表数据，值之间也是用英文逗号分隔
                3，行和行用\n分隔
                4.至多有一百行表数据
                例如：
                id,name,age\n
                1,2,yy\n
                2,3,mm\n
    """
    #监控
    monitor.report_tool(tool_name="获取表中数据工具",args={"table_name":table_name})
    try:
        with connect(**get_db_config()) as conn:
            with conn.cursor() as cursor:
                sql=f"select * from {table_name} limit 100"
                cursor.execute(sql)
                # cursor获取返回结果
                  #获取列名，从cursor.description中获取列信息，这里包含的就是列信息，从中取出第一个就是列名
                    #他返回的是[(),(),()],并且如果没有列信息或者没有表信息，就不会获取到
                description=cursor.description
                if not description:
                    return f"数据表{table_name}为空"
                #返回列名表格
                columns=[desc[0] for desc in description]   #[1,2,3]

                #表数据
                rows=cursor.fetchall() #[(),(),()]
                #把元组中元素都变成字符串，用逗号隔开，变成字符串组成的列表 ['1,2','2,3']
                data=[",".join(map(str,row)) for row in rows]

                #csv的head，把columns中的元素用逗号隔开
                head=",".join(columns)

                #数据用换行符隔开
                data_res="\n".join(data)

                return f"{head}\n{data_res}"

    except Error as e:
        print(f"查询出现异常：{str(e)}")

# 工具三：核心 SQL 执行逻辑（纯函数，不做审批）
def _execute_sql_impl(query: str) -> str:
    """执行 SQL 查询的底层实现，不应直接作为工具暴露。"""
    try:
        with connect(**get_db_config()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                description = cursor.description
                if not description:
                    return f"执行自定义sql语句{query}查询没结果数据表"
                columns = [desc[0] for desc in description]
                rows = cursor.fetchall()
                data = [",".join(map(str, row)) for row in rows]
                head = ",".join(columns)
                data_res = "\n".join(data)
                return f"{head}\n{data_res}"
    except Error as e:
        return f"查询出现异常：{str(e)}"


# 工具三（异步版）：带 HITL 审批的 SQL 执行（主入口，Agent 使用此工具）
@tool
async def excute_sql_query(query: str) -> str:
    """
    执行自定义的查询sql语句，切记，执行之前，需要通过list_sql_tables明确表名，执行get_table_data明确表结构和数据格式

    安全机制：对于 INSERT/UPDATE/DELETE/DROP/ALTER 等写操作，需要人工审批后才能执行。

    :param query: sql语句
    :return:csv格式的数据（模拟表格数据格式）
                1.第一行是列信息，列之间使用英文逗号分隔
                2.第二行开始是表数据，值之间也是用英文逗号分隔
                3，行和行用\\n分隔
                4.至多有一百行表数据
    """

    # 监控
    monitor.report_tool(tool_name="数据库数据查询工具", args={"query": query})

    # === HITL: SQL 写操作检测 ===
    is_write, operation = parse_sql(query)

    if is_write:
        thread_id = get_thread_context() or "unknown"

        # 创建审批请求
        req = await approval_registry.create_approval(
            approval_type="sql_write",
            thread_id=thread_id,
            payload={
                "query": query,
                "operation": operation,
            },
            timeout=120,
        )

        # 通知前端
        monitor.report_approval_required(
            approval_id=req.approval_id,
            approval_type="sql_write",
            payload={
                "query": query,
                "operation": operation,
            },
            message=f"检测到SQL写入操作 ({operation})，需要审批",
        )

        # 等待审批结果
        result = await approval_registry.wait_for_approval(req.approval_id)

        if result["action"] == "reject":
            reason = result.get("reason", "用户拒绝了该操作")
            print(f"[HITL] SQL写操作被拒绝: {reason}")
            return f"SQL执行被拒绝。原因: {reason}"

        elif result["action"] == "modify":
            modified_query = result.get("modifications", {}).get("modified_query", "")
            if modified_query and modified_query != query:
                query = modified_query
                print(f"[HITL] SQL已修改为: {query[:200]}")

    # 执行 SQL
    return _execute_sql_impl(query)


# 同步版 SQL 执行（纯函数，用于脚本/测试等非异步上下文）
def _excute_sql_sync(query: str) -> str:
    """同步版 SQL 执行，不注册为 LangChain 工具。用于脚本和测试。"""
    monitor.report_tool(tool_name="数据库数据查询工具", args={"query": query})

    is_write, operation = parse_sql(query)

    if is_write:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            print(f"[HITL] 非异步上下文，跳过审批直接执行SQL")
        else:
            return (
                f"检测到SQL写入操作 ({operation})，需要人工审批。\n"
                f"请通过 Agent 的 excute_sql_query 工具调用以触发审批流程。\n"
                f"SQL语句: {query}"
            )

    return _execute_sql_impl(query)




if __name__ == '__main__':
    print(_excute_sql_sync("select * from drugs dgs join sales_records srd on dgs.drug_id = srd.drug_id"))