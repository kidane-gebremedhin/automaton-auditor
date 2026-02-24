"""Shared config: load .env and configure LangSmith tracing.

No API keys or secrets are hardcoded. All values come from the environment.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of src/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

# LangSmith project name (used when tracing is enabled)
LANGSMITH_PROJECT = "automaton-auditor"


def configure_tracing() -> None:
    """Enable LangSmith tracing from environment.

    Reads .env and sets:
    - LANGCHAIN_TRACING_V2=true when user has enabled tracing
    - LANGCHAIN_PROJECT to the configured project name

    Does not set LANGCHAIN_API_KEY; that must be set in .env if using LangSmith.
    """
    load_dotenv(_ENV_PATH)
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("true", "1", "yes"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.setdefault("LANGCHAIN_PROJECT", LANGSMITH_PROJECT)
