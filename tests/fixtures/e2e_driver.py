"""E2E driver — a faithful automation of the judge-manager protocol.

Mirrors ``src/adversarial_judge/integrations/<host>/agent/judge-manager.md``:

    prepare (``review --file ... --run-dir RUN``) → for each manifest task:
    read ``tasks/<id>.md`` verbatim → answer (mock scenario or real LLM) →
    write raw text to ``results/<id>.md`` → ``review --resume --run-dir RUN``
    → repeat until ``done: true`` → read ``verdict.json``.

Used by:
- ``tests/test_e2e.py`` — automated e2e (mock scenarios: zero token;
  integration marker: real LLM)
- ``scripts/e2e_review.py`` — manual runs producing readable reports

This module must stay importable WITHOUT pytest (plain script usage).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from typer.testing import CliRunner

from adversarial_judge.cli import app
from adversarial_judge.utils.truncate import truncate_string

__all__ = [
    "PROJECTS_DIR",
    "REVIEWERS_DIR",
    "SKILLS_DIR",
    "RunOutcome",
    "MockScenarioAnswerer",
    "LitellmAnswerer",
    "drive_review",
]

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEWERS_DIR = REPO_ROOT / "reviewers"
SKILLS_DIR = REPO_ROOT / "skills"
PROJECTS_DIR = REPO_ROOT / "tests" / "project"

# --- canned agent outputs (schema-conformant verdict JSON in fenced blocks,
# --- exactly what the verdict parse chain consumes) ------------------------

CLEAN_VERDICT = """```json
{"severity": "pass", "confidence": 0.92,
 "reasoning": "文档结构完整,需求均可验证,未发现重大缺陷。",
 "findings": [], "satisfied": true}
```"""

CLEAN_META_VERDICT = """```json
{"severity": "pass", "confidence": 0.9,
 "reasoning": "元审查:原审查结论依据充分,维持原判。",
 "findings": [], "satisfied": true, "confidence_adjustment": 0.0}
```"""

PROBLEM_VERDICT = """```json
{"severity": "critical", "confidence": 0.85,
 "reasoning": "存在关键缺陷:非功能需求无量化指标,部分验收标准不可客观判定。",
 "findings": [{"description": "非功能需求缺少量化指标", "severity": "major",
   "confidence": 0.7, "evidence": "原文:界面响应应尽量快",
   "suggestion": "补充可测量的性能指标(如 P95 < 200ms)"}],
 "satisfied": false}
```"""

PROBLEM_META_VERDICT = """```json
{"severity": "major", "confidence": 0.8,
 "reasoning": "元审查:原审查基本成立,但置信度偏乐观,存在漏判风险。",
 "findings": [], "satisfied": false, "confidence_adjustment": -0.2}
```"""

CLEAN_DEBATE_POSITION = "维持原判:该文档质量良好,关键要求完整可验证,无需修改。"
PROBLEM_DEBATE_POSITION = (
    "我坚持该文档存在量化指标缺失问题:性能要求无可测量数值,"
    "验收标准无法客观判定,必须补充量化指标后才可通过。"
)
PROBLEM_META_DEBATE_POSITION = "元审查辩论:原审查的置信度偏乐观,建议下调校准。"

_VERDICT_KINDS = {"sentinel_review", "independent_review", "blind_final"}
_META_VERDICT_KINDS = {"meta_review", "meta_blind_final"}
_DEBATE_KINDS = {"debate", "meta_debate"}


@dataclass
class RunOutcome:
    """Everything the e2e layer needs to assert on one completed run."""

    run_id: str
    logs_dir: Path
    evidence_dir: Path
    verdict: dict  # parsed verdict.json
    rounds: int  # resume invocations after prepare
    task_ids: list[str] = field(default_factory=list)  # every emitted task id
    answered: list[str] = field(default_factory=list)  # task ids actually answered


class MockScenarioAnswerer:
    """Deterministic scenario answering — zero token, full state-machine run.

    ``clean``   → every reviewer passes with high confidence (Gate 1 early
                  stop on short content / standard continuation on long).
    ``problem`` → sentinel + panel report critical findings (Gate 2 →
                  thorough: 2 debate rounds + blind final + meta review with
                  a −0.2 confidence adjustment → escalation).
    """

    def __init__(self, scenario: str = "problem"):
        if scenario not in ("clean", "problem"):
            raise ValueError(f"unknown scenario: {scenario!r}")
        self.scenario = scenario
        self.calls = 0

    def answer(self, task: dict, prompt: str) -> str:  # noqa: ARG002
        self.calls += 1
        kind = task["kind"]
        if kind in _VERDICT_KINDS:
            return CLEAN_VERDICT if self.scenario == "clean" else PROBLEM_VERDICT
        if kind in _META_VERDICT_KINDS:
            return (
                CLEAN_META_VERDICT if self.scenario == "clean"
                else PROBLEM_META_VERDICT
            )
        if kind in _DEBATE_KINDS:
            if self.scenario == "clean":
                return CLEAN_DEBATE_POSITION
            return (
                PROBLEM_META_DEBATE_POSITION
                if kind == "meta_debate"
                else PROBLEM_DEBATE_POSITION
            )
        raise ValueError(f"unknown task kind: {kind!r}")

    def stats(self) -> str:
        return f"mock scenario={self.scenario}, calls={self.calls}"


class LitellmAnswerer:
    """Real-LLM answering: persona from the reviewer registry (simulating the
    host's installed reviewer Agent definition), task prompt passed through
    verbatim (truncation-guarded)."""

    def __init__(
        self,
        model: str = "anthropic/claude-sonnet-4-20250514",
        base_url: str | None = None,
        max_calls: int = 120,
        max_prompt_tokens: int = 50000,
    ):
        from adversarial_judge.llm.provider import LLM
        from adversarial_judge.reviewer import ReviewerRegistry

        self._llm = LLM(model=model, base_url=base_url)
        self._registry = ReviewerRegistry(REVIEWERS_DIR, skills_dir=SKILLS_DIR)
        self._max_calls = max_calls
        self._max_prompt_tokens = max_prompt_tokens
        self.calls = 0

    def answer(self, task: dict, prompt: str) -> str:
        if self.calls >= self._max_calls:
            raise RuntimeError(
                f"e2e driver exceeded max_calls={self._max_calls} LLM calls — "
                "aborting the run (raise --max-calls if this was expected)"
            )
        system = ""
        try:
            system = self._registry.get(task["agent"]).system_prompt
        except KeyError:
            pass  # unknown agent (e.g. host-only reviewer): answer generically
        user = truncate_string(prompt, max_tokens=self._max_prompt_tokens)
        self.calls += 1
        return self._llm.complete(system, user)

    def stats(self) -> str:
        tokens = self._llm.total_input_tokens + self._llm.total_output_tokens
        cost = self._llm.cost.accumulated_cost
        return f"model={self._llm.model_name}, calls={self.calls}, tokens={tokens}, cost=${cost:.4f}"


def _invoke(args: list[str]) -> dict:
    result = runner.invoke(app, args)
    if result.exit_code != 0:
        raise RuntimeError(
            f"agent-judges CLI failed (exit={result.exit_code}):\n{result.output}"
        )
    return json.loads(result.stdout)


def drive_review(
    doc: Path,
    answerer: MockScenarioAnswerer | LitellmAnswerer,
    *,
    context_file: Path | None = None,
    extra_args: list[str] | None = None,
    max_rounds: int = 60,
    verbose: bool = False,
) -> RunOutcome:
    """Drive one complete agent-mode review through the judge-manager protocol.

    Returns the parsed ``verdict.json`` plus protocol bookkeeping. Raises
    ``RuntimeError`` on CLI failure or if the run does not finish within
    ``max_rounds`` resume rounds (guard against driver/engine livelock).
    """
    common = [
        "--reviewers-dir", str(REVIEWERS_DIR),
        "--skills-dir", str(SKILLS_DIR),
    ]
    args = [
        "review", "--llm", "agent",
        "--file", str(doc),
        *common,
        *(extra_args or []),
    ]
    if context_file is not None:
        args += ["--context", context_file.read_text(encoding="utf-8")]

    def _log(msg: str) -> None:
        if verbose:
            print(f"[drive_review] {msg}", file=sys.stderr)

    manifest = _invoke(args)
    logs_dir = Path(manifest["logs_dir"])
    evidence_dir = Path(manifest["evidence_dir"])
    run_id = manifest["run_id"]
    _log(f"prepare: run_id={run_id} stage={manifest['stage']}")

    outcome = RunOutcome(
        run_id=run_id,
        logs_dir=logs_dir,
        evidence_dir=evidence_dir,
        verdict={},
        rounds=0,
    )

    while not manifest["done"]:
        for task in manifest["tasks"]:
            outcome.task_ids.append(task["task_id"])
            result_file = logs_dir / task["result_file"]
            if result_file.exists():
                continue  # engine re-emitted an already-answered task
            prompt = (logs_dir / task["prompt_file"]).read_text(encoding="utf-8")
            result_file.parent.mkdir(parents=True, exist_ok=True)
            result_file.write_text(answerer.answer(task, prompt), encoding="utf-8")
            outcome.answered.append(task["task_id"])
        manifest = _invoke(["review", "--resume", *common])
        outcome.rounds += 1
        _log(f"resume #{outcome.rounds}: stage={manifest['stage']}")
        if outcome.rounds > max_rounds:
            raise RuntimeError(
                f"e2e driver exceeded {max_rounds} resume rounds for run_id={run_id}"
            )

    # manifest with done=true carries evidence_dir; use it to locate verdict
    evidence_dir = Path(manifest["evidence_dir"])
    verdict_file = evidence_dir / manifest.get("verdict_file", "verdict.json")
    outcome.verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
    return outcome
