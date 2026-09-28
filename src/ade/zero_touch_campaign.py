from __future__ import annotations

from typing import Any


def zero_touch_campaign_marker(
    campaign_id: str,
    mode: str,
    started: bool = True,
) -> dict[str, Any]:
    """Return a deterministic zero-touch campaign marker dictionary.

    Args:
        campaign_id: A non-empty string identifying the campaign.
        mode: A non-empty string representing the campaign mode.
        started: A boolean flag indicating whether the campaign has started.

    Returns:
        A dictionary containing campaign_id, mode, and started.

    Raises:
        TypeError: If arguments are not of expected types.
        ValueError: If campaign_id or mode is empty or whitespace-only.
    """
    if not isinstance(campaign_id, str):
        raise TypeError(f"campaign_id must be a str, got {type(campaign_id).__name__}")
    cleaned_campaign_id = campaign_id.strip()
    if not cleaned_campaign_id:
        raise ValueError("campaign_id must not be empty")

    if not isinstance(mode, str):
        raise TypeError(f"mode must be a str, got {type(mode).__name__}")
    cleaned_mode = mode.strip()
    if not cleaned_mode:
        raise ValueError("mode must not be empty")

    if not isinstance(started, bool):
        raise TypeError(f"started must be a bool, got {type(started).__name__}")

    return {
        "campaign_id": cleaned_campaign_id,
        "mode": cleaned_mode,
        "started": started,
    }


def _run_inline_tests() -> None:
    # Deterministic dictionary check
    res1 = zero_touch_campaign_marker("camp-123", "auto")
    assert res1 == {"campaign_id": "camp-123", "mode": "auto", "started": True}, f"Unexpected: {res1}"

    res2 = zero_touch_campaign_marker("camp-123", "manual", started=False)
    assert res2 == {"campaign_id": "camp-123", "mode": "manual", "started": False}, f"Unexpected: {res2}"

    # Purity check (returns new dict each time)
    assert res1 is not zero_touch_campaign_marker("camp-123", "auto")

    # Rejection of empty campaign_id
    for invalid in ("", "   ", None, 123):
        try:
            zero_touch_campaign_marker(invalid, "auto")  # type: ignore[arg-type]
            raise AssertionError(f"Expected failure for campaign_id={invalid!r}")
        except (ValueError, TypeError):
            pass

    # Rejection of empty mode
    for invalid in ("", "   ", None, 123):
        try:
            zero_touch_campaign_marker("camp-123", invalid)  # type: ignore[arg-type]
            raise AssertionError(f"Expected failure for mode={invalid!r}")
        except (ValueError, TypeError):
            pass

    # Rejection of non-bool started
    for invalid in ("True", 1, 0, None, []):
        try:
            zero_touch_campaign_marker("camp-123", "auto", started=invalid)  # type: ignore[arg-type]
            raise AssertionError(f"Expected failure for started={invalid!r}")
        except TypeError:
            pass

    print("All inline zero_touch_campaign tests passed successfully.")


if __name__ == "__main__":
    _run_inline_tests()
