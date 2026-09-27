"""Graduation metadata utility for ADE v1.0.

Provides pure functions to represent and validate production graduation metadata.
"""

from __future__ import annotations

from typing import Any


def graduation_metadata(
    version: str,
    status: str,
    completed_phase_count: int = 17,
) -> dict[str, Any]:
    """Return a deterministic dictionary containing graduation metadata.

    Args:
        version: Non-empty release or version string (e.g. "1.0.0").
        status: Non-empty status string (e.g. "GRADUATED").
        completed_phase_count: Non-negative integer representing completed phase count.

    Returns:
        A dictionary with keys 'version', 'status', and 'completed_phase_count'.

    Raises:
        ValueError: If version or status is empty or whitespace-only, or if types/counts are invalid.
    """
    if not isinstance(version, str) or not version.strip():
        raise ValueError("version must be a non-empty string")

    if not isinstance(status, str) or not status.strip():
        raise ValueError("status must be a non-empty string")

    if isinstance(completed_phase_count, bool) or not isinstance(completed_phase_count, int) or completed_phase_count < 0:
        raise ValueError("completed_phase_count must be a non-negative integer")

    return {
        "version": version.strip(),
        "status": status.strip(),
        "completed_phase_count": completed_phase_count,
    }
