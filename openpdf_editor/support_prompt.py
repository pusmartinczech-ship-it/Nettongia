from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


SUPPORT_URL = "https://buy.stripe.com/dRm00ca0yeYK1am9ix7ss00"
FIRST_PROMPT_SAVE_COUNT = 5
REMINDER_SAVE_INTERVAL = 10
MAX_SAVE_COUNT = 1_000_000


@dataclass(frozen=True)
class SupportPromptState:
    successful_saves: int
    next_prompt_at: int
    disabled: bool


def _bounded_int(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(MAX_SAVE_COUNT, number))


def _setting_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def read_support_prompt_state(settings: QSettings) -> SupportPromptState:
    saves = _bounded_int(settings.value("support/successful_saves", 0), 0)
    threshold = _bounded_int(
        settings.value("support/next_prompt_at", FIRST_PROMPT_SAVE_COUNT),
        FIRST_PROMPT_SAVE_COUNT,
    )
    threshold = max(FIRST_PROMPT_SAVE_COUNT, threshold)
    disabled = _setting_bool(settings.value("support/disabled", False))
    return SupportPromptState(saves, threshold, disabled)


def record_successful_save(settings: QSettings) -> tuple[SupportPromptState, bool]:
    """Record one normal save and reserve a due prompt at most once."""

    state = read_support_prompt_state(settings)
    saves = min(MAX_SAVE_COUNT, state.successful_saves + 1)
    settings.setValue("support/successful_saves", saves)
    due = not state.disabled and saves >= state.next_prompt_at
    next_prompt = state.next_prompt_at
    if due:
        # Reserve the next interval before showing UI. A crash or forced close
        # can therefore never cause the prompt to reappear on the next start.
        next_prompt = min(MAX_SAVE_COUNT, saves + REMINDER_SAVE_INTERVAL)
        settings.setValue("support/next_prompt_at", next_prompt)
    return SupportPromptState(saves, next_prompt, state.disabled), due


def disable_support_prompt(settings: QSettings) -> None:
    settings.setValue("support/disabled", True)
