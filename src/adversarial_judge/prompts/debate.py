"""Debate-round and blind-final prompt builders (Phase 2 / Phase 3)."""

__all__ = [
    "build_debate_system_prompt",
    "build_debate_user_prompt",
    "build_blind_final_system_prompt",
    "build_blind_final_user_prompt",
]


def build_debate_system_prompt(persona: str) -> str:
    """System prompt for a debate round: challenge, don't capitulate.

    Two constraints (agent-review-panel HOW_WE_BUILT_THIS.md insights):
    1. Only challenge findings within your expertise (PBR principle —
       reviewers with orthogonal dimensions should not overrule each
       other's domain-specific findings).
    2. Add at least one new finding in your own dimension (New Discovery
       Requirement — prevents debate from degenerating into pure
       argumentation at the expense of discovery).
    """
    return (
        persona.rstrip()
        + "\n\n你现在进入辩论阶段。其他审查者的观点如下。请:\n"
        "1. 仅对你有专业判断能力的发现发表意见,挑战你不同意的部分,"
        "坚持你有证据的部分\n"
        "2. 基于其他审查者的发现,补充你维度内的新问题\n"
    )


def build_debate_user_prompt(content: str, others_args: str) -> str:
    """User prompt for a debate round."""
    return (
        f"被审查内容:\n{content}\n\n"
        f"其他审查者观点:\n{others_args}\n\n"
        f"你的反驳:"
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
