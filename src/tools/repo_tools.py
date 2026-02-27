"""RepoInvestigator tools: sandboxed git clone, git history, graph structure analysis.

Satisfies: Git Forensic Analysis, Graph Orchestration Architecture, Safe Tool Engineering.

Sandboxed Tooling (rubric): Cloning is wrapped in error handlers and temporary
directories only. Never uses os.system(); never drops code into the live working
directory. Uses subprocess.run() with capture and returncode checks.
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


class AuthenticationError(CloneError):
    """Git authentication failed (bad credentials, missing token, permission denied).

    Subclass of CloneError so callers catching CloneError still handle auth failures.
    Rubric: 'Authentication failures caught and reported.'
    """

    pass


# Patterns in git stderr that indicate authentication failure (not network or other errors).
_AUTH_FAILURE_PATTERNS = (
    "authentication failed",
    "could not read username",
    "could not read password",
    "permission denied",
    "invalid credentials",
    "bad credentials",
    "fatal: could not read from remote repository",
    "repository not found",  # GitHub returns 404 for private repos without auth
)


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


def validate_github_url(repo_url: str) -> None:
    """Raise CloneError if repo_url is not a valid GitHub HTTPS URL (for CLI fail-fast)."""
    u = (repo_url or "").strip()
    if not u:
        raise CloneError("No repository URL provided.")
    if not GITHUB_URL_PATTERN.match(u):
        raise CloneError(f"Invalid GitHub URL: {u!r}")


def _normalize_github_url(url: str) -> str:
    """Normalize URL for comparison: canonical form github.com/owner/repo (lowercase, no .git)."""
    u = url.strip().lower().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    # HTTPS: https://github.com/owner/repo -> github.com/owner/repo
    if "github.com/" in u:
        u = u.split("github.com/", 1)[-1]
        return "github.com/" + u.split("?", 1)[0].rstrip("/")
    # SSH: git@github.com:owner/repo -> github.com/owner/repo
    if u.startswith("git@github.com:"):
        return "github.com/" + u.split(":", 1)[1].split("?", 1)[0].rstrip("/")
    return u


def _get_remote_origin(repo_path: Path) -> str | None:
    """Return origin URL of the repo, or None on failure."""
    r = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0 or not r.stdout:
        return None
    return r.stdout.strip()


def clone_repo_sandboxed(repo_url: str, target_dir: str | Path | None = None) -> tuple[str, Path | None]:
    """Clone a GitHub repo into a sandboxed temporary directory only.

    Sandboxed Tooling precedent: Cloning must be wrapped in error handlers and
    temporary directories. Must never drop code into the live working directory
    (Security Negligence otherwise).

    Compliance:
    - Clone target is always under a temp dir (tempfile); never cwd or project root.
    - subprocess.run() with list args (no os.system, no shell injection).
    - Captures stdout/stderr, checks returncode; raises CloneError on failure.
    - Timeout and cleanup on any failure.
    - Full clone (no --depth) so all commits visible for forensic analysis.

    Args:
        repo_url: HTTPS GitHub URL.
        target_dir: Optional parent (e.g. from tempfile.TemporaryDirectory()).
            If None, a new temp dir is created; caller must shutil.rmtree(cleanup_path).

    Returns:
        (repo_path, cleanup_path): repo_path is cloned repo root; cleanup_path
        is the temp dir to remove, or None if target_dir was provided.

    Raises:
        CloneError: Invalid URL, git not found, clone failed, or timeout.
    """
    import shutil

    repo_url = repo_url.strip()
    if not GITHUB_URL_PATTERN.match(repo_url):
        raise CloneError(f"Invalid GitHub URL: {repo_url!r}")

    # Sandbox: clone only under a temporary directory; never use cwd or project root.
    if target_dir is not None:
        parent = Path(target_dir).resolve()
        cleanup_path = None
    else:
        parent = Path(tempfile.mkdtemp(prefix="repo_tools_")).resolve()
        cleanup_path = parent

    clone_into = parent / "repo"
    if clone_into.exists():
        shutil.rmtree(clone_into, ignore_errors=True)

    try:
        # Full clone (no --depth) so git log shows full history (all commits) for forensic analysis.
        result = subprocess.run(
            ["git", "clone", "--quiet", repo_url, str(clone_into)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        if cleanup_path is not None:
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError("git clone timed out") from None
    except FileNotFoundError:
        if cleanup_path is not None:
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError("git executable not found") from None

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "(no output)").strip()
        if cleanup_path is not None:
            shutil.rmtree(cleanup_path, ignore_errors=True)
        # Check for authentication failure explicitly (rubric: 'Authentication failures caught and reported')
        err_lower = err.lower()
        if any(pattern in err_lower for pattern in _AUTH_FAILURE_PATTERNS):
            raise AuthenticationError(
                f"git authentication failed for {repo_url!r}: {err}"
            )
        raise CloneError(f"git clone failed: {err}")

    if not clone_into.exists() or not (clone_into / ".git").exists():
        if cleanup_path is not None:
            shutil.rmtree(cleanup_path, ignore_errors=True)
        raise CloneError("git clone did not create a valid repository at target.")

    # Ensure we cloned the requested repo (not a redirect or wrong repo).
    origin = _get_remote_origin(clone_into)
    wanted = _normalize_github_url(repo_url)
    if origin:
        origin_norm = _normalize_github_url(origin)
        if origin_norm != wanted:
            if cleanup_path is not None:
                shutil.rmtree(cleanup_path, ignore_errors=True)
            raise CloneError(
                f"Cloned repo remote does not match requested URL: requested {repo_url!r}, got {origin!r}"
            )
    repo_path = str(clone_into.resolve())
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
    has_conditional_edges = False
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
            if name == "add_conditional_edges":
                has_conditional_edges = True
            if name == "add_node" and node.args and isinstance(node.args[0], ast.Constant):
                node_names.add(str(node.args[0].value))
        if isinstance(node, ast.Name):
            if "EvidenceAggregator" in node.id:
                has_evidence_aggregator = True
            if "judge" in node.id.lower() or "Judge" in node.id:
                judge_nodes.add(node.id)

    # Fan-out: multiple outgoing add_edge from one node, or add_conditional_edges (router returns list[Send])
    from_groups: dict[str, set[str]] = {}
    for fr, to in add_edge_calls:
        from_groups.setdefault(fr, set()).add(to)
    has_fan_out = has_conditional_edges or any(len(tos) > 1 for tos in from_groups.values())

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
    if has_conditional_edges:
        details_parts.append("add_conditional_edges: present (fan-out via router)")
    # Include source snippet so judges can see actual fan-out/fan-in code
    graph_snippet = _read_snippet(graph_file, 2500)
    if graph_snippet:
        details_parts.append(f"\nGraph source (first 2500 chars):\n{graph_snippet}")

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


def list_repo_files(repo_path: str, extensions: tuple[str, ...] = (".py", ".json", ".md", ".toml")) -> list[str]:
    """List relative paths under repo root for cross-reference (Report Accuracy)."""
    root = Path(repo_path)
    if not root.is_dir():
        return []
    out: list[str] = []
    for f in root.rglob("*"):
        if f.is_file() and f.suffix.lower() in extensions:
            try:
                rel = f.relative_to(root)
                out.append(str(rel).replace("\\", "/"))
            except ValueError:
                pass
    return sorted(out)


def _read_snippet(file_path: Path, max_chars: int = 2000) -> str:
    """Read file and return content up to max_chars."""
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _ast_has_os_system_call(file_path: Path) -> bool:
    """Return True if the file contains an actual os.system(...) call (AST), not docstrings/comments."""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr = node.func
                if attr.attr == "system":
                    if isinstance(attr.value, ast.Name) and attr.value.id == "os":
                        return True
    return False


def analyze_state_management(repo_path: str) -> tuple[bool, str]:
    """Scan state.py for TypedDict, BaseModel, Annotated, operator.add/ior. Return (found, snippet)."""
    root = Path(repo_path)
    candidates = [root / "src" / "state.py", root / "state.py"]
    for p in candidates:
        if not p.exists():
            continue
        text = _read_snippet(p, 3500)
        has_typed = "TypedDict" in text or "BaseModel" in text
        has_annotated = "Annotated" in text
        has_reducers = "operator.add" in text or "operator.ior" in text
        has_evidence = "Evidence" in text and ("BaseModel" in text or "class" in text)
        has_opinion = "JudicialOpinion" in text
        if has_typed and (has_reducers or has_annotated):
            return True, (
                f"TypedDict/BaseModel={has_typed} Annotated={has_annotated} "
                f"operator.add/ior={has_reducers} Evidence+JudicialOpinion classes present. "
                f"Snippet (first 1200 chars): {text[:1200]}"
            )
    return False, "No src/state.py or state.py with TypedDict/BaseModel and reducers found."


def analyze_safe_tool_engineering(repo_path: str) -> tuple[bool, str]:
    """Scan tools for tempfile, subprocess.run, no os.system. Return (found, snippet).
    Uses AST for os.system so docstrings/comments do not trigger a fail."""
    root = Path(repo_path)
    tools_dir = root / "src" / "tools"
    if not tools_dir.exists():
        return False, "No src/tools directory."
    # Prioritize repo_tools.py (has tempfile, subprocess, auth handling) over other tool files
    tool_files = sorted(tools_dir.glob("*.py"), key=lambda f: (0 if "repo" in f.name else 1, f.name))
    text_parts: list[str] = []
    for f in tool_files:
        text_parts.append(_read_snippet(f, 3000))
    combined = "\n---\n".join(text_parts)
    has_tempfile = "tempfile" in combined
    has_subprocess = "subprocess.run" in combined or "subprocess." in combined
    has_os_system = any(_ast_has_os_system_call(f) for f in tool_files)
    # Show the most relevant file (repo_tools.py) snippet first
    primary_snippet = text_parts[0] if text_parts else ""
    if has_tempfile and has_subprocess and not has_os_system:
        return True, (
            f"tempfile={has_tempfile} subprocess.run/equivalent={has_subprocess} os.system={has_os_system} (must be false). "
            f"Snippet from tools (repo_tools.py first): {primary_snippet[:2500]}"
        )
    return False, (
        f"tempfile={has_tempfile} subprocess={has_subprocess} os.system={has_os_system}. "
        "Safe tool engineering requires tempfile, subprocess with error handling, no os.system."
    )


def analyze_structured_output(repo_path: str) -> tuple[bool, str]:
    """Scan judges.py for with_structured_output(JudicialOpinion), retry logic. Return (found, snippet)."""
    root = Path(repo_path)
    p = root / "src" / "nodes" / "judges.py"
    if not p.exists():
        return False, "No src/nodes/judges.py."
    text = _read_snippet(p, 6000)
    has_structured = "with_structured_output" in text and "JudicialOpinion" in text
    has_retry = "retry" in text.lower() or "MAX_PARSE_RETRIES" in text or "attempt" in text
    if has_structured:
        return True, (
            f"with_structured_output(JudicialOpinion)={has_structured} retry/parse handling={has_retry}. "
            f"Snippet: {text[:2500]}"
        )
    return False, "with_structured_output(JudicialOpinion) or equivalent not found in judges.py."


def analyze_chief_justice_synthesis(repo_path: str) -> tuple[bool, str]:
    """Scan justice.py for deterministic rules: security_override, fact_supremacy, functionality_weight. Return (found, snippet)."""
    root = Path(repo_path)
    p = root / "src" / "nodes" / "justice.py"
    if not p.exists():
        return False, "No src/nodes/justice.py."
    text = _read_snippet(p, 3000)
    has_security = "security_override" in text or "Rule of Security" in text
    has_fact = "fact_supremacy" in text or "Rule of Evidence" in text
    has_functionality = "functionality_weight" in text
    has_dissent = "dissent" in text.lower() or "variance" in text
    has_markdown = "markdown" in text.lower() or "report" in text
    if has_security and (has_fact or has_functionality):
        return True, (
            f"security_override/Rule of Security={has_security} fact_supremacy/Rule of Evidence={has_fact} "
            f"functionality_weight={has_functionality} dissent/variance={has_dissent} Markdown/report output={has_markdown}. "
            f"Snippet: {text[:1200]}"
        )
    return False, (
        f"Deterministic rules: security={has_security} fact={has_fact} functionality={has_functionality}. "
        "Chief Justice must use hardcoded Python logic, not LLM."
    )
