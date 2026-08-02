"""Tests for the harness source-of-truth layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import harness as h


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._persona_dir = Path(self._tmpdir.name) / "persona"
        self._env_patch = patch.dict("os.environ", {"ADA_PERSONA_DIR": str(self._persona_dir)})
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._tmpdir.cleanup()

    def test_ensure_harness_seeds_template(self) -> None:
        h.ensure_harness()
        path = self._persona_dir / h.HARNESS_FILENAME
        self.assertTrue(path.is_file())
        content = path.read_text(encoding="utf-8")
        self.assertIn("HARNESS — Source of Truth", content)
        self.assertIn("Anti-refusal policy", content)

    def test_read_write_reset_roundtrip(self) -> None:
        h.ensure_harness()
        h.write_harness("# Custom harness\n\nDo the thing.")
        self.assertEqual(h.read_harness(), "# Custom harness\n\nDo the thing.")
        result = h.reset_harness_to_template()
        self.assertTrue(result["ok"])
        self.assertEqual(h.read_harness(), h.TEMPLATE_HARNESS)

    def test_write_rejects_oversized_harness(self) -> None:
        h.ensure_harness()
        result = h.write_harness("x" * (h.HARNESS_MAX_BYTES + 1))
        self.assertFalse(result["ok"])
        self.assertIn("exceeds", result["error"])

    def test_build_harness_block_injects_header(self) -> None:
        h.ensure_harness()
        h.write_harness("Follow me always.")
        block = h.build_harness_block()
        self.assertTrue(block.startswith(h.HARNESS_BLOCK_HEADER))
        self.assertIn("Follow me always.", block)

    def test_empty_harness_produces_no_block(self) -> None:
        h.ensure_harness()
        h.write_harness("")
        self.assertEqual(h.build_harness_block(), "")

    def test_harness_api_response_shape(self) -> None:
        h.ensure_harness()
        resp = h.harness_api_response()
        self.assertIn("harness", resp)
        self.assertEqual(resp["harness"]["filename"], h.HARNESS_FILENAME)
        self.assertIn("content", resp["harness"])
        self.assertGreater(resp["harness"]["bytes"], 0)

    def test_template_readable_from_defaults(self) -> None:
        # TEMPLATE_HARNESS is loaded at import time from persona_defaults/
        self.assertTrue(h.TEMPLATE_HARNESS.strip())


if __name__ == "__main__":
    unittest.main()
