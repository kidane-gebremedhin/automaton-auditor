"""RepoInvestigator tools: sandboxed git clone, git history, graph structure analysis.

Satisfies: Git Forensic Analysis, Graph Orchestration Architecture, Safe Tool Engineering.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from pathlib import Path
from pydantic import BaseModel


# -----------------------------------------------------------------------------
# Structured errors (Safe Tool Engineering)
# -----------------------------------------------------------------------------


class RepoToolError(Exception):
    """Base for repo tool failures."""

    pass


class CloneError(RepoToolError):
    """Git clone failed (invalid URL, network, permission)."""

    pass


class GitHistoryError(RepoToolError):
    """Git log or repo access failed."""

    pass


# -----------------------------------------------------------------------------
# Structured results
# -----------------------------------------------------------------------------


class CommitRecord(BaseModel):
    """Single commit from git log."""

    hash_short: str
    message: str
    timestamp: str


class GitHistoryResult(BaseModel):
    """Structured git log output."""

    path: str
    commits: list[CommitRecord]
    total: int


class GraphStructureResult(BaseModel):
    """Structured result of graph AST analysis."""

    path: str
    has_state_graph: bool
    has_add_edge: bool
    has_fan_out: bool
    has_evidence_aggregator: bool
    has_parallel_judges: bool
    node_names: list[str] = []
    edge_count: int = 0
    details: str = ""


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

GITHUB_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+(?:\.git)?$"
)


def clone_repo_sandboxed(repo_url: str, target_dir: str | Path | None = None) -> tuple[str, Path | None]:
    """Clone a GitHub repo into a sandboxed temp directory.

    Uses subprocess.run() for git clone. No os.system. Captures stdout/stderr.
    Caller can pass target_dir from tempfile.TemporaryDirectory(); otherwise
    a new temp dir is created and the caller must clean up the parent of the
    returned path.

    Args:
        repo_url: HTTPS GitHub URL.
        target_dir: Optional parent path (e.g. from TemporaryDirectory()). If
            None, a new mkdtemp() is used.

    Returns:
        (repo_path, cleanup_context): repo_path is the cloned repo root.
        If target_dir was provided, cleanup_context is None. Otherwise it is
        the Path to the temp parent to remove with shutil.rmtree(cleanup_context).

    Raises:
        CloneError: Invalid URL or git clone failure.
    """
    repo_url = repo_url.strip()
    if not GITHUB_URL_PATTERN.match(repo_url):
        raise CloneError(f"Invalid GitHub URL: {repo_url!r}")

    if target_dir is not None:
        parent = Path(target_dir)
        cleanup_path = None
    else:
        parent = Path(tempfile.mkdtemp(prefix="repo_tools_"))
        cleanup_path = parent

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", repo_url, str(parent)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        if cleanup_path is not None:
            import shutil
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError("git clone timed out") from None
    except FileNotFoundError:
        if cleanup_path is not None:
            import shutil
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError("git executable not found") from None

    if result.returncode != 0:
        err = result.stderr or result.stdout or "(no output)"
        if cleanup_path is not None:
            import shutil
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError(f"git clone failed: {err.strip()}")

    subdirs = [d for d in parent.iterdir() if d.is_dir()]
    if len(subdirs) != 1:
        if cleanup_path is not None:
            import shutil
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError("unexpected clone layout (expected single subdir)")

    repo_path = str(subdirs[0].resolve())
    return repo_path, cleanup_path


def extract_git_history(path: str) -> GitHistoryResult:
    """Run git log --oneline --reverse and return structured commits with timestamps.

    Args:
        path: Path to repo root (must contain .git).

    Returns:
        GitHistoryResult with commits (hash, message, timestamp).

    Raises:
        GitHistoryError: Not a git repo or git log failed.
    """
    root = Path(path)
    if not (root / ".git").exists():
        raise GitHistoryError(f"not a git repository: {path}")

    result = subprocess.run(
        ["git", "log", "--oneline", "--reverse", "--format=%h%x00%s%x00%ad", "--date=short"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise GitHistoryError(result.stderr or "git log failed")

    commits: list[CommitRecord] = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\x00", 2)
        if len(parts) >= 3:
            commits.append(
                CommitRecord(hash_short=parts[0], message=parts[1], timestamp=parts[2])
            )
        elif len(parts) == 2:
            commits.append(
                CommitRecord(hash_short=parts[0], message=parts[1], timestamp="")
            )

    return GitHistoryResult(path=str(root), commits=commits, total=len(commits))


def _ast_find_graph_file(repo_path: Path) -> Path | None:
    """Locate graph definition file (e.g. src/graph.py)."""
    candidates = [
        repo_path / "src" / "graph.py",
        repo_path / "graph.py",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _get_call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def analyze_graph_structure(path: str) -> GraphStructureResult:
    """Analyze graph definition with Python ast (no regex).

    Detects: StateGraph instantiation, add_edge, fan-out pattern,
    EvidenceAggregator, parallel Judges. Returns structured result for
    Graph Orchestration Architecture rubric.
    """
    root = Path(path)
    graph_file = _ast_find_graph_file(root)
    if not graph_file:
        return GraphStructureResult(
            path=str(root),
            has_state_graph=False,
            has_add_edge=False,
            has_fan_out=False,
            has_evidence_aggregator=False,
            has_parallel_judges=False,
            details="no graph file found (src/graph.py or graph.py)",
        )

    try:
        source = graph_file.read_text(encoding="utf-8")
    except OSError as e:
        return GraphStructureResult(
            path=str(graph_file),
            has_state_graph=False,
            has_add_edge=False,
            has_fan_out=False,
            has_evidence_aggregator=False,
            has_parallel_judges=False,
            details=f"read error: {e}",
        )

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return GraphStructureResult(
            path=str(graph_file),
            has_state_graph=False,
            has_add_edge=False,
            has_fan_out=False,
            has_evidence_aggregator=False,
            has_parallel_judges=False,
            details=f"syntax error: {e}",
        )

    has_state_graph = False
    has_add_edge = False
    node_names: set[str] = set()
    edge_count = 0
    add_edge_calls: list[tuple[str, str]] = []  # (from, to) for fan-out detection
    has_evidence_aggregator = False
    judge_nodes: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _get_call_name(node)
            if name and "StateGraph" in name:
                has_state_graph = True
            if name == "add_edge":
                has_add_edge = True
                edge_count += 1
                if len(node.args) >= 2:
                    from_node = _arg_to_str(node.args[0])
                    to_node = _arg_to_str(node.args[1])
                    if from_node and to_node:
                        add_edge_calls.append((from_node, to_node))
            if name == "add_node" and node.args and isinstance(node.args[0], ast.Constant):
                node_names.add(str(node.args[0].value))
        if isinstance(node, ast.Name):
            if "EvidenceAggregator" in node.id:
                has_evidence_aggregator = True
            if "judge" in node.id.lower() or "Judge" in node.id:
                judge_nodes.add(node.id)

    # Fan-out: one node has multiple outgoing edges
    from_groups: dict[str, set[str]] = {}
    for fr, to in add_edge_calls:
        from_groups.setdefault(fr, set()).add(to)
    has_fan_out = any(len(tos) > 1 for tos in from_groups.values())

    # Parallel judges: multiple judge-related nodes
    has_parallel_judges = len(judge_nodes) >= 2 or any(
        "judge" in n.lower() for n in node_names
    )

    details_parts = []
    if node_names:
        details_parts.append(f"nodes: {sorted(node_names)}")
    details_parts.append(f"edges: {edge_count}")
    if add_edge_calls:
        details_parts.append(f"add_edge calls: {len(add_edge_calls)}")

    return GraphStructureResult(
        path=str(graph_file),
        has_state_graph=has_state_graph,
        has_add_edge=has_add_edge,
        has_fan_out=has_fan_out,
        has_evidence_aggregator=has_evidence_aggregator,
        has_parallel_judges=has_parallel_judges,
        node_names=sorted(node_names),
        edge_count=edge_count,
        details="; ".join(details_parts),
    )


def _arg_to_str(node: ast.AST) -> str | None:
    """Turn an AST argument (e.g. Constant, Name) into a string."""
    if isinstance(node, ast.Constant):
        return str(node.value) if node.value is not None else None
    if isinstance(node, ast.Name):
        return node.id
    return None
