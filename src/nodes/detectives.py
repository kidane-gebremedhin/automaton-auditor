"""Detective nodes: RepoInvestigator, DocAnalyst, VisionInspector, pdf_preprocess."""

from __future__ import annotations

import shutil
from pathlib import Path

from src.state import AgentState, Evidence


def pdf_preprocess(state: AgentState) -> dict:
    """Convert PDF once with timeout; store result in state for doc and vision detectives.

    Prevents two parallel Docling conversions (which can stall or deadlock on CPU).
    """
    pdf_path = state.get("pdf_path")
    if not pdf_path:
        return {}

    from src.tools.doc_tools import DocContext, convert_pdf_once

    try:
        doc_context, image_paths, cleanup_path = convert_pdf_once(pdf_path)
    except (FileNotFoundError, RuntimeError) as e:
        # Store empty so doc/vision use cache and do not call convert again
        return {
            "pdf_doc_context": {"path": str(pdf_path), "markdown": "", "chunks": []},
            "pdf_image_paths": [],
            "pdf_cleanup_path": "",
        }

    return {
        "pdf_doc_context": {
            "path": doc_context.path,
            "markdown": doc_context.markdown,
            "chunks": doc_context.chunks,
        },
        "pdf_image_paths": image_paths,
        "pdf_cleanup_path": str(cleanup_path) if cleanup_path else "",
    }


def repo_detective(state: AgentState) -> dict:
    """RepoInvestigator: clone repo, analyze graph structure and git history; return evidences["repo"]."""
    repo_url = state.get("repo_url")
    if not repo_url:
        return {"evidences": {"repo": []}}

    import shutil as _shutil

    from src.tools.repo_tools import (
        CloneError,
        GitHistoryError,
        analyze_graph_structure,
        clone_repo_sandboxed,
        extract_git_history,
    )

    evidences: list[Evidence] = []
    repo_path: str | None = None
    cleanup_path = None

    try:
        repo_path, cleanup_path = clone_repo_sandboxed(repo_url)
    except CloneError as e:
        evidences.append(
            Evidence(
                goal="repo clone",
                found=False,
                content=None,
                location=repo_url,
                rationale=str(e),
                confidence=1.0,
            )
        )
        return {"evidences": {"repo": evidences}}

    try:
        gs = analyze_graph_structure(repo_path)
        evidences.append(
            Evidence(
                goal="graph orchestration",
                found=gs.has_state_graph and gs.has_add_edge,
                content=gs.details,
                location=gs.path,
                rationale=f"StateGraph={gs.has_state_graph} fan_out={gs.has_fan_out} parallel_judges={gs.has_parallel_judges}",
                confidence=0.9 if gs.has_state_graph else 0.5,
            )
        )
        try:
            gh = extract_git_history(repo_path)
            evidences.append(
                Evidence(
                    goal="git history",
                    found=gh.total > 0,
                    content=f"{gh.total} commits",
                    location=gh.path,
                    rationale="; ".join(c.message[:80] for c in gh.commits[:5]),
                    confidence=0.8,
                )
            )
        except GitHistoryError as e:
            evidences.append(
                Evidence(goal="git history", found=False, content=None, location=repo_path, rationale=str(e), confidence=1.0)
            )
    finally:
        if cleanup_path is not None and Path(cleanup_path).exists():
            _shutil.rmtree(cleanup_path, ignore_errors=True)

    return {"evidences": {"repo": evidences}}


