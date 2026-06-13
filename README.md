# Deep Search Pro

基于多智能体协作的深度搜索系统，集成网络搜索、企业内部数据库查询和知识库检索三大信息源，支持实时进度监控、人工审批（HITL）和文档自动生成。

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                     Vue 3 前端 (ui/)                      │
│                 WebSocket ↔ REST API                     │
├─────────────────────────────────────────────────────────┤
│                  FastAPI 服务层 (api/)                    │
│   ├── REST: /api/task  /api/upload  /api/download       │
│   ├── WebSocket: /ws/{thread_id} (实时通信)              │
│   ├── Monitor: 工具调用/进度推送                          │
│   └── HITL: SQL写操作审批流                               │
├─────────────────────────────────────────────────────────┤
│                  主智能体 (agent/)                        │
│   ┌─────────────────────────────────────────────────┐   │
│   │           Main Agent (DeepAgents)                │   │
│   │   协调子智能体 + 文档生成工具                      │   │
│   └────────┬────────────┬──────────────┬────────────┘   │
│            │            │              │                 │
│   ┌────────▼───┐ ┌──────▼──────┐ ┌────▼──────────┐     │
│   │ 网络搜索助手 │ │ 数据库查询助手│ │ RAGFlow助手   │     │
│   │  (Tavily)   │ │   (MySQL)   │ │ (企业内部知识库)│     │
│   └─────────────┘ └─────────────┘ └───────────────┘     │
├─────────────────────────────────────────────────────────┤
│                    工具层 (tools/)                       │
│   ├── tavily_tool     网络搜索                          │
│   ├── db_tools        数据库查询/写入 (含HITL审批)       │
│   ├── ragflow_tools   RAGFlow知识库问答                  │
│   ├── markdown_tools  Markdown文档生成                   │
│   ├── pdf_tools       Markdown → PDF 转换               │
│   └── upload_file_read_tool  上传文件读取               │
└─────────────────────────────────────────────────────────┘
```

## 功能特性

- **多智能体协作**：主智能体负责协调调度，根据任务类型自动分发到三个专业子智能体
  - 🌐 **网络搜索助手**：通过 Tavily API 检索互联网公开信息，支持多角度、由浅入深的搜索策略
  - 🗄️ **数据库查询助手**：连接 MySQL 数据库，自动探查表结构、预览数据、执行自定义 SQL
  - 📚 **RAGFlow 助手**：对接企业内部 RAGFlow 知识库，检索私域知识

- **实时进度监控**：基于 WebSocket 的双向通信，前端可实时查看工具调用、子智能体执行进度和最终结果

- **HITL 人工审批**：SQL 写操作（INSERT/UPDATE/DELETE/DROP/ALTER）需前端用户审批后才能执行，支持通过/拒绝/修改三种操作，120 秒超时自动拒绝

- **文档自动生成**：支持 Markdown 和 PDF 两种格式的文档生成，PDF 通过 Word 引擎转换，保证排版质量

- **会话隔离**：每个会话拥有独立的工作目录（`output/session_{id}`）和上传目录（`updated/session_{id}`），支持文件上传后在任务中引用

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TypeScript + Vite + Axios |
| 后端 | FastAPI + Uvicorn + WebSocket |
| AI 框架 | LangChain + LangGraph + DeepAgents |
| LLM | DeepSeek (兼容 OpenAI 协议) |
| 搜索引擎 | Tavily Search API |
| 知识库 | RAGFlow SDK |
| 数据库 | MySQL (mysql-connector-python) |
| 文档生成 | Markdown → WeasyPrint/Word (PDF) |

## 项目结构

```
deep_search_pro/
├── agent/                       # 智能体核心
│   ├── main_agent.py            # 主智能体入口（创建、执行、流式输出）
│   ├── llm.py                   # LLM 模型初始化
│   ├── prompts.py               # Prompt 加载（从 YAML 读取）
│   └── subagents/               # 子智能体定义
│       ├── net_work_agent.py    # 网络搜索子智能体
│       ├── database_query.py    # 数据库查询子智能体
│       └── knowledge_base_agent.py  # RAGFlow 知识库子智能体
├── api/                         # 后端 API 层
│   ├── server.py                # FastAPI 应用（REST + WebSocket）
│   ├── monitor.py               # 实时监控推送（单例 + WebSocket管理器）
│   ├── approval.py              # HITL 审批注册表（Future 机制）
│   └── context.py               # ContextVar 上下文管理
├── tools/                       # 工具层
│   ├── tavily_tool.py           # Tavily 网络搜索工具
│   ├── db_tools.py              # MySQL 数据库工具（含审批）
│   ├── ragflow_tools.py         # RAGFlow 知识库工具
│   ├── markdown_tools.py        # Markdown 生成工具
│   ├── pdf_tools.py             # MD → PDF 转换工具
│   └── upload_file_read_tool.py # 上传文件读取工具
├── prompt/
│   └── prompts.yml              # 主/子智能体 Prompt 配置
├── ragflow/
│   └── ragflow_config.py        # RAGFlow 配置加载
├── utils/
│   ├── path_utils.py            # 路径安全解析
│   ├── sql_parser.py            # SQL 语句解析（识别写操作）
│   └── word_converter.py        # MD → Word → PDF 引擎
├── ui/                          # Vue 3 前端项目
│   ├── src/                     # 前端源码
│   ├── index.html
│   └── package.json
├── output/                      # 会话输出目录（运行时生成）
├── updated/                     # 会话上传目录（运行时生成）
├── .env.example                 # 环境变量模板
└── requirements.txt             # Python 依赖
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+
- MySQL 数据库（可选，用于数据库查询功能）
- RAGFlow 服务（可选，用于知识库检索功能）

