"""Run-state model and run-directory IO for the prepare/resume engine (FR-11).

A review run is a persistent state machine living in a run directory:

    RUN/
      state.json          this model (the single source of progress truth)
      input/content.md    review-target snapshot (+ context.md when provided)
      tasks/<id>.md       verbatim prompt for one agent task
      results/<id>.md     raw agent output written back by the driver
      verdict.json / report.md   terminal artifacts

The engine (:mod:`adversarial_judge.engine`) transitions the state with a
pure ``advance(state, results)`` function; the CLI (agent mode) and the
driver agent (judge-manager) only persist/load and shuttle files.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from .types import Verdict

__all__ = [
    "Stage",
    "TaskKind",
    "AgentTask",
    "RunState",
    "run_dir_layout",
    "new_run_dir",
    "save_state",
    "load_state",
    "write_task",
    "read_results",
    "snapshot_input",
]

#: default root for auto-created run dirs (relative to CWD)
DEFAULT_RUNS_ROOT = Path(".agent-judges") / "runs"


class Stage(StrEnum):
    """State-machine stages; ``done`` is the only terminal stage."""

    AWAITING_SENTINEL = "awaiting_sentinel"
    AWAITING_PANEL = "awaiting_panel"
    AWAITING_DEBATE = "awaiting_debate"
    AWAITING_FINAL = "awaiting_final"
    AWAITING_META = "awaiting_meta"
    AWAITING_META_DEBATE = "awaiting_meta_debate"
    AWAITING_META_FINAL = "awaiting_meta_final"
    DONE = "done"


class TaskKind(StrEnum):
    SENTINEL_REVIEW = "sentinel_review"
    INDEPENDENT_REVIEW = "independent_review"
    DEBATE = "debate"
    BLIND_FINAL = "blind_final"
    META_REVIEW = "meta_review"
    META_DEBATE = "meta_debate"
    META_BLIND_FINAL = "meta_blind_final"


class AgentTask(BaseModel):
    """One unit of driver work: run agent ``agent`` with a verbatim prompt."""

    task_id: str
    agent: str  # reviewer agent name (host namespace, as installed)
    kind: TaskKind
    prompt: str  # verbatim; also written to tasks/<task_id>.md


class DebateRound(BaseModel):
    """One completed debate round: each panelist's argued position."""

    positions: list[str]  # aligned with RunState.panel order


class RunState(BaseModel):
    """Complete persistent state of one review run (FR-11)."""

    # static inputs (fixed at prepare)
    content: str
    context: str | None = None
    filename: str | None = None
    panel: list[str] = Field(default_factory=list)  # active reviewer names
    all_reviewers: list[str] = Field(default_factory=list)  # full pool
    token_count: int = 0
    content_type: str = "other"
    threshold: float = 0.8
    gated: bool = True  # progressive gates vs fixed plan
    max_tier: str = "thorough"
    majority_votes: dict[str, int] = Field(default_factory=dict)  # name → N

    # plan (gate 2 / fixed params)
    tier: str | None = None  # fast (early stop) / standard / thorough
    planned_debate_rounds: int = 0
    planned_review_depth: int = 0

    # progression
    stage: Stage = Stage.AWAITING_SENTINEL
    start_panel: int = 1
    rounds_done: int = 0
    meta_depth_done: int = 0

    # collected (reviewer name → verdict / round records)
    individual: dict[str, Verdict] = Field(default_factory=dict)
    debate_rounds: list[DebateRound] = Field(default_factory=list)
    final_verdicts: dict[str, Verdict] = Field(default_factory=dict)
    verdict: Verdict | None = None  # synthesized (uncalibrated)
    consensus_score: float = 0.0
    stability_score: float = 1.0
    stability_degraded: bool = False

    # audit
    gate1_reason: str | None = None
    gate2_reason: str | None = None
    early_stopped: bool = False
    meta_verdict: Verdict | None = None  # last meta layer's own verdict
    meta_individual: dict[str, Verdict] = Field(default_factory=dict)
    # meta debate progression (B-2 fix: engine meta now mirrors the legacy
    # 4-phase meta debate instead of Phase-1-only + synthesis)
    meta_names: list[str] = Field(default_factory=list)  # active meta reviewers
    meta_positions: list[str] = Field(default_factory=list)  # aligned positions
    meta_debate_rounds_done: int = 0
    meta_final_verdicts: dict[str, Verdict] = Field(default_factory=dict)
    route_reason: str = ""


# ---------------------------------------------------------------------------
# run-directory IO
# ---------------------------------------------------------------------------


def run_dir_layout(run_dir: Path) -> dict[str, Path]:
    """Standard sub-paths of a run directory (created lazily by callers)."""
    return {
        "state": run_dir / "state.json",
        "content": run_dir / "input" / "content.md",
        "context": run_dir / "input" / "context.md",
        "tasks": run_dir / "tasks",
        "results": run_dir / "results",
        "verdict": run_dir / "verdict.json",
        "report": run_dir / "report.md",
    }


def new_run_dir(root: Path | None = None, label: str = "run") -> Path:
    """Create a fresh timestamped run directory; error if it exists."""
    base = root or DEFAULT_RUNS_ROOT
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = base / f"{stamp}-{label}"
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    for sub in ("input", "tasks", "results"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def snapshot_input(run_dir: Path, content: str, context: str | None) -> None:
    """Freeze the review target (and optional context) into the run dir."""
    paths = run_dir_layout(run_dir)
    paths["content"].write_text(content, encoding="utf-8")
    if context:
        paths["context"].write_text(context, encoding="utf-8")


def save_state(run_dir: Path, state: RunState) -> None:
    """Persist the state machine (idempotent, atomic-enough via replace)."""
    paths = run_dir_layout(run_dir)
    tmp = paths["state"].with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(paths["state"])


def load_state(run_dir: Path) -> RunState:
    """Load the state machine from a run directory."""
    paths = run_dir_layout(run_dir)
    if not paths["state"].is_file():
        raise FileNotFoundError(
            f"no state.json in {run_dir} — initialize first (run without --resume)"
        )
    return RunState.model_validate_json(paths["state"].read_text(encoding="utf-8"))


def write_task(run_dir: Path, task: AgentTask) -> None:
    """Write one task: verbatim prompt file + a small manifest entry.

    The manifest (tasks/<id>.json) carries agent/kind metadata; the prompt
    (.md) is what the driver must pass to the agent VERBATIM.
    """
    paths = run_dir_layout(run_dir)
    (paths["tasks"] / f"{task.task_id}.md").write_text(task.prompt, encoding="utf-8")
    (paths["tasks"] / f"{task.task_id}.json").write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "agent": task.agent,
                "kind": task.kind.value,
                "prompt_file": f"{task.task_id}.md",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def read_results(run_dir: Path) -> dict[str, str]:
    """Read all driver-written results.

    An existing-but-empty file is a **collected-but-failed** task (driver
    red-line: write the raw outcome, even empty) — returned as ``""`` so the
    engine degrades it; only a *missing* file means "not run yet".
    """
    paths = run_dir_layout(run_dir)
    results: dict[str, str] = {}
    if not paths["results"].is_dir():
        return results
    for f in sorted(paths["results"].glob("*.md")):
        results[f.stem] = f.read_text(encoding="utf-8")
    return results


def copy_run_output(run_dir: Path, dest_dir: Path) -> None:
    """Copy terminal artifacts to ``--output-dir`` (both-format mode)."""
    paths = run_dir_layout(run_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for key in ("report", "verdict"):
        src = paths[key]
        if src.is_file():
            shutil.copy2(src, dest_dir / src.name)