def doc_detective(state: AgentState) -> dict:
    """DocAnalyst: ingest PDF (or use cached pdf_doc_context), theoretical depth, path extraction."""
    pdf_path = state.get("pdf_path")
    if not pdf_path:
        return {"evidences": {"docs": []}}

    from src.tools.doc_tools import DocContext, detect_theoretical_depth, extract_and_verify_paths, ingest_pdf

    evidences: list[Evidence] = []
    cached = state.get("pdf_doc_context")
    if isinstance(cached, dict) and "markdown" in cached:
        context = DocContext(
            path=cached.get("path", str(pdf_path)),
            markdown=cached.get("markdown", ""),
            chunks=cached.get("chunks", []),
        )
    else:
        try:
            context = ingest_pdf(pdf_path)
        except (FileNotFoundError, RuntimeError) as e:
            evidences.append(
                Evidence(
                    goal="document ingest",
                    found=False,
                    content=None,
                    location=str(pdf_path),
                    rationale=str(e),
                    confidence=1.0,
                )
            )
            return {"evidences": {"docs": evidences}}

    td = detect_theoretical_depth(context)
    evidences.append(
        Evidence(
            goal="theoretical depth",
            found=td.is_substantive or len(td.terms_found) > 0,
            content="; ".join(td.terms_found) if td.terms_found else None,
            location=context.path,
            rationale=f"substantive={td.is_substantive} terms={td.terms_found}",
            confidence=0.85 if td.is_substantive else 0.5,
        )
    )
    path_result = extract_and_verify_paths(context, [])
    evidences.append(
        Evidence(
            goal="report accuracy (paths)",
            found=len(path_result.verified) > 0,
            content=f"mentioned={path_result.mentioned} verified={path_result.verified} hallucinated={path_result.hallucinated}",
            location=context.path,
            rationale=f"verified={len(path_result.verified)} hallucinated={len(path_result.hallucinated)}",
            confidence=0.7,
        )
    )
    return {"evidences": {"docs": evidences}}


def vision_inspector(state: AgentState) -> dict:
    """VisionInspector: use cached pdf_image_paths or extract from PDF; classify diagrams."""
    pdf_path = state.get("pdf_path")
    if not pdf_path:
        return {"evidences": {"vision": []}}

    from src.tools.vision_tools import (
        DIAGRAM_PROMPT,
        classify_diagram_with_vision,
        extract_images_from_pdf,
    )

    evidences: list[Evidence] = []
    image_paths: list[str] = []
    cleanup_path: Path | None = None

    # Use cache from pdf_preprocess when present (avoids second conversion)
    if "pdf_image_paths" in state:
        image_paths = list(state["pdf_image_paths"]) if state["pdf_image_paths"] else []
        cp = state.get("pdf_cleanup_path")
        if cp and Path(cp).exists():
            cleanup_path = Path(cp)
    else:
        try:
            image_paths, cleanup_path = extract_images_from_pdf(pdf_path)
        except FileNotFoundError as e:
            evidences.append(
                Evidence(
                    goal="diagram architecture",
                    found=False,
                    content=None,
                    location=str(pdf_path),
                    rationale=str(e),
                    confidence=1.0,
                )
            )
            return {"evidences": {"vision": evidences}}
        except Exception as e:
            evidences.append(
                Evidence(
                    goal="diagram architecture",
                    found=False,
                    content=None,
                    location=str(pdf_path),
                    rationale=f"image extraction failed: {e}",
                    confidence=1.0,
                )
            )
            return {"evidences": {"vision": evidences}}

    try:
        if not image_paths:
            evidences.append(
                Evidence(
                    goal="diagram architecture",
                    found=False,
                    content=None,
                    location=str(pdf_path),
                    rationale="no images extracted from PDF",
                    confidence=0.9,
                )
            )
            return {"evidences": {"vision": evidences}}

        results = classify_diagram_with_vision(image_paths, prompt=DIAGRAM_PROMPT)
        classifications = [r.classification for r in results]
        best = max(
            set(classifications),
            key=lambda c: (
                2 if c == "StateGraph diagram" else (1 if c == "Linear pipeline" else 0)
            ),
        )
        evidences.append(
            Evidence(
                goal="diagram architecture",
                found=(best == "StateGraph diagram"),
                content=f"Classifications: {classifications}; best: {best}",
                location=str(pdf_path),
                rationale="multimodal answer to: Does this diagram show parallel fan-out/fan-in architecture?",
                confidence=0.85 if results else 0.0,
            )
        )
    finally:
        if cleanup_path is not None and Path(cleanup_path).exists():
            shutil.rmtree(cleanup_path, ignore_errors=True)

    return {"evidences": {"vision": evidences}}
