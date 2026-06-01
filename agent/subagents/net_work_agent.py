#创建网络搜索子智能体

from agent.prompts import sub_agents_content
from tools.tavily_tool import internet_search

net_work_search={
    "name":sub_agents_content["tavily"]["name"],
    "description":sub_agents_content["tavily"]["description"],
    "system_prompt":sub_agents_content["tavily"]["system_prompt"],
    "tools":[internet_search]

}