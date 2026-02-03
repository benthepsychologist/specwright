"""Resolver for check prompts within epic directories."""

from pathlib import Path

from spec.core.exceptions import SpecwrightError


class PromptNotFoundError(SpecwrightError):
    """Prompt file not found in epic directory."""

    exit_code = 2


def resolve_prompt(prompt_ref: str, epic_path: Path) -> str:
    """Read prompt file from epic directory.

    Args:
        prompt_ref: Relative path to prompt file within epic directory.
        epic_path: Path to the epic directory.

    Returns:
        Markdown content of the prompt file.

    Raises:
        PromptNotFoundError: If the prompt file does not exist.
    """
    prompt_path = epic_path / prompt_ref

    if not prompt_path.exists():
        raise PromptNotFoundError(
            f"Prompt file not found: {prompt_path}"
        )

    return prompt_path.read_text()
