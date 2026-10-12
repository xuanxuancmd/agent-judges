import logging
from typing import Union

import tiktoken

logger = logging.getLogger(__name__)


def _resolve_encoding(model: Union[str, None] = None):
    """Resolve the tiktoken encoding for ``model`` (cl100k_base fallback)."""
    if model is not None:
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base (used by gpt-4) if model not found
            logger.warning(
                "Model %s not found in tiktoken. Using cl100k_base encoding instead.",
                model,
            )
            return tiktoken.get_encoding("cl100k_base")
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: Union[str, None], model: Union[str, None] = None) -> int:
    """Exact token count for ``text`` via the same encoding truncate_string uses.

    Deterministic length signal for the progressive flow's start rule —
    never ask an LLM to measure what tiktoken already knows.
    """
    if not text:
        return 0
    encoding = _resolve_encoding(model)
    return len(encoding.encode(text, disallowed_special=()))


def truncate_string(
    info_string: Union[str, None],
    model: Union[str, None] = None,
    max_tokens: int = 10000,
    drop_mode: str = "middle",
) -> str:
    """Truncate a string to at most ``max_tokens`` tokens (AaaJ-preserved util)."""

    if info_string is None:
        logger.warning(
            "Received None input for truncation. Returning an empty string."
        )
        return ""

    info_string = str(info_string)

    encoding = _resolve_encoding(model)
    tokens = encoding.encode(info_string, disallowed_special=())

    # If tokens exceed the maximum length, we truncate based on the drop_mode
    if len(tokens) > max_tokens:
        # logging.warning(f"Input string exceeds maximum token limit ({max_tokens}). Truncating using {drop_mode} mode.")
        ellipsis = encoding.encode("...")
        ellipsis_len = len(ellipsis)

        if drop_mode == "head":
            tokens = ellipsis + tokens[-(max_tokens - ellipsis_len) :]
        elif drop_mode == "middle":
            head_tokens = (max_tokens - ellipsis_len) // 2
            tail_tokens = max_tokens - head_tokens - ellipsis_len
            tokens = tokens[:head_tokens] + ellipsis + tokens[-tail_tokens:]
        elif drop_mode == "tail":
            tokens = tokens[: (max_tokens - ellipsis_len)] + ellipsis

        else:
            raise ValueError(
                f"Unknown drop_mode: {drop_mode}. Supported modes: 'head', 'middle', 'tail'."
            )

    return encoding.decode(tokens)
