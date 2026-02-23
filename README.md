# Automaton Auditor – Digital Courtroom

Production-grade LangGraph-based audit system that evaluates a GitHub repo + PDF report against a machine-readable rubric ("Constitution").

## Inputs

- **GitHub repo URL** – Cloned and analyzed
- **PDF report** – Parsed with docling

## Pipeline

1. **Detectives** (parallel): RepoInvestigator, DocAnalyst, VisionInspector → Evidence
2. **Judges** (parallel): Prosecutor, Defense, Tech Lead → JudicialOpinion
3. **Chief Justice** – Deterministic synthesis → final verdicts
4. **Report** – Markdown with Executive Summary, Criterion Breakdown, Remediation Plan

## Setup

```bash
uv sync
```

## Config

Create `.env` with:

- `OPENAI_API_KEY` – for LLM calls
- `LANGSMITH_API_KEY` (optional) – for tracing

## Usage

```bash
# TODO: CLI to be added
# uv run python -m src.main --repo <url> --pdf <path>
```
