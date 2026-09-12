"""``agent-judges evaluate`` — confidence-calibration evaluation (Accuracy / AUROC).

Compares system predictions against human labels; logic lives in
``evaluation.py`` so it stays importable without the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from ..evaluation import (
    JudgementFileError,
    build_pairs,
    format_evaluation_report,
    load_judgement_records,
)
from . import app


def _echo_err(msg: str) -> None:
    typer.echo(msg, err=True)


@app.command()
def evaluate(
    predictions: Path = typer.Option(
        ...,
        "--predictions",
        "-p",
        help="系统判定 JSON: [{satisfied, confidence, ...}] 或 AaaJ 格式 {requirements, judge_stats}",
    ),
    labels: Path = typer.Option(
        ...,
        "--labels",
        "-l",
        help="人工标注 JSON: [{satisfied}] 或 {requirements: [...]}",
    ),
):
    """评估置信度校准质量: Accuracy / Mean confidence / AUROC"""
    try:
        pred_records, judge_stats = load_judgement_records(predictions)
        label_records, _ = load_judgement_records(labels)
    except (JudgementFileError, json.JSONDecodeError) as e:
        _echo_err(f"Error: {e}")
        raise typer.Exit(1) from e
    pairs = build_pairs(pred_records, label_records, judge_stats)
    if not pairs:
        _echo_err(
            "Error: 无可比较的标注对(检查两侧记录是否都含 satisfied 字段且数量匹配)。"
        )
        raise typer.Exit(1)
    typer.echo(format_evaluation_report(pairs))
