"""RepoInvestigator: analyze GitHub repo structure and content.

Clones repos into sandboxed temp directories and analyzes state, graph, and git history.
"""

import ast
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from src.state import Evidence

if TYPE_CHECKING:
    from src.state import AgentState

logger = logging.getLogger(__name__)

# GitHub URL pattern (basic validation)
GITHUB_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+(?:\.git)?$"
)

# Expected Evidence fields
EXPECTED_EVIDENCE_FIELDS = {"goal", "found", "content", "location", "rationale", "confidence"}

# Expected JudicialOpinion fields
EXPECTED_JUDICIAL_OPINION_FIELDS = {
    "judge",
    "criterion_id",
    "score",
    "argument",
    "cited_evidence",
}


class RepoInvestigatorError(Exception):
    """Raised when repo investigation fails (clone, parse, etc.)."""

    pass


def clone_repo(repo_url: str) -> str:
    """Clone a GitHub repository into a sandboxed temporary directory.

    Args:
        repo_url: Valid GitHub HTTPS URL (e.g. https://github.com/user/repo).

    Returns:
        Path to the cloned repo root (where .git lives).
        Caller must clean up with shutil.rmtree(Path(path).parent).

    Raises:
        RepoInvestigatorError: If URL is invalid or git clone fails.
    """
    repo_url = repo_url.strip()
    if not GITHUB_URL_PATTERN.match(repo_url):
        raise RepoInvestigatorError(f"Invalid GitHub URL: {repo_url!r}")

    tmp_dir = tempfile.mkdtemp(prefix="repo_investigator_")
    target = Path(tmp_dir)

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", repo_url, str(target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.error("git clone timed out for %s", repo_url)
        raise RepoInvestigatorError("git clone timed out") from None
    except FileNotFoundError:
        logger.error("git not found in PATH")
        raise RepoInvestigatorError("git executable not found") from None

    if result.returncode != 0:
        stderr = result.stderr or result.stdout or "(no output)"
        logger.error("git clone failed: %s", stderr)
        raise RepoInvestigatorError(f"git clone failed: {stderr.strip()}")

    # git clone creates a subdir named after the repo
    subdirs = [d for d in target.iterdir() if d.is_dir()]
    if len(subdirs) != 1:
        raise RepoInvestigatorError("unexpected clone layout (expected single subdir)")

    repo_path = str(subdirs[0].resolve())
    logger.info("Cloned %s to %s", repo_url, repo_path)
    return repo_path


def analyze_state_structure(repo_path: str) -> list[Evidence]:
    """Analyze src/state.py for typed state, Evidence, and JudicialOpinion.

    Parses with ast and checks for:
    - AgentState TypedDict or equivalent
    - Pydantic Evidence and JudicialOpinion models
    - Expected field names

    Returns:
        Evidence list describing existence and correctness of state structures.
    """
    root = Path(repo_path)
    state_file = root / "src" / "state.py"
    if not state_file.exists():
        return [
            Evidence(
                goal="typed state structure",
                found=False,
                content=None,
                location="src/state.py",
                rationale="src/state.py not found",
                confidence=1.0,
            )
        ]

    try:
        source = state_file.read_text(encoding="utf-8")
    except OSError as e:
        return [
            Evidence(
                goal="typed state structure",
                found=False,
                content=None,
                location=str(state_file),
                rationale=f"cannot read file: {e}",
                confidence=1.0,
            )
        ]

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [
            Evidence(
                goal="typed state structure",
                found=False,
                content=None,
                location=str(state_file),
                rationale=f"syntax error: {e}",
                confidence=1.0,
            )
        ]

    evidences: list[Evidence] = []
    classes: dict[str, ast.ClassDef] = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    has_typed_dict = False
    has_evidence = False
    has_judicial_opinion = False
    evidence_fields_ok = False
    judicial_opinion_fields_ok = False

    for name, node in classes.items():
        bases = [ast.unparse(b) if hasattr(ast, "unparse") else _get_base_name(b) for b in node.bases]
        if "TypedDict" in str(bases) or name == "AgentState":
            has_typed_dict = True
        if name == "Evidence":
            has_evidence = True
            evidence_fields_ok = _check_class_fields(node, EXPECTED_EVIDENCE_FIELDS)
        if name == "JudicialOpinion":
            has_judicial_opinion = True
            judicial_opinion_fields_ok = _check_class_fields(node, EXPECTED_JUDICIAL_OPINION_FIELDS)

    evidences.append(
        Evidence(
            goal="typed state structure",
            found=has_typed_dict,
            content=f"AgentState TypedDict: {has_typed_dict}",
            location="src/state.py",
            rationale="AgentState or TypedDict must exist for typed state",
            confidence=1.0 if has_typed_dict else 0.0,
        )
    )
    evidences.append(
        Evidence(
            goal="Evidence model",
            found=has_evidence,
            content=f"Evidence class with expected fields: {evidence_fields_ok}" if has_evidence else None,
            location="src/state.py",
            rationale="Evidence (goal, found, content, location, rationale, confidence)" if has_evidence else "Evidence class not found",
            confidence=1.0 if (has_evidence and evidence_fields_ok) else (0.5 if has_evidence else 0.0),
        )
    )
    evidences.append(
        Evidence(
            goal="JudicialOpinion model",
            found=has_judicial_opinion,
            content=f"JudicialOpinion with expected fields: {judicial_opinion_fields_ok}" if has_judicial_opinion else None,
            location="src/state.py",
            rationale="JudicialOpinion (judge, criterion_id, score, argument, cited_evidence)" if has_judicial_opinion else "JudicialOpinion class not found",
            confidence=1.0 if (has_judicial_opinion and judicial_opinion_fields_ok) else (0.5 if has_judicial_opinion else 0.0),
        )
    )
    return evidences


