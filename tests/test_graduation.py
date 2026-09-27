"""Focused stdlib unit tests for graduation_metadata helper."""

import unittest

from ade.graduation import graduation_metadata


class GraduationMetadataTests(unittest.TestCase):
    """Focused stdlib unit tests covering deterministic summary and invalid input handling."""

    def test_valid_graduation_metadata_default_phase_count(self) -> None:
        """Test graduation_metadata returns deterministic dict with default phase count."""
        result = graduation_metadata("1.0.0", "GRADUATED")
        expected = {
            "version": "1.0.0",
            "status": "GRADUATED",
            "completed_phase_count": 17,
        }
        self.assertEqual(result, expected)

    def test_valid_graduation_metadata_custom_phase_count_and_whitespace(self) -> None:
        """Test graduation_metadata trims whitespace and accepts non-negative phase counts."""
        result = graduation_metadata("  2.0.0-rc1  ", "  IN_PROGRESS  ", completed_phase_count=0)
        expected = {
            "version": "2.0.0-rc1",
            "status": "IN_PROGRESS",
            "completed_phase_count": 0,
        }
        self.assertEqual(result, expected)

    def test_invalid_version_raises_value_error(self) -> None:
        """Test invalid version values raise ValueError."""
        invalid_versions = ["", "   ", "\t\n", None, 123, []]
        for version in invalid_versions:
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    graduation_metadata(version, "GRADUATED")  # type: ignore[arg-type]

    def test_invalid_status_raises_value_error(self) -> None:
        """Test invalid status values raise ValueError."""
        invalid_statuses = ["", "   ", "\n", None, 456, True]
        for status in invalid_statuses:
            with self.subTest(status=status):
                with self.assertRaises(ValueError):
                    graduation_metadata("1.0.0", status)  # type: ignore[arg-type]

    def test_invalid_completed_phase_count_raises_value_error(self) -> None:
        """Test invalid completed_phase_count values raise ValueError."""
        invalid_counts = [-1, -10, True, False, "17", 17.0, None]
        for count in invalid_counts:
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    graduation_metadata("1.0.0", "GRADUATED", completed_phase_count=count)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
