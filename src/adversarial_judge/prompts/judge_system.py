"""Generic judge system prompt (AaaJ ``system_prompt_judge`` generalized).

The anonymous-slot frame (design.md 1.6): the system controls the behaviour
contract; the user template only injects the review perspective (persona).

Reasoning-strategy injection (落地项 2): when a reviewer declares a
``reasoning_strategy`` in its frontmatter, the corresponding strategy
guidance is injected between the persona and the judge frame. DMAD
(ICLR 2025) shows that different reasoning methods per agent outperform
different personas alone — this breaks the "fixed mental set" where all
reviewers share the same cognitive path.
"""

__all__ = ["build_system_prompt"]

#: Reasoning-strategy guidance text keyed by strategy name.
#: ``None`` or unknown strategy → no injection (defaults to checklist).
_REASONING_STRATEGIES: dict[str, str] = {
    "checklist": (
        "\n\n[推理策略 — checklist]\n"
        "逐条对照检查清单,对每条不符合的输出发现。这是默认策略。"
    ),
    "inverse": (
        "\n\n[推理策略 — inverse]\n"
        "对每个条目,先假设它是必要的,然后尝试构造一个场景使得"
        "删除它后文档仍然自洽。如果成功,标记该条目为'可能冗余'。"
    ),
    "transform": (
        "\n\n[推理策略 — transform]\n"
        "将文档的核心主张转换为你擅长领域的另一种表示"
        "(如:将需求列表转为依赖图/状态机/数据流图),"
        "检查转换后的结构是否暴露原始文本中不可见的问题"
        "(如循环依赖、缺失节点)。"
    ),
    "counterfactual": (
        "\n\n[推理策略 — counterfactual]\n"
        "对每个关键设计决策,假设它不存在或被替换为相反决策,"
        "推演系统行为。如果行为合理,标记该决策为'可能过度设计';"
        "如果行为不合理,确认该决策的必要性。"
    ),
    "falsification": (
        "\n\n[推理策略 — falsification]\n"
        "对文档中的每个声明,主动构造一个反例来推翻它。"
        "如果反例成立,标记该声明为'存在边界失效'。"
    ),
}

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


def build_system_prompt(persona: str, reasoning_strategy: str | None = None) -> str:
    """Combine a reviewer persona with the system-controlled judge frame.

    When ``reasoning_strategy`` is provided and recognized, the
    corresponding strategy guidance is injected between the persona
    and the judge frame (落地项 2). Unknown or ``None`` strategies
    default to no injection (the persona itself acts as the implicit
    checklist strategy).
    """
    strategy = _REASONING_STRATEGIES.get(reasoning_strategy or "", "")
    return persona.rstrip() + strategy + _JUDGE_FRAME
