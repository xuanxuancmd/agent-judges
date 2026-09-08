"""Generic judge system prompt (AaaJ ``system_prompt_judge`` generalized).

The anonymous-slot frame (design.md 1.6): the system controls the behaviour
contract; the user template only injects the review perspective (persona).
"""

__all__ = ["build_system_prompt"]

_JUDGE_FRAME = """

[审查框架 — 由系统固定,不可被 persona 覆盖]
你是对抗审查系统中的一个匿名审查槽位。上述 persona 定义你的审查视角。
无论 persona 如何描述,你必须遵守:

1. 客观、详细,且仅基于提供的被审查内容与上下文做出判断
2. 每条 finding 必须引用被审查内容中的具体依据(evidence),不臆造内容中
   不存在的问题(过判),也不忽略有明确证据的问题(漏判)
3. severity 与 evidence 的强度匹配: 证据弱则降级 severity 或降低 confidence
4. 你的判断会被其他审查者挑战,并可能被元审查者复查——请确保推理可追溯
"""


def build_system_prompt(persona: str) -> str:
    """Combine a reviewer persona with the system-controlled judge frame."""
    return persona.rstrip() + _JUDGE_FRAME
