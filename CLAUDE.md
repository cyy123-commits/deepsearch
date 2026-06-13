# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start Commands

```bash
# Backend — install deps then start API server (port 8000)
pip install -r requirements.txt
python -m api.server

# Frontend — install deps then start dev server (port 5173)
cd ui && npm install && npm run dev

# Run a single Python module for testing
python -m tools.db_tools          # test DB tools directly
python -m tools.ragflow_tools     # test RAGFlow tools
```

## Environment

Copy `.env.example` to `.env` and fill in:
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` — DeepSeek LLM (OpenAI-compatible endpoint)
- `LLM_SK` — model name, e.g. `deepseek-v4-flash`
- `TAVILY_API_KEY` — web search
- `RAGFLOW_API_URL` / `RAGFLOW_API_KEY` — internal knowledge base (optional)
- `MYSQL_*` — database connection (optional)

## Architecture

This is a **multi-agent deep search system** with three layers:

### Agent Layer (`agent/`)

**Main agent** (`main_agent.py`) is the orchestrator, built with `deepagents.create_deep_agent()`. It manages three sub-agents defined as dicts (name, description, system_prompt, tools), plus three top-level tools: `generate_markdown`, `convert_md_to_pdf`, `read_file_content`.

- **LLM** (`llm.py`): Initialized via `langchain.chat_models.init_chat_model` with provider `"openai"`, reading `LLM_SK` from env. The model global is imported by `main_agent.py` at module load.
- **Prompts** (`prompts.py`): Loads `prompt/prompts.yml` via `yaml.safe_load`, returns `main_agent_content` and `sub_agents_content` dicts.
- **Sub-agents** are plain Python dicts (NOT DeepAgents-created agents), keyed by `name`, `description`, `system_prompt`, and `tools`:
  - `net_work_search` — Tavily web search
  - `database_query_agent` — MySQL table exploration + SQL execution
  - `knowledge_base_agent` — RAGFlow assistant queries

**Execution flow** (`run_main_agent`):
1. Creates per-session directories under `output/session_{id}` and `updated/session_{id}`
2. Copies any uploaded files into the output session dir
3. Sets ContextVar tokens for session_dir and thread_id
4. Builds a path-instruction prompt telling the agent where to write files
5. Streams via `main_agent.astream()`, emitting real-time events through `monitor`
6. On `task` tool calls from the model, extracts `subagent_type`/`description` and reports to the frontend

### API Layer (`api/`)

**FastAPI application** (`server.py`) provides:

| Endpoint | Purpose |
|---|---|
| `POST /api/task` | Submit a query, spawns `run_main_agent` via `asyncio.create_task` |
| `POST /api/upload` | Upload files → `updated/session_{id}` |
| `GET /api/download?path=` | Download generated files (path traversal protected) |
| `GET /api/files?path=` | List files in output directory |
| `WS /ws/{thread_id}` | WebSocket for real-time events + HITL approval responses |

**Context isolation** (`context.py`): Uses Python `ContextVar` (NOT `threading.local` and NOT globals) to store `session_dir` and `thread_id` per asyncio task. This prevents cross-request contamination in the single-threaded async event loop. Call `set_session_context` / `set_thread_context` before execution, `reset_session_context` in a `finally` block.

**Monitor** (`monitor.py`): Singleton `ToolMonitor` pushes execution progress to the frontend via WebSocket. It resolves the target `thread_id` from ContextVar to route messages to the correct client. Falls back to `builtins.runtime.stream_writer` for script/CLI mode, and prints to console as last resort. The `ConnectionManager` singleton manages WebSocket connections keyed by `thread_id`.

**HITL Approval** (`approval.py`): Singleton `ApprovalRegistry` implements a Future-based approval pattern:
1. Tool function calls `create_approval()` → creates `asyncio.Future`
2. `monitor.report_approval_required()` → WebSocket push to frontend
3. Tool `await`s `wait_for_approval()` → coroutine suspends
4. Frontend sends `approval_response` via WebSocket → `resolve()` calls `future.set_result()`
5. Coroutine resumes with `{"action": "approve"|"reject"}`

Timeout is 120s; disconnect auto-rejects all pending approvals for that thread.

### Tool Layer (`tools/`)

Each tool is decorated with `@tool` from LangChain and reports progress via `monitor.report_tool()`. Key patterns:

- **db_tools.py**: `excute_sql_query` is the only `async` tool — it parses SQL with `utils/sql_parser.py`, and for write operations (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/REPLACE/RENAME/GRANT/REVOKE) goes through the HITL approval flow before calling the sync `_execute_sql_impl`.
- **markdown_tools.py / pdf_tools.py / upload_file_read_tool.py**: All resolve file paths via `utils/path_utils.resolve_path()` which sanitizes virtual prefixes (`/workspace`, `/mnt/data`, `/home/user`), isolates to the session directory, and prevents path nesting.
- **pdf_tools.py**: Converts MD → HTML → Word → PDF via `win32com.client` (Windows-only, requires Microsoft Word installed). On non-Windows or without Word, this will fail.
- **ragflow_tools.py**: `create_ask_delete` creates a temporary RAGFlow session, streams the answer, then deletes the session — no data retained.
- **tavily_tool.py**: Uses env var `TA_API_KEY` (note: different from `.env.example` which uses `TAVILY_API_KEY`).

### Frontend (`ui/`)

Vue 3 + TypeScript + Vite. All logic lives in a single `App.vue` (~1200 lines) handling:
- WebSocket auto-reconnect
- Message rendering with Markdown (`marked` library)
- File upload (multipart/form-data to `/api/upload`)
- File explorer sidebar (fetches from `/api/files`)
- HITL approval modal overlay (SQL write confirmation)
- Real-time progress logs (tool calls, sub-agent invocation)

The `HelloWorld.vue` component is the Vite scaffold and is **not used** by the app.

### Utility Layer (`utils/`)

- **path_utils.py**: `resolve_path()` — the single path resolution entry point. Cleans AI/container virtual prefixes, handles `updated/` special directory, and enforces session-dir sandboxing with nested-path detection.
- **sql_parser.py**: Regex-based SQL write operation detection. Strips comments (`--` and `/* */`), splits by `;`, matches against write keywords.
- **word_converter.py**: MD → PDF via Word COM. Initializes COM per call (`CoInitialize`/`CoUninitialize`), creates temporary HTML, opens in Word, saves as PDF format 17.

## Key Design Decisions

- **Module-level side effects**: Importing `agent.main_agent` triggers LLM initialization and agent construction (takes a few seconds). The `server.py` import chain is `server → main_agent → llm + prompts + subagents → tools`. Don't add circular imports.
- **Async tool pattern**: Only `excute_sql_query` is async (because it awaits HITL). All other tools are synchronous. DeepAgents/LangChain handles this transparently.
- **Session directory layout**: Each session gets `output/session_{uuid}/` and `updated/session_{uuid}/`. Uploaded files are copied from `updated/` to `output/` at task start so all files are served from one directory.
- **ContextVar lifecycle**: ContextVars are set in `run_main_agent` and cleared in its `finally` block. Tools call `get_session_context()` / `get_thread_context()` anywhere in the call stack without parameter threading.
- **Prompt organization**: All agent prompts live in `prompt/prompts.yml` under `main_agent.system_prompt` and `sub_agents.<key>.system_prompt`. Never hardcode prompts in Python.

## Notes

- PDF generation uses Word COM and only works on Windows with Microsoft Word installed.
- The `TAVILY_API_KEY` env var in `.env.example` differs from the actual key name `TA_API_KEY` used in `tavily_tool.py`. Check which one is correct for your setup.
- There is no test suite — tools are tested by running `if __name__ == "__main__"` blocks directly.
- Loop prevention middleware is in `agent/middleware/` (ToolCallLimit, TokenMonitor, Deduplication). See `docs/loop_prevention_plan.md` for design details.
