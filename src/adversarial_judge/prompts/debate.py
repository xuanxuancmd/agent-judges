"""Debate-round and blind-final prompt builders (Phase 2 / Phase 3).

Provenance tagging (落地项 1): every reference to another reviewer's claim
must be annotated with a tri-state cognitive status — ``[✓已确认]`` you
verified it in the reviewed content, ``[✗已反驳]`` you found it false, or
``[?未验证]`` you cannot confirm or refute it. Unannotated references are
treated as invalid rebuttals, and ``[?未验证]`` claims must not be used as
a basis for adjusting severity or confidence.

Agreement intensity (落地项 3): ``skepticism`` is auto-inferred from Phase-1
signals (consensus / max severity) — no external configuration needed.
``None`` falls back to the default moderate-skepticism frame.
"""

from __future__ import annotations

__all__ = [
    "build_debate_system_prompt",
    "build_debate_user_prompt",
    "build_blind_final_system_prompt",
    "build_blind_final_user_prompt",
]

#: Default skepticism when Phase-1 signals are unavailable.
_DEFAULT_SKEPTICISM = 0.7


def _challenge_clause(skepticism: float) -> str:
    """Render the skepticism-dependent challenge instruction.

    Auto-inferred from Phase-1 signals by the caller (落地项 3):
    ``>= 0.85`` → high skepticism (deep challenge); ``>= 0.55`` → moderate
    (the classic frame); ``< 0.55`` → low (prioritize consensus).
    """
    if skepticism >= 0.85:
        return (
            "3. 对其他审查者的每个主张保持高度怀疑,即使表面合理也要尝试构造反例验证\n"
            "4. 仅当你在被审查内容中找到确凿证据支持时,才接受对方主张\n"
        )
    if skepticism >= 0.55:
        return (
            "3. 对其他审查者不同意的发现进行反驳,坚持你有证据的部分\n"
        )
    return (
        "3. 优先寻找与其他审查者的共识点,仅在确有证据时提出异议\n"
    )


def build_debate_system_prompt(
    persona: str, skepticism: float | None = None
) -> str:
    """System prompt for a debate round: challenge, don't capitulate.

    Two constraints (agent-review-panel HOW_WE_BUILT_THIS.md insights):
    1. Only challenge findings within your expertise (PBR principle —
       reviewers with orthogonal dimensions should not overrule each
       other's domain-specific findings).
    2. Add at least one new finding in your own dimension (New Discovery
       Requirement — prevents debate from degenerating into pure
       argumentation at the expense of discovery).

    Provenance tagging (落地项 1): every reference to another reviewer's
    claim must carry a tri-state cognitive status tag.

    Agreement intensity (落地项 3): ``skepticism`` is auto-inferred from
    Phase-1 signals by the caller — no external configuration needed.
    """
    s = skepticism if skepticism is not None else _DEFAULT_SKEPTICISM
    return (
        persona.rstrip()
        + "\n\n你现在进入辩论阶段。其他审查者的观点如下。请:\n"
        "1. 仅对你有专业判断能力的发现发表意见,挑战你不同意的部分,"
        "坚持你有证据的部分\n"
        "2. 基于其他审查者的发现,补充你维度内的新问题\n"
        + _challenge_clause(s)
        + "5. 对你引用的其他审查者的每条主张,你必须标注认知状态:\n"
        "   [✓已确认] 你在被审查内容中验证了此主张\n"
        "   [✗已反驳] 你在被审查内容中发现此主张不成立\n"
        "   [?未验证] 你无法在被审查内容中确认或反驳此主张\n"
        "6. 不带认知状态标记的引用对方观点,视为无效反驳\n"
        "7. [?未验证]的主张不得作为你调整自己severity或confidence的依据\n"
    )


def build_debate_user_prompt(content: str, others_args: str) -> str:
    """User prompt for a debate round.

    The content is labelled as the verification source so reviewers
    know to check others' claims against it (落地项 1).
    """
    return (
        f"被审查内容(请据此验证他人主张):\n{content}\n\n"
        f"其他审查者观点:\n{others_args}\n\n"
        f"你的反驳(每条引用他人主张须标注[✓已确认]/[✗已反驳]/[?未验证]):"
    )


def build_blind_final_system_prompt(persona: str) -> str:
    """System prompt for the blind final judgement."""
    return (
        persona.rstrip()
        + "\n\n辩论已结束。请基于辩论中的所有信息,给出你的最终裁决。"
    )


def build_blind_final_user_prompt(content: str, debated_position: str) -> str:
    """User prompt for the blind final judgement.

    Carries the same JSON output protocol as Phase 1 (``build_judge_prompt``):
    in agent mode the reviewer Agent sees ONLY this prompt — without the
    protocol it answers in prose and the verdict parse chain degrades to a
    failed verdict (confidence 0.0).
    """
    return (
        f"被审查内容:\n{content}\n\n"
        f"辩论后你的立场:\n{debated_position}\n\n"
        f"请给出最终裁决(严重程度/置信度/依据/建议),"
        "并用 ```json 代码块返回结构化裁决,包含:\n"
        "- severity: critical / major / minor / pass\n"
        "- confidence: 0.0-1.0\n"
        "- reasoning: 推理过程\n"
        "- findings: [{description, severity: critical/major/minor, "
        "confidence, evidence, suggestion}]\n"
        "- satisfied: bool"
    )
