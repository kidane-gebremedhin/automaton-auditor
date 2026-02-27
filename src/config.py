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


# ---------------------------------------------------------------------------
# LLM factory: swap providers via LLM_PROVIDER env var
# ---------------------------------------------------------------------------

# Provider → (package, class, model, api-key env var[, base_url])
_PROVIDERS: dict[str, tuple[str, ...]] = {
    "openai": ("langchain_openai", "ChatOpenAI", "gpt-4o", "OPENAI_API_KEY"),
    "gemini": (
        "langchain_google_genai",
        "ChatGoogleGenerativeAI",
        "gemini-2.0-flash",
        "GOOGLE_API_KEY",
    ),
    "deepseek": (
        "langchain_openai",
        "ChatOpenAI",
        "deepseek-chat",
        "DEEPSEEK_API_KEY",
        "https://api.deepseek.com",
    ),
}


def get_llm(*, temperature: float = 0.2):
    """Return the chat-model selected by ``LLM_PROVIDER`` env var.

    Supported values: ``openai`` (default), ``gemini``, ``deepseek``.
    Raises ``RuntimeError`` if the required API key is not set.
    """
    import importlib

    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    if provider not in _PROVIDERS:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={provider!r}. "
            f"Supported: {', '.join(_PROVIDERS)}"
        )

    entry = _PROVIDERS[provider]
    pkg, cls_name, model, key_env = entry[:4]
    base_url = entry[4] if len(entry) > 4 else None

    if not os.getenv(key_env):
        raise RuntimeError(
            f"LLM_PROVIDER={provider} but {key_env} is not set. "
            f"Add it to your .env file."
        )

    module = importlib.import_module(pkg)
    chat_cls = getattr(module, cls_name)

    kwargs: dict = {"model": model, "temperature": temperature}
    if base_url:
        kwargs["base_url"] = base_url
        kwargs["api_key"] = os.getenv(key_env)
    return chat_cls(**kwargs)


# Providers that don't support json_schema response_format
_JSON_MODE_PROVIDERS = {"deepseek"}


def get_structured_output_method() -> str | None:
    """Return the ``method`` kwarg for ``.with_structured_output()``.

    DeepSeek rejects ``response_format: json_schema`` but works with
    ``json_mode``. Returns ``None`` for providers that work with the default.
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower().strip()
    if provider in _JSON_MODE_PROVIDERS:
        return "json_mode"
    return None
