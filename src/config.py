"""Configuration: env loading, LangSmith tracing."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of src/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def ensure_config() -> None:
    """Load env and enable LangSmith tracing if configured."""
    load_dotenv(_ENV_PATH)
    if os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("true", "1", "yes"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"


def get_openai_api_key() -> str | None:
    """Get OpenAI API key from environment."""
    return os.getenv("OPENAI_API_KEY")


def get_langsmith_project() -> str:
    """Get LangSmith project name."""
    return os.getenv("LANGCHAIN_PROJECT", "digital-courtroom")


# Called on import to set up tracing
ensure_config()
