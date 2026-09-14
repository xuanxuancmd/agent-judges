"""Generic judge user prompt (accepts arbitrary content + checklist).

AaaJ's ``prompt_judge`` generalized away from code generation; uses
structured tags (# 被审查内容 / # 检查清单 / # 背景上下文 / # 输出要求)
borrowed from the ``system_prompt_retrieve`` pattern.
"""

from typing import Iterable

__all__ = ["build_judge_prompt"]

_OUTPUT_REQUIREMENTS = """# 输出要求
请用 ```json 代码块返回结构化裁决,包含:
- severity: critical / major / minor / pass
- confidence: 0.0-1.0
- reasoning: 推理过程
- findings: [{description, severity: critical/major/minor, confidence, evidence, suggestion}]
- satisfied: bool"""


def build_judge_prompt(
    content: str,
    checklist: Iterable,
    context: str | None = None,
) -> str:
    """Build the Phase-1 independent-review user prompt."""
    checklist_text = "\n".join(f"  - {c.criteria}" for c in checklist)
    parts = [
        f"# 被审查内容\n{content}",
        f"\n# 检查清单\n{checklist_text}",
    ]
    if context:
        parts.append(f"\n# 背景上下文\n{context}")
    parts.append(f"\n{_OUTPUT_REQUIREMENTS}")
    return "\n".join(parts)
