"""Debate-round and blind-final prompt builders (Phase 2 / Phase 3)."""

__all__ = [
    "build_debate_system_prompt",
    "build_debate_user_prompt",
    "build_blind_final_system_prompt",
    "build_blind_final_user_prompt",
]


def build_debate_system_prompt(persona: str) -> str:
    """System prompt for a debate round: challenge, don't capitulate."""
    return (
        persona.rstrip()
        + "\n\n你现在进入辩论阶段。其他审查者的观点如下,"
        "请挑战你不同意的部分,坚持你有证据的部分:\n"
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
    """User prompt for the blind final judgement."""
    return (
        f"被审查内容:\n{content}\n\n"
        f"辩论后你的立场:\n{debated_position}\n\n"
        f"请给出最终裁决(严重程度/置信度/依据/建议):"
    )
