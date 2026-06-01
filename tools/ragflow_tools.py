import os
from dotenv import load_dotenv
from api.monitor import monitor
from ragflow.ragflow_config import _load_ragflow_env
from typing import Annotated, List
from langchain_core.tools import tool
from ragflow_sdk import RAGFlow

load_dotenv()
api_key,base_url = _load_ragflow_env()

ragflow_client=RAGFlow(api_key=api_key,base_url=base_url)

@tool
def get_assisant_list()->str:
    """
        【工具功能】获取 RAGFlow 中所有聊天助手信息
        适用场景：Agent 需要确认当前有哪些可用助手，及每个助手绑定的知识库范围时调用
        返回：结构化字符串（助手名称+功能介绍+关联知识库）
    """
    monitor.report_tool(tool_name="ragflow助手列表查询工具：get_assisant_list")
    try:
        chat_list=ragflow_client.list_chats()
        if len(chat_list)==0:
            return f"没有可用助手"
        count_chat_info=''
        for chat in chat_list:
            datasets_name=[]

            dataset_list=chat.datasets
            if dataset_list and isinstance(dataset_list,list):
                for dataset in dataset_list:
                    datasets_name.append(dataset['name'])

            count_chat_info+=f"助手名称：{chat.name},助手描述：{chat.description},关联知识库：{','.join(datasets_name)}\n"
        return count_chat_info
    except Exception as e:
        return f"出现错误，错误：{str(e)}"



@tool
def create_ask_delete(chat_name,question)->str:
    """
        【工具功能】向指定 RAGFlow 助手发起单次提问（临时会话，用完即删）
        适用场景：Agent 需单次查询某个助手，无需保留会话记录时调用
        特点：创建临时会话→流式接收答案→自动删除会话，无数据残留
    """
    monitor.report_tool(tool_name="ragflow提问助手列表查询工具：create_ask_delete")
    try:
        chats=ragflow_client.list_chats(name=chat_name)
        if len(chats)==0:
            return f"无可用查询助手"
        use_chat=chats[0]

        session=use_chat.create_session(name="temp_session_ask")

        response=session.ask(question=question,stream=True)
        result=''
        for chunk in response:

            result=chunk.content

        use_chat.delete_sessions(ids=[session.id])

        return result
    except Exception as e:
        return f"出现错误，错误：{str(e)}"





if __name__=="__main__":
    print(create_ask_delete(chat_name="小马",question="空调安装的大概步骤"))


















