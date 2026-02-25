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
        analyze_chief_justice_synthesis,
        analyze_graph_structure,
        analyze_safe_tool_engineering,
        analyze_state_management,
        analyze_structured_output,
        clone_repo_sandboxed,
        extract_git_history,
        list_repo_files,
    )

    evidences: list[Evidence] = []
    repo_path: str | None = None
    cleanup_path = None

    try:
        repo_path, cleanup_path = clone_repo_sandboxed(repo_url)
    except CloneError as e:
        err_msg = str(e)
        evidences.append(
            Evidence(
                goal="repo clone",
                found=False,
                content=None,
                location=repo_url,
                rationale=err_msg,
                confidence=1.0,
            )
        )
        # So judges see git_forensic_analysis as failed (clone failed), not missing evidence.
        evidences.append(
            Evidence(
                goal="git_forensic_analysis",
                found=False,
                content="Repository clone failed; no commit history available.",
                location=repo_url,
                rationale=err_msg,
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
            # Rich content for git_forensic_analysis: rubric expects "more than 3 commits" and progression.
            lines = [
                f"COMMIT_COUNT: {gh.total} (rubric pass requires more than 3 commits with progression).",
                "List of all commits (hash, date, message):",
            ]
            for i, c in enumerate(gh.commits, 1):
                lines.append(f"  {i}. [{c.timestamp}] {c.hash_short}: {c.message}")
            content = "\n".join(lines)
            evidences.append(
                Evidence(
                    goal="git_forensic_analysis",
                    found=gh.total > 0,
                    content=content,
                    location=gh.path,
                    rationale=f"Full clone; git log found {gh.total} commit(s). Pass requires >3. Details in content above.",
                    confidence=0.9 if gh.total > 3 else 0.75,
                )
            )
        except GitHistoryError as e:
            evidences.append(
                Evidence(goal="git_forensic_analysis", found=False, content=None, location=repo_path, rationale=str(e), confidence=1.0)
            )
        # Repo file list for Report Accuracy cross-reference (doc_detective)
        try:
            repo_files = list_repo_files(repo_path)
            evidences.append(
                Evidence(
                    goal="repo_file_list",
                    found=len(repo_files) > 0,
                    content="\n".join(repo_files),
                    location=repo_path,
                    rationale=f"Relative paths in repo for path verification ({len(repo_files)} files).",
                    confidence=0.95,
                )
            )
        except Exception:
            pass
        # State management rigor (state.py: TypedDict, BaseModel, Annotated, operator.add/ior)
        try:
            found_sm, snippet_sm = analyze_state_management(repo_path)
            evidences.append(
                Evidence(
                    goal="state_management_rigor",
                    found=found_sm,
                    content=snippet_sm,
                    location=repo_path,
                    rationale="AST/source scan for TypedDict, BaseModel, Annotated reducers.",
                    confidence=0.9 if found_sm else 0.5,
                )
            )
        except Exception:
            pass
        # Safe tool engineering (tools: tempfile, subprocess, no os.system)
        try:
            found_st, snippet_st = analyze_safe_tool_engineering(repo_path)
            evidences.append(
                Evidence(
                    goal="safe_tool_engineering",
                    found=found_st,
                    content=snippet_st,
                    location=repo_path,
                    rationale="Scan src/tools for tempfile, subprocess.run, absence of os.system.",
                    confidence=0.9 if found_st else 0.5,
                )
            )
        except Exception:
            pass
        # Structured output (judges.py: with_structured_output(JudicialOpinion), retry)
        try:
            found_so, snippet_so = analyze_structured_output(repo_path)
            evidences.append(
                Evidence(
                    goal="structured_output_enforcement",
                    found=found_so,
                    content=snippet_so,
                    location=repo_path,
                    rationale="Scan src/nodes/judges.py for .with_structured_output and retry logic.",
                    confidence=0.9 if found_so else 0.5,
                )
            )
        except Exception:
            pass
        # Chief Justice synthesis (justice.py: deterministic rules, Markdown output)
        try:
            found_cj, snippet_cj = analyze_chief_justice_synthesis(repo_path)
            evidences.append(
                Evidence(
                    goal="chief_justice_synthesis",
                    found=found_cj,
                    content=snippet_cj,
                    location=repo_path,
                    rationale="Scan src/nodes/justice.py for security_override, fact_supremacy, functionality_weight.",
                    confidence=0.9 if found_cj else 0.5,
                )
            )
        except Exception:
            pass
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
    repo_paths: list[str] = []
    for e in (state.get("evidences") or {}).get("repo", []):
        goal = e.get("goal") if isinstance(e, dict) else getattr(e, "goal", None)
        content = e.get("content") if isinstance(e, dict) else getattr(e, "content", None)
        if goal == "repo_file_list" and content:
            repo_paths = [p.strip() for p in content.splitlines() if p.strip()]
            break
    path_result = extract_and_verify_paths(context, repo_paths)
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