### 2. 安装依赖

```bash
# Python 后端依赖
pip install -r requirements.txt

# 前端依赖
cd ui && npm install
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写必要的配置：

```env
# LLM 配置（必填）
OPENAI_API_KEY=your-deepseek-api-key
OPENAI_BASE_URL=https://api.deepseek.com
LLM_SK=deepseek-v4-flash

# Tavily 网络搜索（必填）
TAVILY_API_KEY=your-tavily-api-key

# RAGFlow 知识库（可选）
RAGFLOW_API_URL=http://your-ragflow-server
RAGFLOW_API_KEY=your-ragflow-api-key

# MySQL 数据库（可选）
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=your_database
MYSQL_HOST=localhost
MYSQL_PORT=3306
```

### 4. 启动服务

```bash
# 启动后端 API 服务（端口 8000）
python -m api.server

# 启动前端开发服务器
cd ui && npm run dev
```

### 5. 使用

1. 打开前端页面（默认 `http://localhost:5173`）
2. 输入任务描述，例如：
   - "帮我搜索最近关于AI大模型的新闻，整理成Markdown文档"
   - "查询数据库中上个月的销售数据，分析趋势并生成PDF报告"
   - "搜索知识库中关于空调安装的规范，结合网络搜索的最佳实践，生成一份安装指南"
3. 可选择上传参考文件
4. 提交任务后，通过实时进度面板查看执行状态
5. 如果触发 SQL 写操作，需在审批弹窗中确认
6. 任务完成后，可在文件列表中下载生成的文档

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/task` | 提交任务，返回 `thread_id` |
| POST | `/api/upload` | 上传文件（关联 `thread_id`） |
| GET | `/api/download?path=` | 下载生成的文件 |
| GET | `/api/files?path=` | 列出会话目录下的文件 |
| WS | `/ws/{thread_id}` | WebSocket 实时通信 |
| POST | `/api/approval/respond` | 审批响应（HTTP 降级备用） |

### WebSocket 消息类型

| 类型 | 方向 | 说明 |
|------|------|------|
| `ping` / `pong` | 双向 | 心跳保活 |
| `session_created` | 服务端→客户端 | 工作目录已创建 |
| `tool_start` | 服务端→客户端 | 工具开始执行 |
| `assistant_call` | 服务端→客户端 | 子智能体调用进度 |
| `task_result` | 服务端→客户端 | 任务执行完成 |
| `approval_required` | 服务端→客户端 | 需要人工审批 |
| `approval_response` | 客户端→服务端 | 提交审批结果 |
| `error` | 服务端→客户端 | 异常信息 |

## HITL 审批机制

系统对 SQL 写操作（INSERT、UPDATE、DELETE、DROP、ALTER）实施人工审批：

```
工具调用 → 检测写操作 → 创建审批请求(Future)
    → WebSocket 推送前端 → 用户审批
    → Future.set_result() → 协程恢复 → 执行/拒绝
```

- **超时**：120 秒未审批自动拒绝
- **断连**：客户端断开时自动拒绝该会话所有待审批项
- **修改**：用户可修改 SQL 语句后批准执行

