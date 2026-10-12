"""Prompt builders for the judge/debate pipeline.

- ``judge_system``: anonymous-slot system prompt wrapping the persona
  (AaaJ's ``system_prompt_judge`` generalized away from code generation)
- ``judge_user``: structured user prompt (content / checklist / context /
  output requirements — structured-tag + focus/exclude prompt engineering
  borrowed from AaaJ's ``system_prompt_retrieve`` pattern)
- ``debate``: debate-round and blind-final prompts
"""

from .judge_system import build_system_prompt
from .judge_user import build_judge_prompt
from .debate import (
    build_debate_system_prompt,
    build_debate_user_prompt,
    build_blind_final_system_prompt,
    build_blind_final_user_prompt,
)

__all__ = [
    "build_system_prompt",
    "build_judge_prompt",
    "build_debate_system_prompt",
    "build_debate_user_prompt",
    "build_blind_final_system_prompt",
    "build_blind_final_user_prompt",
]
