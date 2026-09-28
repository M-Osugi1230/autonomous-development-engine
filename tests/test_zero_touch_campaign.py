"""Focused stdlib unit tests for zero_touch_campaign_marker utility."""

import unittest

from ade.zero_touch_campaign import zero_touch_campaign_marker


class TestZeroTouchCampaignMarker(unittest.TestCase):
    """Focused stdlib unit tests for zero_touch_campaign_marker."""

    def test_valid_deterministic_output(self) -> None:
        """Test valid deterministic output and whitespace stripping for campaign_id and mode."""
        res1 = zero_touch_campaign_marker("camp-123", "auto")
        self.assertEqual(
            res1,
            {"campaign_id": "camp-123", "mode": "auto", "started": True},
        )

        res2 = zero_touch_campaign_marker("  camp-456  ", "  manual  ", started=False)
        self.assertEqual(
            res2,
            {"campaign_id": "camp-456", "mode": "manual", "started": False},
        )

    def test_marker_purity(self) -> None:
        """Test that returned dictionary is a new instance each time."""
        res1 = zero_touch_campaign_marker("camp-123", "auto")
        res2 = zero_touch_campaign_marker("camp-123", "auto")
        self.assertEqual(res1, res2)
        self.assertIsNot(res1, res2)

    def test_invalid_campaign_id(self) -> None:
        """Test invalid campaign_id inputs raise ValueError or TypeError."""
        for invalid_val in ("", "   ", "\t\n "):
            with self.assertRaises(ValueError):
                zero_touch_campaign_marker(invalid_val, "auto")  # type: ignore[arg-type]

        for invalid_type in (None, 123, 45.6, [], {}):
            with self.assertRaises(TypeError):
                zero_touch_campaign_marker(invalid_type, "auto")  # type: ignore[arg-type]

    def test_invalid_mode(self) -> None:
        """Test invalid mode inputs raise ValueError or TypeError."""
        for invalid_val in ("", "   ", "\t\n "):
            with self.assertRaises(ValueError):
                zero_touch_campaign_marker("camp-123", invalid_val)  # type: ignore[arg-type]

        for invalid_type in (None, 123, 45.6, [], {}):
            with self.assertRaises(TypeError):
                zero_touch_campaign_marker("camp-123", invalid_type)  # type: ignore[arg-type]

    def test_invalid_started(self) -> None:
        """Test invalid started inputs raise TypeError."""
        for invalid_type in ("True", "False", 1, 0, None, [], {}):
            with self.assertRaises(TypeError):
                zero_touch_campaign_marker("camp-123", "auto", started=invalid_type)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
