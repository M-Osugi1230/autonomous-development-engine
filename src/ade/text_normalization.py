"""Text normalization utility module."""

from typing import Optional
import unittest


def normalize_text(text: Optional[str]) -> str:
    """Trim surrounding whitespace and collapse internal whitespace.

    Returns an empty string if input is None, empty, or whitespace-only.
    The function is pure and deterministic.
    """
    if not text:
        return ""
    return " ".join(text.split())


class TextNormalizationTests(unittest.TestCase):
    """Focused tests for normalize_text utility."""

    def test_empty_and_none_input_returns_empty_string(self) -> None:
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")

    def test_whitespace_only_input_returns_empty_string(self) -> None:
        self.assertEqual(normalize_text("   "), "")
        self.assertEqual(normalize_text("\t\n\r "), "")

    def test_trims_surrounding_whitespace(self) -> None:
        self.assertEqual(normalize_text("  hello  "), "hello")
        self.assertEqual(normalize_text("\n\ttest\n"), "test")

    def test_collapses_internal_whitespace(self) -> None:
        self.assertEqual(normalize_text("hello   world"), "hello world")
        self.assertEqual(normalize_text("hello \t\n world"), "hello world")
        self.assertEqual(
            normalize_text("  multiple   spaces   and\t\nnewlines  "),
            "multiple spaces and newlines",
        )

    def test_already_normalized_text_remains_unchanged(self) -> None:
        self.assertEqual(normalize_text("hello world"), "hello world")

    def test_pure_and_deterministic(self) -> None:
        input_str = "   foo   bar   baz  "
        first_call = normalize_text(input_str)
        second_call = normalize_text(input_str)
        self.assertEqual(first_call, "foo bar baz")
        self.assertEqual(first_call, second_call)


if __name__ == "__main__":
    unittest.main()
