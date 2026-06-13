from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content

from agent.subagents.database_query import database_query_agent
from agent.subagents.net_work_agent import net_work_search
from agent.subagents.knowledge_base_agent import knowledge_base_agent

from deepagents import create_deep_agent

from agent.llm import model
from agent.prompts import main_agent_content

from api.monitor import monitor
import asyncio
import uuid
import shutil
from pathlib import Path

from api.context import set_session_context, reset_session_context, set_thread_context

from langchain_core.messages import AIMessage

# --- 死循环防护中间件 ---
from langchain.agents.middleware.tool_call_limit import ToolCallLimitMiddleware
from agent.middleware.token_monitor import TokenMonitorMiddleware
from agent.middleware.dedup import DeduplicationMiddleware

# 方案一：工具调用次数限制
#   - 全局所有工具：单次 run 最多  次调用
#   - 网络搜索工具：单次 run 最多  次调用（与 prompts.yml 软约束一致 + 代码硬执行）
tool_call_limiter_all = ToolCallLimitMiddleware(
    tool_name=None,       # None = 追踪全部工具
    run_limit=40,
    exit_behavior="continue",
)
tool_call_limiter_search = ToolCallLimitMiddleware(
    tool_name="internet_search",
    run_limit=25,
    exit_behavior="continue",
)

# 方案四：Token 消耗监控
#   按会话累计 (thread) 上限 500,000 token，超限后优雅退出（注入 AIMessage 并 jump_to end）
#   每次提问 (run) 不单独限制（max_run_tokens=None），仅作为辅助参考展示在前端
token_monitor = TokenMonitorMiddleware(
    max_run_tokens=None,       # 不限制每次提问
    max_thread_tokens=500_000, # 按会话累计限制
    exit_behavior="end",
)

# 方案五：工具返回去重检测
#   相同参数调用同一工具 >=3 次时阻断
dedup = DeduplicationMiddleware(
    max_identical_calls=3,
    dedup_window=20,
)





subagents_list = [
    knowledge_base_agent,
    database_query_agent,
    net_work_search
]

main_agent=create_deep_agent(
    model=model,
    subagents=subagents_list,
    tools=[generate_markdown,convert_md_to_pdf,read_file_content],
    system_prompt=main_agent_content["system_prompt"],
    middleware=[
        tool_call_limiter_all,
        tool_call_limiter_search,
        token_monitor,
        dedup,
    ],

)


#执行
project_root_dir=Path(__file__).parents[1].resolve()

async def run_main_agent(task_query,session_id):
    """
    定义流式+异步执行主智能体
    执行过程中，返回 会话文件化返回 调用子智能体 调用最终结果 （monitor）
    :param task_query:  用户问题
    :param session_id:  每个前端会话对应的标识，会话id，（1，存储session_id到contextvars 2。session_id 给他创建对应的output输出地址）
    :return:
    """
    updated_info_prompt = ""

    print(f"当前会话的main_agent开始执行，会话id：{session_id}")
    #创建当前会话存储生成文件的专属文件夹
    session_dir=project_root_dir/"output"/f"session_{session_id}"
    session_dir.mkdir(parents=True,exist_ok=True)

    session_dir_str=str(session_dir).replace("\\","/")

    #获取相对文件夹，这个是给模型看的

    relative_session_dir_str=str(session_dir.relative_to(project_root_dir)).replace("\\","/")

    #updated文件存储会话的上传的文件
    update_dir=project_root_dir/"updated"/f"session_{session_id}"
    update_dir.mkdir(parents=True,exist_ok=True)

    #如果文件夹中存在上传的文件，将update中的文件复制到output文件夹中，方便前端统一读取session_dir
    files=[f.name for f in update_dir.iterdir() if f.is_file()]

    if files:
        for file in files:
            shutil.copy2(update_dir/file,session_dir/file)
        #构建提示词，告诉模型有上传文件，要读取上传文件

        updated_info_prompt=(f"\n    [已上传文件] 已加载到工作目录:\n" +
                             "\n".join([f"    - {f}" for f in files]) +
                             "\n    请优先使用工具(read_file_content)读取并参考这些文件。")


    #1将session_dir和id存储到contextvar中，后续工具获取，通过socket推送消息，2。调用monitor给前端推送session_dir信息
    session_dir_token=set_session_context(session_dir_str)#后面会释放掉
    session_id_token=set_thread_context(session_id)

    #当前会话对应的文件夹地址推送给前端,这样前端就有了这个地址，后面前端想要地址中的上传的文件时就可以再返回来
    monitor.report_session_dir(session_dir_str)




    #执行

    config={
        "recursion_limit": 80,  # 限制最大图节点执行步数，防止死循环（LangGraph 层硬兜底）
        "configurable":{
            "thread_id":session_id
        }
    }

    #构建提示词
    path_instruction=f"""
    【工作环境指令】
    工作目录: {relative_session_dir_str}
    {updated_info_prompt}

    规则：
    1. 新生成文件必须保存到工作目录：'{relative_session_dir_str}/filename'
    2. 使用相对路径，禁止使用绝对路径
    3. 若存在上传文件，请先分析内容
    """

    try:
        async for chunk in main_agent.astream({
            "messages":[
                {"role":"user","content":task_query+path_instruction
                       }
            ]
        },config=config):
            for node_name,state in chunk.items():
                if not state or "messages" not in state:
                    continue
                messages=state["messages"]
                if messages and isinstance(messages,list):
                    last_msg=messages[-1]
                    if node_name=='model':
                        if last_msg.tool_calls:
                            for tool_call in last_msg.tool_calls:
                                if tool_call["name"]=="task":
                                    monitor.report_assistant(tool_call["args"]["subagent_type"],{"description":tool_call["args"]["description"]})


                        elif last_msg.content:
                            print(f"主智能体执行结果，最终结果：{last_msg.content[:100]}")
                            monitor.report_task_result(last_msg.content)




    except Exception as e:
        monitor._emit("error",f"执行主智能体发生异常信息：{str(e)}")

    finally:
        reset_session_context(session_dir_token,session_id_token)



























