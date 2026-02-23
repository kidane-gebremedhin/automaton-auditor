"""DocAnalyst: parse and analyze PDF reports with docling.

Extracts evidence for theoretical depth and claimed file paths (for cross-check with RepoInvestigator).
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.state import Evidence

if TYPE_CHECKING:
    from src.state import AgentState

logger = logging.getLogger(__name__)

# Terms for theoretical depth – must be explained, not just mentioned
THEORETICAL_TERMS = [
    "Dialectical Synthesis",
    "Fan-In / Fan-Out",
    "Fan-In",
    "Fan-Out",
    "Metacognition",
    "State Synchronization",
]

# Pattern for file paths: src/..., lib/..., tests/..., etc.
FILE_PATH_PATTERN = re.compile(
    r"\b(?:src|lib|tests?|app|backend|frontend)/[\w./\-]+\.[a-zA-Z]{2,4}\b"
    r"|\b[\w\-]+/[\w./\-]+\.[a-zA-Z]{2,4}\b"
)


@dataclass
class DocContext:
    """Internal representation of ingested PDF."""

    markdown: str
    raw: Any  # docling ConversionResult for extensibility


def ingest_pdf(path: str) -> DocContext:
    """Parse PDF with docling and return internal representation.

    Args:
        path: Path to PDF file.

    Returns:
        DocContext with markdown text and raw docling result.

    Raises:
        FileNotFoundError: If path does not exist.
        RuntimeError: If docling conversion fails.
    """
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(str(path))
    markdown = result.document.export_to_markdown()
    return DocContext(markdown=markdown, raw=result)


def query_pdf(context: DocContext, query: str) -> str:
    """Search for query in PDF content and return matching excerpts.

    Uses simple substring/line-based search. For more complex queries,
    consider LLM-based retrieval.

    Args:
        context: Ingested PDF context.
        query: Search string (case-insensitive).

    Returns:
        Concatenated excerpts (up to ~2000 chars) where query appears.
    """
    query_lower = query.lower()
    lines = context.markdown.splitlines()
    excerpts: list[str] = []
    total_len = 0
    max_len = 2000

    for i, line in enumerate(lines):
        if query_lower in line.lower():
            # Include surrounding context (±2 lines)
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            block = "\n".join(lines[start:end])
            if total_len + len(block) < max_len:
                excerpts.append(block)
                total_len += len(block)
            else:
                break

    return "\n\n---\n\n".join(excerpts) if excerpts else ""


def _extract_sentences_with_term(text: str, term: str) -> list[str]:
    """Find sentences that contain term and return those sentences."""
    sentences: list[str] = []
    # Simple sentence split (period, newline, etc.)
    for para in text.split("\n\n"):
        for sent in re.split(r"(?<=[.!?])\s+", para):
            if term.lower() in sent.lower():
                sentences.append(sent.strip())
    return sentences


def _classify_explanation_vs_buzzword(sentences: list[str], term: str) -> tuple[bool, str]:
    """Heuristic: real explanation vs buzzword mention.

    Real explanation: sentence has >15 words, uses 'means', 'refers to', 'is when', etc.
    Buzzword: short mention, no definition.
    """
    if not sentences:
        return False, "no mentions"

    explained = False
    for s in sentences:
        if len(s.split()) > 15 or any(
            kw in s.lower()
            for kw in ("means", "refers to", "is when", "describes", "involves", "allows")
        ):
            explained = True
            break

    rationale = (
        "sentence explains term"
        if explained
        else "only buzzword mention, no substantive explanation"
    )
    return explained, rationale


def extract_theoretical_depth_evidence(text: str, source_path: str) -> list[Evidence]:
    """Extract Evidence for Theoretical Depth criterion.

    Searches for Dialectical Synthesis, Fan-In/Fan-Out, Metacognition, State Synchronization.
    Captures sentences where terms are explained vs merely mentioned.
    """
    evidences: list[Evidence] = []
    terms_found: set[str] = set()

    for term in THEORETICAL_TERMS:
        sentences = _extract_sentences_with_term(text, term)
        if not sentences:
            continue

        terms_found.add(term)
        explained, rationale = _classify_explanation_vs_buzzword(sentences, term)
        excerpt = sentences[0][:500] if sentences else ""

        evidences.append(
            Evidence(
                goal="theoretical depth",
                found=True,
                content=excerpt,
                location=source_path,
                rationale=f"{term}: {rationale}",
                confidence=0.9 if explained else 0.4,
            )
        )

    if not evidences:
        evidences.append(
            Evidence(
                goal="theoretical depth",
                found=False,
                content=None,
                location=source_path,
                rationale="none of [Dialectical Synthesis, Fan-In/Fan-Out, Metacognition, State Synchronization] found",
                confidence=1.0,
            )
        )

    return evidences


def extract_file_paths_evidence(text: str, source_path: str) -> list[Evidence]:
    """Extract claimed file paths from PDF for cross-reference with RepoInvestigator.

    Returns Evidence listing paths mentioned. Integration: cross-check with
    state.evidences.get("repo", []) to flag hallucinated or missing paths.
    """
    # TODO: Cross-check extracted paths with RepoInvestigator evidences
    # (state.evidences["repo"]) to flag hallucinated file references.
    paths = list(dict.fromkeys(FILE_PATH_PATTERN.findall(text)))  # dedupe, preserve order

    if not paths:
        return [
            Evidence(
                goal="host analysis accuracy",
                found=False,
                content=None,
                location=source_path,
                rationale="no file paths (e.g. src/..., tests/...) detected in document",
                confidence=0.8,
            )
        ]

    return [
        Evidence(
            goal="host analysis accuracy",
            found=True,
            content="\n".join(paths[:50]),
            location=source_path,
            rationale=f"extracted {len(paths)} file paths; TODO: cross-check with RepoInvestigator for hallucination",
            confidence=0.7,
        )
    ]


def doc_analyst_main(state: "AgentState") -> dict:
    """Parse PDF and populate state.evidences["docs"].

    Extracts:
    - Theoretical depth (real understanding vs buzzwords)
    - Claimed file paths (candidate hallucination check)
    """
    pdf_path = state.get("pdf_path")
    if not pdf_path:
        return {"evidences": {"docs": []}}

    try:
        context = ingest_pdf(pdf_path)
    except (FileNotFoundError, RuntimeError) as e:
        logger.exception("PDF ingest failed: %s", e)
        return {
            "evidences": {
                "docs": [
                    Evidence(
                        goal="document ingest",
                        found=False,
                        content=None,
                        location=str(pdf_path),
                        rationale=str(e),
                        confidence=1.0,
                    )
                ]
            }
        }

    evidences: list[Evidence] = []
    evidences.extend(extract_theoretical_depth_evidence(context.markdown, str(pdf_path)))
    evidences.extend(extract_file_paths_evidence(context.markdown, str(pdf_path)))

    return {"evidences": {"docs": evidences}}
