
from tools.db_tools import get_table_data, get_db_config, list_sql_tables, excute_sql_query

from agent.prompts import sub_agents_content

database_query_agent = {
    "name": sub_agents_content["db"]["name"],
    "description": sub_agents_content["db"]["description"],
    "system_prompt": sub_agents_content["db"]["system_prompt"],
    "tools": [get_table_data, get_db_config, list_sql_tables, excute_sql_query],
}