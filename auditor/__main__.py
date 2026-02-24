"""CLI entrypoint: python -m auditor --repo <url> --pdf <path> [--self-audit].

Runs full swarm, saves report, logs LangSmith trace when configured.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Project root on path so "src" resolves when running from any cwd
_project_root = Path(__file__).resolve().parent.parent
if _project_root not in sys.path:
    sys.path.insert(0, str(_project_root))

# Ensure config (and LangSmith tracing) is loaded before graph
import src.config  # noqa: F401

from src.graph import create_compiled_graph
from src.state import AgentState


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Automaton Auditor: run full audit swarm (Detectives → Judges → Chief Justice → Report).",
    )
    p.add_argument("--repo", type=str, help="GitHub repo URL to audit")
    p.add_argument("--pdf", type=str, help="Path to PDF report")
    p.add_argument(
        "--self-audit",
        action="store_true",
        help="Self-audit mode: save report only to audit/report_onself_generated",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.repo and not args.pdf:
        print("Provide at least one of --repo or --pdf.", file=sys.stderr)
        return 1

    initial_state: AgentState = {
        "repo_url": args.repo or "",
        "pdf_path": args.pdf or "",
        "self_audit": args.self_audit,
    }

    graph = create_compiled_graph()
    final_state = graph.invoke(initial_state)

    report = final_state.get("final_report")
    if report:
        print("Audit complete. Report saved to audit/report_onself_generated/", end="")
        if not args.self_audit:
            print(" and audit/report_onpeer_generated/")
        else:
            print(" (self-audit mode)")
    else:
        print("Audit finished; no report in state.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
