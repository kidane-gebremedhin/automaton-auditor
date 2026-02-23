"""Typed agent state for the Digital Courtroom graph.

Reducer design:
- evidences: merge_evidences (Dict merge with list concatenation on key overlap)
  prevents data loss when parallel detectives write to the same source key.
- opinions: operator.add appends new opinions to the list without overwriting.
"""

import operator
from typing import Annotated, Literal, Optional

from pydantic import BaseModel
from typing_extensions import TypedDict


# -----------------------------------------------------------------------------
# Custom reducer for Dict[str, List[Evidence]]
# operator.ior would overwrite on key conflict; we concatenate lists instead.
# -----------------------------------------------------------------------------


def merge_evidences(
    left: dict[str, list["Evidence"]], right: dict[str, list["Evidence"]]
) -> dict[str, list["Evidence"]]:
    """Merge evidences dicts: concatenate lists for overlapping keys."""
    result = dict(left)
    for key, items in right.items():
        if key in result:
            result[key] = result[key] + items
        else:
            result[key] = items
    return result


# -----------------------------------------------------------------------------
# Evidence & Opinion Models
# -----------------------------------------------------------------------------


class Evidence(BaseModel):
    """Evidence collected by a detective (RepoInvestigator, DocAnalyst, VisionInspector)."""

    goal: str
    found: bool
    content: Optional[str] = None
    location: str
    rationale: str
    confidence: float


class JudicialOpinion(BaseModel):
    """Opinion from a judge (Prosecutor, Defense, Tech Lead)."""

    judge: Literal["Prosecutor", "Defense", "TechLead"]
    criterion_id: str
    score: int
    argument: str
    cited_evidence: list[str]


# -----------------------------------------------------------------------------
# Agent State
# -----------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """State passed through the Digital Courtroom graph.

    Uses Annotated reducers to prevent data loss during parallel execution:
    - evidences: merge_evidences (concatenates lists on key overlap)
    - opinions: operator.add (appends to list)
    """

    # Inputs
    repo_url: str
    pdf_path: str

    # Rubric (loaded by context_builder)
    rubric_dimensions: list[dict]

    # Detective outputs: Dict[source, List[Evidence]]
    evidences: Annotated[dict[str, list[Evidence]], merge_evidences]

    # Judge outputs
    opinions: Annotated[list[JudicialOpinion], operator.add]

    # Final output
    final_report: str
