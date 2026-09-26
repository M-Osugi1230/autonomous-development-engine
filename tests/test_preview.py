from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ade import PreviewKind, PreviewManifest, PreviewStore


class PreviewManifestTests(unittest.TestCase):
    def make_preview(self, **overrides):
        values = {
            "preview_id": "preview-1",
            "kind": PreviewKind.PULL_REQUEST,
            "title": "Review PR #33",
            "url": "https://github.com/M-Osugi1230/autonomous-development-engine/pull/33",
            "task_id": "vertical-slice-027",
            "updated_at": "2026-09-26T01:35:00+00:00",
        }
        values.update(overrides)
        return PreviewManifest(**values)

    def test_round_trip(self) -> None:
        preview = self.make_preview()
        self.assertEqual(PreviewManifest.from_dict(preview.to_dict()), preview)

    def test_rejects_non_https_credentials_query_fragment_and_unknown_host(self) -> None:
        invalid_urls = (
            "http://github.com/M-Osugi1230/autonomous-development-engine/pull/33",
            "https://user:pass@github.com/M-Osugi1230/autonomous-development-engine/pull/33",
            "https://github.com/M-Osugi1230/autonomous-development-engine/pull/33?token=x",
            "https://github.com/M-Osugi1230/autonomous-development-engine/pull/33#fragment",
            "https://example.com/preview/33",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.make_preview(url=url)

    def test_rejects_naive_timestamp_and_secret_like_text(self) -> None:
        with self.assertRaises(ValueError):
            self.make_preview(updated_at="2026-09-26T01:35:00")
        with self.assertRaises(ValueError):
            self.make_preview(
                title="ghp_123456789012345678901234567890123456"
            )


class PreviewStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "nested" / "preview.json"
        self.store = PreviewStore(self.path)
        self.preview = PreviewManifest(
            preview_id="preview-1",
            kind=PreviewKind.ACTION_ARTIFACT,
            title="Mission Control artifact",
            url="https://github.com/M-Osugi1230/autonomous-development-engine/actions/runs/36208419018",
            task_id="vertical-slice-026",
            updated_at="2026-09-26T01:35:00+00:00",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_missing_store_is_none_and_round_trip(self) -> None:
        self.assertIsNone(self.store.load())
        self.store.save(self.preview)
        self.assertEqual(self.store.load(), self.preview)

    def test_clear_is_explicit_null_and_atomic(self) -> None:
        self.store.save(self.preview)
        self.store.save(None)
        self.assertIsNone(self.store.load())
        self.assertEqual(list(self.path.parent.glob(".*.tmp")), [])

    def test_invalid_json_and_schema_are_rejected(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{bad-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.load()

        self.path.write_text(
            '{"schema_version":2,"preview":null}',
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.store.load()


if __name__ == "__main__":
    unittest.main()
