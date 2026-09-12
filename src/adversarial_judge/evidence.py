"""Graphify evidence collection for active verification.

When a graphify knowledge graph is available in the working directory,
collects code-structure evidence (callers, callees, dependencies,
cross-file references) and returns it as text for injection into
reviewer prompts.  When graphify is absent or no graph exists, returns
``None`` — the system silently falls back to pure-LLM mode.

Design: this is *evidence injection*, not *tool execution*.  The
reviewer (LLM) never calls graphify; the engine collects evidence
*before* dispatching tasks and appends it to the prompt context.  The
reviewer reads the evidence as richer context, same as any
``--context`` text.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["collect_graphify_evidence", "enrich_context"]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: File extensions whose content warrants graphify evidence.
_CODE_EXTENSIONS = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs",
    ".go", ".rs", ".java", ".kt", ".scala", ".clj",
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
    ".cs", ".rb", ".php", ".swift", ".dart", ".lua",
    ".zig", ".ex", ".exs", ".hs", ".jl", ".ml", ".fs",
})

#: Regex detecting code keywords to distinguish code from prose.
_CODE_KEYWORDS = re.compile(
    r"\b(?:def|class|function|fn|func|import|package|pub|private|public|"
    r"async|await|return|elif|struct|enum|interface|trait|impl|module|"
    r"export|const|let|var|void)\b",
)

#: Timeout for a single graphify CLI invocation (seconds).
_CLI_TIMEOUT = 15

#: Token budget for ``graphify query`` output.
_QUERY_BUDGET = 1500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_graphify_evidence(
    content: str,
    filename: str | None = None,
    graph_path: Path | None = None,
) -> str | None:
    """Collect code-structure evidence from a graphify knowledge graph.

    Returns evidence text suitable for prompt injection, or ``None`` when
    graphify is unavailable, no graph exists, or the content does not
    look like code.

    Parameters
    ----------
    content
        The text under review.
    filename
        Optional filename hint (used to detect code files and to look
        up nodes by stem).
    graph_path
        Explicit path to ``graph.json``.  Defaults to
        ``./.graph/graph.json`` in the current working directory.
    """
    # 1. graphify CLI must be on PATH
    if not shutil.which("graphify"):
        logger.debug("graphify CLI not found in PATH; skipping active verification")
        return None

    # 2. content must look like code (skip pure prose documents)
    if not _is_code_like(content, filename):
        logger.debug("content does not look like code; skipping graphify evidence")
        return None

    # 3. graph file must exist
    if graph_path is None:
        graph_path = Path.cwd() / ".graph" / "graph.json"
    if not graph_path.is_file():
        logger.debug("graphify graph not found at %s; skipping", graph_path)
        return None

    # 4. collect evidence
    parts: list[str] = []

    query_text = _build_query(content, filename)
    if query_text:
        result = _run_graphify(
            ["query", query_text, "--budget", str(_QUERY_BUDGET)],
            graph_path,
        )
        if result:
            parts.append("## 相关节点与调用关系\n" + result)

    if filename:
        node_name = Path(filename).stem
        result = _run_graphify(["explain", node_name], graph_path)
        if result:
            parts.append(f"## {node_name} 的邻居与依赖\n" + result)

    if not parts:
        return None

    header = "# 代码结构证据（来自 graphify 图谱）\n\n"
    footer = (
        "\n\n（以上证据来自预构建的代码知识图谱，供审查时参考验证 findings。"
        "若证据与被审查内容矛盾，请在 finding 的 evidence 中指出。）"
    )
    return header + "\n\n".join(parts) + footer


def enrich_context(
    content: str,
    context: str | None,
    filename: str | None = None,
    graph_path: Path | None = None,
) -> str | None:
    """Return *context* enriched with graphify evidence.

    If graphify evidence is available it is appended to the existing
    context.  If not, the original context is returned unchanged — the
    caller never needs to branch on graphify availability.
    """
    evidence = collect_graphify_evidence(content, filename, graph_path=graph_path)
    if evidence is None:
        return context
    if context:
        return context + "\n\n" + evidence
    return evidence


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_code_like(content: str, filename: str | None) -> bool:
    """Heuristic: does this content look like code rather than prose?"""
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in _CODE_EXTENSIONS:
            return True
    matches = _CODE_KEYWORDS.findall(content[:2000])
    return len(matches) >= 3


def _build_query(content: str, filename: str | None) -> str:
    """Build a graphify query string from the reviewed content."""
    snippet = content[:500].strip()
    if filename:
        snippet = f"{filename}\n{snippet}"
    return snippet


def _run_graphify(args: list[str], graph_path: Path) -> str | None:
    """Run graphify CLI, return stdout text, or ``None`` on any failure."""
    cmd = ["graphify"] + args + ["--graph", str(graph_path)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("graphify %s error: %s", args[0], exc)
        return None

    if result.returncode != 0:
        logger.debug(
            "graphify %s failed (rc=%d): %s",
            args[0],
            result.returncode,
            result.stderr[:200],
        )
        return None

    output = result.stdout.strip()
    if not output:
        return None
    # graphify sometimes prints human-facing errors to stdout (not stderr)
    if "未找到" in output or "error:" in output.lower():
        return None
    return output
