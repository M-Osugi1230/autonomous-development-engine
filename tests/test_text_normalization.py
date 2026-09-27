"""Focused stdlib unit tests for normalize_text text normalization utility."""

import unittest

from ade.text_normalization import normalize_text


class TextNormalizationTests(unittest.TestCase):
    """Focused stdlib unit tests for normalize_text covering required cases."""

    def test_normal_input(self) -> None:
        """Test normalization of normal strings with standard single spacing."""
        self.assertEqual(normalize_text("hello world"), "hello world")
        self.assertEqual(normalize_text("  hello world  "), "hello world")

    def test_repeated_whitespace(self) -> None:
        """Test collapsing of repeated spaces and tabs within strings."""
        self.assertEqual(normalize_text("hello   world"), "hello world")
        self.assertEqual(
            normalize_text("  multiple   spaces   and   tabs\t\t "),
            "multiple spaces and tabs",
        )

    def test_newline_input(self) -> None:
        """Test handling of single and multiple newlines (leading, trailing, and internal)."""
        self.assertEqual(normalize_text("\nhello\nworld\n"), "hello world")
        self.assertEqual(normalize_text("hello\r\nworld"), "hello world")
        self.assertEqual(normalize_text("\n\ttest\n\nline\r\n"), "test line")

    def test_empty_input(self) -> None:
        """Test empty string, None, and whitespace-only inputs return empty string."""
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text("   "), "")
        self.assertEqual(normalize_text("\n\t\r "), "")


if __name__ == "__main__":
    unittest.main()