def _get_base_name(node: ast.AST) -> str:
    """Extract base class name for ast node (Python 3.8 compatible)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return str(node)


def _check_class_fields(node: ast.ClassDef, expected: set[str]) -> bool:
    """Check that class has at least the expected attribute names."""
    found: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            found.add(stmt.target.id)
    return expected.issubset(found)


def analyze_graph_structure(repo_path: str) -> list[Evidence]:
    """Analyze src/graph.py for StateGraph, add_node/add_edge, and fan-out.

    Confirms:
    - StateGraph-like instantiation
    - add_node / add_edge wiring
    - Whether Detectives and Judges use parallel fan-out/fan-in (not purely linear).

    Returns:
        Evidence describing graph orchestration and fan-out presence.
    """
    root = Path(repo_path)
    graph_file = root / "src" / "graph.py"
    if not graph_file.exists():
        return [
            Evidence(
                goal="graph orchestration",
                found=False,
                content=None,
                location="src/graph.py",
                rationale="src/graph.py not found",
                confidence=1.0,
            )
        ]

    try:
        source = graph_file.read_text(encoding="utf-8")
    except OSError as e:
        return [
            Evidence(
                goal="graph orchestration",
                found=False,
                content=None,
                location=str(graph_file),
                rationale=f"cannot read file: {e}",
                confidence=1.0,
            )
        ]

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [
            Evidence(
                goal="graph orchestration",
                found=False,
                content=None,
                location=str(graph_file),
                rationale=f"syntax error: {e}",
                confidence=1.0,
            )
        ]

    has_state_graph = False
    has_add_node = False
    has_add_edge = False
    node_names: set[str] = set()
    edge_count = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _get_call_name(node)
            if name and "StateGraph" in name:
                has_state_graph = True
            if name and "add_node" in name:
                has_add_node = True
                first_arg = node.args[0] if node.args else None
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    node_names.add(first_arg.value)
            if name and "add_edge" in name:
                has_add_edge = True
                edge_count += 1

    # Heuristic: parallel architecture usually has multiple nodes feeding into one,
    # or send_all / fan-out patterns. Detectives/Judges as parallel hubs.
    has_detective_hub = any("detective" in n.lower() for n in node_names)
    has_judge_hub = any("judge" in n.lower() for n in node_names)
    has_fan_out = has_detective_hub and has_judge_hub and edge_count >= 4

    evidences = [
        Evidence(
            goal="StateGraph usage",
            found=has_state_graph,
            content=f"StateGraph instantiated: {has_state_graph}",
            location="src/graph.py",
            rationale="StateGraph or equivalent must be used",
            confidence=1.0 if has_state_graph else 0.0,
        ),
        Evidence(
            goal="graph wiring",
            found=has_add_node and has_add_edge,
            content=f"add_node: {has_add_node}, add_edge: {has_add_edge}, edges: {edge_count}",
            location="src/graph.py",
            rationale="add_node and add_edge must wire the graph",
            confidence=1.0 if (has_add_node and has_add_edge) else 0.0,
        ),
        Evidence(
            goal="parallel fan-out architecture",
            found=has_fan_out,
            content=f"Detectives hub: {has_detective_hub}, Judges hub: {has_judge_hub}, fan-out present: {has_fan_out}",
            location="src/graph.py",
            rationale="Graph should have Detectives and Judges in parallel/fan-out structure",
            confidence=0.9 if has_fan_out else (0.5 if (has_detective_hub or has_judge_hub) else 0.0),
        ),
    ]
    return evidences


def _get_call_name(node: ast.Call) -> str | None:
    """Extract the name of a call (e.g. 'add_node', 'StateGraph')."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def extract_git_history(repo_path: str) -> list[Evidence]:
    """Extract git log and categorize commit history.

    Runs `git log --oneline --reverse` and distinguishes:
    - Healthy history: >3 commits, stepwise evolution
    - Single init / bulk upload: few commits, bulk-style messages

    Returns:
        Evidence with commit messages and timestamps.
    """
    path = Path(repo_path)
    if not (path / ".git").exists():
        return [
            Evidence(
                goal="git history",
                found=False,
                content=None,
                location=str(path),
                rationale="not a git repository",
                confidence=1.0,
            )
        ]

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--reverse", "--format=%h %s %ad", "--date=short"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "TZ": "UTC"},
        )
    except subprocess.TimeoutExpired:
        return [
            Evidence(
                goal="git history",
                found=False,
                content=None,
                location=str(path),
                rationale="git log timed out",
                confidence=1.0,
            )
        ]
    except FileNotFoundError:
        return [
            Evidence(
                goal="git history",
                found=False,
                content=None,
                location=str(path),
                rationale="git not found",
                confidence=1.0,
            )
        ]

    if result.returncode != 0:
        return [
            Evidence(
                goal="git history",
                found=False,
                content=None,
                location=str(path),
                rationale=result.stderr or "git log failed",
                confidence=1.0,
            )
        ]

    lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
    commit_count = len(lines)
    messages = [ln.split(" ", 2)[-1] if len(ln.split()) >= 3 else ln for ln in lines]

    # Heuristics for healthy vs bulk
    bulk_keywords = {"initial", "init", "bulk", "first commit", "initial commit"}
    has_bulk_style = any(
        any(kw in m.lower() for kw in bulk_keywords) for m in messages[:3]
    )
    healthy = commit_count > 3 and not (commit_count <= 2 and has_bulk_style)

    return [
        Evidence(
            goal="git history",
            found=True,
            content="\n".join(messages[:20]) or None,
            location=str(path),
            rationale=f"commits: {commit_count}, healthy: {healthy}",
            confidence=0.9 if healthy else 0.5,
        ),
        Evidence(
            goal="commit evolution",
            found=healthy,
            content="; ".join(messages[:5]) if messages else None,
            location=str(path),
            rationale="healthy: >3 commits and stepwise evolution" if healthy else "few commits or bulk-style init",
            confidence=1.0 if healthy else 0.4,
        ),
    ]


def repo_investigator_main(state: "AgentState") -> dict:
    """Run RepoInvestigator: clone repo and populate state.evidences["repo"].

    Uses state.repo_url, clones into a temp dir, runs:
    - analyze_state_structure
    - analyze_graph_structure
    - extract_git_history

    Returns:
        State update dict with evidences["repo"] populated.
    """
    import shutil

    repo_url = state.get("repo_url")
    if not repo_url:
        return {"evidences": {"repo": []}}

    try:
        repo_path = clone_repo(repo_url)
    except RepoInvestigatorError as e:
        logger.exception("clone failed: %s", e)
        return {
            "evidences": {
                "repo": [
                    Evidence(
                        goal="clone repository",
                        found=False,
                        content=None,
                        location=repo_url,
                        rationale=str(e),
                        confidence=1.0,
                    )
                ]
            }
        }

    parent = Path(repo_path).parent
    try:
        evidences: list[Evidence] = []
        evidences.extend(analyze_state_structure(repo_path))
        evidences.extend(analyze_graph_structure(repo_path))
        evidences.extend(extract_git_history(repo_path))
    finally:
        shutil.rmtree(parent, ignore_errors=True)

    return {"evidences": {"repo": evidences}}
