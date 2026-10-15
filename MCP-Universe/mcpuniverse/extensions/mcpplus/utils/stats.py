"""
Utility functions and classes for postprocessor agents.
"""
from dataclasses import dataclass
import tiktoken


@dataclass
class PostProcessStats:
    """
    Statistics from post-processing operation.

    Attributes:
        postprocessor_iterations: Number of iterations performed.
        original_chars: Character count of original output.
        filtered_chars: Character count of filtered output.
        chars_reduced: Number of characters reduced.
        original_tokens: Token count of original output.
        filtered_tokens: Token count of filtered output.
        tokens_reduced: Number of tokens reduced.
        success: Whether post-processing succeeded.
    """
    postprocessor_iterations: int
    original_chars: int
    filtered_chars: int
    chars_reduced: int
    original_tokens: int
    filtered_tokens: int
    tokens_reduced: int
    success: bool


def count_tokens(text: str, model: str = "gpt-4") -> int:
    """
    Count tokens in text using tiktoken.

    Args:
        text: Text to count tokens for.
        model: Model name for tokenizer selection.

    Returns:
        Number of tokens.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        # Fallback to cl100k_base (used by gpt-4, gpt-3.5-turbo)
        encoding = tiktoken.get_encoding("cl100k_base")

    return len(encoding.encode(text))
