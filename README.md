# automaton-auditor

Production-grade Python scaffold for an AI multi-agent audit system.

## Setup

1. **Install uv** (if needed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Create and sync the environment**:
   ```bash
   uv sync
   ```

3. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env and set OPENAI_API_KEY (or ANTHROPIC_API_KEY)
   ```

4. **Run the audit CLI** (from project root):
   ```bash
   uv run python -m auditor --repo https://github.com/user/repo --pdf path/to/report.pdf
   ```
   Optional **self-audit mode** (saves report only to `audit/report_onself_generated/`):
   ```bash
   uv run python -m auditor --repo <url> --pdf <path> --self-audit
   ```
   The CLI runs the full swarm (Detectives → EvidenceAggregator → Judges → Chief Justice → Report), saves the Markdown report, and logs a LangSmith trace when `LANGCHAIN_TRACING_V2=true` is set in `.env`.

## Layout

- `src/` — core state, graph, nodes, tools
- `rubric/` — audit rubric / constitution
- `audit/` — audit inputs (e.g. repos, PDFs)
- `reports/` — generated reports

## LangSmith tracing

Tracing is off by default. To enable:

1. Copy `.env.example` to `.env` and set:
   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY=<your-key>   # from https://smith.langchain.com
   LANGCHAIN_PROJECT=automaton-auditor
   ```
2. Call the shared config before running the graph so `.env` is loaded and tracing is applied:
   ```python
   from src.config import configure_tracing
   configure_tracing()
   # then build/run your graph
   ```
   Or ensure your entrypoint imports `src.config` (or calls `configure_tracing()`) so the config runs at startup.

No API keys are hardcoded; all values are read from the environment.

## Dependencies

Managed by uv: langchain, langgraph, pydantic, python-dotenv, openai, docling. Python `ast` is used for code analysis (stdlib; no extra package).
