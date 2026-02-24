"""DocAnalyst tools: RAG-lite PDF parsing with Docling.

Supports: Theoretical Depth detection, Report Accuracy cross-reference
(verified vs hallucinated file paths).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel


# -----------------------------------------------------------------------------
# Docling ingest and chunking
# -----------------------------------------------------------------------------

CHUNK_MAX_CHARS = 1200
CHUNK_MIN_CHARS = 100


@dataclass
class DocContext:
    """Ingested PDF: full markdown and chunks for querying."""

    path: str
    markdown: str
    chunks: list[str] = field(default_factory=list)


def _chunk_markdown(markdown: str) -> list[str]:
    """Chunk by paragraphs and section boundaries; merge/split by size."""
    # Split on double newline (paragraphs) or header lines (# ...)
    raw = re.split(r"\n(?=\s*#+\s|\n)", markdown)
    chunks: list[str] = []
    current: list[str] = []

    def flush():
        nonlocal current
        if current:
            text = "\n\n".join(current).strip()
            if len(text) > CHUNK_MAX_CHARS:
                # Split by sentence or mid-paragraph
                while len(text) > CHUNK_MAX_CHARS:
                    head = text[:CHUNK_MAX_CHARS]
                    last_break = max(head.rfind("\n\n"), head.rfind(". "))
                    if last_break > CHUNK_MIN_CHARS:
                        chunks.append(text[: last_break + 1].strip())
                        text = text[last_break + 1 :].lstrip()
                    else:
                        chunks.append(text[:CHUNK_MAX_CHARS])
                        text = text[CHUNK_MAX_CHARS:].lstrip()
            if text:
                chunks.append(text)
            current = []

    for block in raw:
        block = block.strip()
        if not block:
            continue
        current.append(block)
        if sum(len(s) for s in current) >= CHUNK_MAX_CHARS:
            flush()

    flush()
    return chunks


def ingest_pdf(path: str) -> DocContext:
    """Load PDF with Docling and chunk for querying.

    Args:
        path: Path to PDF file.

    Returns:
        DocContext with full markdown and intelligent chunks (paragraph/section).

    Raises:
        FileNotFoundError: If path does not exist.
        RuntimeError: If Docling conversion fails.
    """
    path_obj = Path(path).resolve()
    if not path_obj.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(str(path_obj))
    markdown = result.document.export_to_markdown()
    chunks = _chunk_markdown(markdown)

    return DocContext(path=str(path_obj), markdown=markdown, chunks=chunks)


def query_pdf(context: DocContext, question: str) -> list[str]:
    """Return relevant excerpts only (chunks that match the question).

    Uses simple keyword overlap; for production, use embeddings + similarity.
    """
    question_lower = question.lower()
    words = {w for w in re.split(r"\W+", question_lower) if len(w) > 1}
    if not words:
        return []

    excerpts: list[str] = []
    for chunk in context.chunks:
        chunk_lower = chunk.lower()
        if any(w in chunk_lower for w in words):
            excerpts.append(chunk)
    return excerpts


# -----------------------------------------------------------------------------
# File path extraction and cross-reference (Report Accuracy)
# -----------------------------------------------------------------------------

FILE_PATH_PATTERN = re.compile(
    r"\b(?:src|lib|tests?|app|backend|frontend)/[\w./\-]+\.[a-zA-Z]{2,4}\b"
    r"|\b[\w\-]+/[\w./\-]+\.[a-zA-Z]{2,4}\b"
)


def extract_file_paths(text: str) -> list[str]:
    """Extract file paths mentioned in report (e.g. src/tools/ast_parser.py)."""
    return list(dict.fromkeys(FILE_PATH_PATTERN.findall(text)))


class PathExtractionResult(BaseModel):
    """Structured result: verified vs hallucinated paths for Report Accuracy."""

    mentioned: list[str] = []
    verified: list[str] = []
    hallucinated: list[str] = []


def cross_reference_paths(
    doc_paths: list[str],
    repo_paths: list[str] | set[str],
) -> PathExtractionResult:
    """Classify mentioned paths as verified (in repo) or hallucinated.

    Normalize for comparison: strip leading ./ and use forward slashes.
    """
    repo_set = {
        _normalize_path(p) for p in (repo_paths if isinstance(repo_paths, list) else list(repo_paths))
    }
    mentioned = list(dict.fromkeys(doc_paths))
    verified: list[str] = []
    hallucinated: list[str] = []

    for p in mentioned:
        norm = _normalize_path(p)
        if norm in repo_set:
            verified.append(p)
        else:
            # Partial match: e.g. doc "src/state.py" vs repo "state.py"
            match = any(
                norm == r or norm.endswith("/" + r) or r.endswith("/" + norm)
                for r in repo_set
            )
            if match:
                verified.append(p)
            else:
                hallucinated.append(p)

    return PathExtractionResult(mentioned=mentioned, verified=verified, hallucinated=hallucinated)


def _normalize_path(p: str) -> str:
    return p.replace("\\", "/").strip().lstrip("./")


# -----------------------------------------------------------------------------
# Theoretical Depth detection
# -----------------------------------------------------------------------------

THEORETICAL_TERMS = [
    "Dialectical Synthesis",
    "Fan-In / Fan-Out",
    "Fan-In",
    "Fan-Out",
    "Metacognition",
    "State Synchronization",
]


class TheoreticalDepthResult(BaseModel):
    """Structured result for Theoretical Depth: terms found and excerpts."""

    terms_found: list[str] = []
    excerpts: list[str] = []
    is_substantive: bool = False  # True if excerpts explain, not just mention


def detect_theoretical_depth(context: DocContext) -> TheoreticalDepthResult:
    """Detect theoretical depth: search for rubric terms and return excerpts.

    Marks as substantive if excerpts contain explanation cues (e.g. "means",
    "refers to") or are sufficiently long.
    """
    terms_found: list[str] = []
    excerpts: list[str] = []
    explanation_cues = ("means", "refers to", "is when", "describes", "involves", "allows")

    for term in THEORETICAL_TERMS:
        if term.lower() not in context.markdown.lower():
            continue
        terms_found.append(term)
        for chunk in context.chunks:
            if term.lower() in chunk.lower():
                excerpts.append(chunk[:800])
                break

    is_substantive = any(
        cue in " ".join(excerpts).lower() for cue in explanation_cues
    ) or any(len(e.split()) > 30 for e in excerpts)

    return TheoreticalDepthResult(
        terms_found=terms_found,
        excerpts=excerpts,
        is_substantive=is_substantive,
    )


# -----------------------------------------------------------------------------
# One-shot: extract paths from doc and cross-reference (for Report Accuracy)
# -----------------------------------------------------------------------------


def extract_and_verify_paths(
    context: DocContext,
    repo_paths: list[str] | set[str],
) -> PathExtractionResult:
    """Extract file paths from report and classify as verified / hallucinated.

    Use repo_paths from RepoInvestigator (e.g. list of files in repo) for
    Report Accuracy cross-reference.
    """
    mentioned = extract_file_paths(context.markdown)
    return cross_reference_paths(mentioned, repo_paths)
