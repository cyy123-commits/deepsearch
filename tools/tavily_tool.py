# ======================== 导入核心依赖 ========================
# 类型注解：增强代码提示和静态检查能力
from typing import  Literal
# LangChain 工具装饰器：将普通函数转为 Agent 可调用的工具
from langchain_core.tools import tool
# Tavily 官方客户端：实现网络搜索核心功能
from tavily import TavilyClient

# 系统/第三方依赖
import os  # 系统路径/环境变量处理
from dotenv import load_dotenv  # 加载 .env 文件中的环境变量

# 自定义模块：工具调用埋点监控（需确保 api 模块可导入）
from api.monitor import monitor

# ======================== 初始化配置 ========================
# 加载项目根目录的 .env 文件，读取环境变量（如 TAVILY_API_KEY）
load_dotenv()

#创建tavilyclient
tavily_client = TavilyClient(
    api_key=os.getenv('TA_API_KEY'),
)

#创建网络搜索工具
@tool
def internet_search(
        query: str,
        max_results: int =5,
        topic:Literal["news","finace","general"]="general",
        include_raw_content:bool=False,
):
    """
    根据问题进行网络查询，当需要获取外部互联网的公开信息、最新新闻或特定主题数据时使用此工具
    注意：如果指定查询数据库或者RAG不能使用此工具
    :param query:
    :param max_results:
    :param topic:
    :param include_raw_content:
    :return:
    """

    #在工具中埋点，monitor向前端推送信息，每次调用工具都会推送调用进度
    #参数一是工具名字，参数二是工具参数信息
    monitor.report_tool(tool_name="网络搜索工具",args={"query":query,"max_results":max_results,
                                                       "topic":topic,
                                                       "include_raw_content":include_raw_content})

    return tavily_client.search(query=query,
                                max_results=max_results,
                                topic=topic,
                                include_raw_content=include_raw_content)




