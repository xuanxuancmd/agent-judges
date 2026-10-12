"""Run-state model and run-directory IO for the prepare/resume engine (FR-11).

A review run is a persistent state machine whose artifacts are split across
two roots for clean separation of runtime logs and review evidence:

    .harness/logs/judges/<run_id>/
      state.json          this model (the single source of progress truth)
      tasks/<id>.md       verbatim prompt for one agent task
      results/<id>.md     raw agent output written back by the driver

    .harness/evidence/judges/<run_id>/
      verdict.json        final synthesized verdict (terminal artifact)
      report.md           human-readable report (terminal artifact)

The input snapshot is **not** written — the original file path is recorded in
``RunState.filename``, and the content is embedded verbatim in every task
prompt, making a frozen copy redundant.

The engine (:mod:`agent_judges.engine`) transitions the state with a
pure ``advance(state, results)`` function; the CLI (agent mode) and the
driver agent (judge-manager) only persist/load and shuttle files.

Test isolation: set ``AGENT_JUDGES_LOGS_ROOT`` / ``AGENT_JUDGES_EVIDENCE_ROOT``
environment variables to redirect both roots to a per-test ``tmp_path``.
"""

from __future__ import annotations

import json
import os
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
    "new_run",
    "find_latest_run",
    "save_state",
    "load_state",
    "write_task",
    "read_results",
    "copy_run_output",
    "DEFAULT_LOGS_ROOT",
    "DEFAULT_EVIDENCE_ROOT",
]

#: default roots for run artifacts (relative to CWD)
DEFAULT_LOGS_ROOT = Path(".harness") / "logs" / "judges"
DEFAULT_EVIDENCE_ROOT = Path(".harness") / "evidence" / "judges"

#: env var overrides (used by tests for per-test isolation via tmp_path)
_LOGS_ROOT_ENV = "AGENT_JUDGES_LOGS_ROOT"
_EVIDENCE_ROOT_ENV = "AGENT_JUDGES_EVIDENCE_ROOT"


def _roots() -> tuple[Path, Path]:
    """Resolve logs/evidence roots, allowing env override for tests."""
    logs = Path(os.environ.get(_LOGS_ROOT_ENV, str(DEFAULT_LOGS_ROOT)))
    evidence = Path(os.environ.get(_EVIDENCE_ROOT_ENV, str(DEFAULT_EVIDENCE_ROOT)))
    return logs, evidence


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

    # identity (set at prepare, used to locate both logs and evidence dirs)
    run_id: str = ""

    # static inputs (fixed at prepare)
    content: str
    context: str | None = None
    filename: str | None = None
    panel: list[str] = Field(default_factory=list)  # active reviewer names
    all_reviewers: list[str] = Field(default_factory=list)  # full pool
    token_count: int = 0
    content_type: str = "document"
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
    conformity_warnings: list[str] = Field(default_factory=list)

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


def run_dir_layout(run_id: str) -> dict[str, Path]:
    """Standard sub-paths for a run, split across logs and evidence roots.

    Runtime logs (state, tasks, results) live under ``.harness/logs/judges/``.
    Review evidence (verdict, report) lives under ``.harness/evidence/judges/``.
    Both share the same ``run_id`` sub-directory name.
    """
    logs, evidence = _roots()
    run_logs = logs / run_id
    run_evidence = evidence / run_id
    return {
        "logs_dir": run_logs,
        "evidence_dir": run_evidence,
        "state": run_logs / "state.json",
        "tasks": run_logs / "tasks",
        "results": run_logs / "results",
        "verdict": run_evidence / "verdict.json",
        "report": run_evidence / "report.md",
    }


def new_run(label: str = "run") -> str:
    """Create a fresh timestamped run directory pair; return the ``run_id``.

    Creates ``logs/<run_id>/{tasks,results}`` and ``evidence/<run_id>/``.
    Raises ``FileExistsError`` if the timestamped name already collides.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_id = f"{stamp}-{label}"
    paths = run_dir_layout(run_id)
    (paths["logs_dir"] / "tasks").mkdir(parents=True, exist_ok=False)
    (paths["logs_dir"] / "results").mkdir(parents=True, exist_ok=False)
    paths["evidence_dir"].mkdir(parents=True, exist_ok=True)
    return run_id


def find_latest_run() -> str | None:
    """Find the most recent **incomplete** run under the logs root.

    Scans ``logs/`` for directories with a ``state.json`` but no verdict yet
    (evidence ``verdict.json`` absent). Returns the ``run_id`` (directory name)
    of the newest such run, or ``None`` if no resumable run exists.
    """
    logs, _ = _roots()
    if not logs.is_dir():
        return None
    candidates: list[tuple[float, str]] = []
    for d in logs.iterdir():
        if not d.is_dir():
            continue
        state_file = d / "state.json"
        if not state_file.is_file():
            continue
        paths = run_dir_layout(d.name)
        if paths["verdict"].is_file():
            continue  # already finished — not resumable
        candidates.append((state_file.stat().st_mtime, d.name))
    if not candidates:
        return None
    candidates.sort(reverse=True)  # newest mtime first
    return candidates[0][1]


def save_state(run_id: str, state: RunState) -> None:
    """Persist the state machine (idempotent, atomic-enough via replace)."""
    paths = run_dir_layout(run_id)
    tmp = paths["state"].with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(paths["state"])


def load_state(run_id: str) -> RunState:
    """Load the state machine from the logs directory for ``run_id``."""
    paths = run_dir_layout(run_id)
    if not paths["state"].is_file():
        raise FileNotFoundError(
            f"no state.json in {paths['logs_dir']} — initialize first (run without --resume)"
        )
    return RunState.model_validate_json(paths["state"].read_text(encoding="utf-8"))


def write_task(run_id: str, task: AgentTask) -> None:
    """Write one task: verbatim prompt file + a small manifest entry.

    The manifest (tasks/<id>.json) carries agent/kind metadata; the prompt
    (.md) is what the driver must pass to the agent VERBATIM.
    """
    paths = run_dir_layout(run_id)
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


def read_results(run_id: str) -> dict[str, str]:
    """Read all driver-written results.

    An existing-but-empty file is a **collected-but-failed** task (driver
    red-line: write the raw outcome, even empty) — returned as ``""`` so the
    engine degrades it; only a *missing* file means "not run yet".
    """
    paths = run_dir_layout(run_id)
    results: dict[str, str] = {}
    if not paths["results"].is_dir():
        return results
    for f in sorted(paths["results"].glob("*.md")):
        results[f.stem] = f.read_text(encoding="utf-8")
    return results


def copy_run_output(run_id: str, dest_dir: Path) -> None:
    """Copy terminal artifacts (verdict + report) to ``--output-dir``."""
    paths = run_dir_layout(run_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for key in ("report", "verdict"):
        src = paths[key]
        if src.is_file():
            shutil.copy2(src, dest_dir / src.name)
