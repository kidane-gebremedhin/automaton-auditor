"""ContextBuilder: load rubric, apply Targeting Protocol, route instructions to Detectives/Judges/ChiefJustice."""

from __future__ import annotations

import json
from pathlib import Path

from src.state import AgentState

# Default path relative to project root
DEFAULT_RUBRIC_PATH = "rubric/week2_rubric.json"

# Targeting Protocol: input key -> detective name (routing)
TARGETING = {
    "github_repo": "RepoInvestigator",
    "pdf_report": "DocAnalyst",
    "pdf_images": "VisionInspector",
}


def load_rubric(path: str | Path) -> dict:
    """Load rubric JSON from path. Raises FileNotFoundError or json.JSONDecodeError."""
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Rubric not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def apply_targeting(state: AgentState, rubric: dict) -> dict:
    """Apply Targeting Protocol: map input keys to state.repo_url / state.pdf_path.

    Protocol: github_repo → RepoInvestigator (state.repo_url)
              pdf_report → DocAnalyst (state.pdf_path)
              pdf_images → VisionInspector (state.pdf_path for images from same PDF)

    Expects state or a separate 'input' dict with keys github_repo, pdf_report, pdf_images.
    """
    out: dict = {}
    # Allow inputs to be passed under "input" or at top level
    inp = state.get("input") or state
    if isinstance(inp.get("github_repo"), str):
        out["repo_url"] = inp["github_repo"]
    if isinstance(inp.get("pdf_report"), str):
        out["pdf_path"] = inp["pdf_report"]
    if isinstance(inp.get("pdf_images"), str):
        out["pdf_path"] = inp["pdf_images"]
    return out


def context_builder(
    state: AgentState,
    rubric_path: str | Path | None = None,
) -> dict:
    """Load rubric and route forensic_instruction → Detectives, judicial_logic → Judges, synthesis_rules → ChiefJustice.

    Targeting Protocol: github_repo → RepoInvestigator, pdf_report → DocAnalyst, pdf_images → VisionInspector.
    Sets state.repo_url / state.pdf_path from input keys when present.
    """
    path = rubric_path or DEFAULT_RUBRIC_PATH
    try:
        rubric = load_rubric(path)
    except (FileNotFoundError, json.JSONDecodeError):
        rubric = {
            "criteria": [],
            "forensic_instruction": "",
            "judicial_logic": "",
            "synthesis_rules": {},
            "targeting": dict(TARGETING),
        }

    criteria = rubric.get("criteria", [])
    forensic_instruction = rubric.get("forensic_instruction", "")
    judicial_logic = rubric.get("judicial_logic", "")
    synthesis_rules = rubric.get("synthesis_rules", {})

    # Apply Targeting Protocol: set repo_url, pdf_path from input
    targeting_updates = apply_targeting(state, rubric)

    return {
        "rubric_dimensions": criteria,
        "forensic_instruction": forensic_instruction,
        "judicial_logic": judicial_logic,
        "synthesis_rules": synthesis_rules,
        **targeting_updates,
    }
