"""Compatibility entrypoint for the previous angle-diagnostic model."""

from __future__ import annotations

from .dynamic import (
    DynamicCaseInput,
    TimeHistoryFrame,
    TimeHistoryFramePoint,
    TimeHistoryPoint,
    TimeHistoryResult,
    get_time_history_case,
    list_time_history_cases,
    solve_time_history,
    solve_time_history_input,
)

__all__ = [
    "DynamicCaseInput",
    "TimeHistoryFrame",
    "TimeHistoryFramePoint",
    "TimeHistoryPoint",
    "TimeHistoryResult",
    "get_time_history_case",
    "list_time_history_cases",
    "solve_time_history",
    "solve_time_history_input",
]
