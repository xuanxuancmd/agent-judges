"""``agent-judges`` — the adversarial-judge CLI package (FR-5).

Commands live in sibling modules and register on ``app``:
- ``review``   — the adversarial-review command (agent-driven prepare/resume)
- ``install``  — install judge-manager + reviewer agents into a host (FR-10)
- ``inspect``  — list-reviewers / list-skills
- ``evaluate`` — confidence-calibration evaluation (Accuracy / AUROC)
"""

from typer import Typer

app = Typer(
    name="agent-judges",
    help="对抗审查: 对 AI 生成的内容进行多 agent 辩论式审查",
    no_args_is_help=True,
)

from . import evaluate, inspect, install, review  # noqa: E402,F401  (register commands)

if __name__ == "__main__":
    app()
