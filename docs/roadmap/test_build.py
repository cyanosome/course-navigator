"""Unit tests for docs/roadmap/build.py."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402


class TestRoadmapBuilder(unittest.TestCase):
    def test_shift_headings_skips_fenced_code_blocks(self) -> None:
        src = (
            "# Title\n"
            "## Sub\n"
            "```python\n"
            "# python comment\n"
            "## not a heading\n"
            "```\n"
            "~~~\n"
            "# tilde fence comment\n"
            "~~~\n"
            "##### Deep\n"
        )
        expected = (
            "### Title\n"
            "#### Sub\n"
            "```python\n"
            "# python comment\n"
            "## not a heading\n"
            "```\n"
            "~~~\n"
            "# tilde fence comment\n"
            "~~~\n"
            "###### Deep\n"
        )
        self.assertEqual(build.shift_headings(src, 2), expected)

    def test_rewrite_relative_links_rebases_and_preserves_externals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "docs" / "roadmap"
            output_dir = root / "docs"
            source_dir.mkdir(parents=True)

            src = (
                "See [ADR](../adr/0015.md#context) and [Guide](README.md).\n"
                "Ignore [Web](https://example.com) and [Anchor](#top).\n"
                "Ignore inline `[code](../adr/0001.md)`.\n"
                "```markdown\n"
                "[fenced](../adr/0002.md)\n"
                "```\n"
            )
            rebased = build.rewrite_relative_links(src, source_dir, output_dir)
            self.assertIn("[ADR](adr/0015.md#context)", rebased)
            self.assertIn("[Guide](roadmap/README.md)", rebased)
            self.assertIn("[Web](https://example.com)", rebased)
            self.assertIn("[Anchor](#top)", rebased)
            self.assertIn("`[code](../adr/0001.md)`", rebased)
            self.assertIn("[fenced](../adr/0002.md)", rebased)

    def test_run_build_and_check_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roadmap_dir = root / "docs" / "roadmap"
            roadmap_dir.mkdir(parents=True)
            (roadmap_dir / "01-a.md").write_text("# Phase A\n\nBody\n", encoding="utf-8")

            manifest = {
                "title": "Test Roadmap",
                "intro": "Intro text",
                "output": "../roadmap.md",
                "sections": [
                    {"file": "01-a.md", "heading_offset": 2, "group": "1. Group"}
                ],
            }
            manifest_path = roadmap_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            # Missing output -> check fails
            self.assertEqual(build.run_build(manifest_path, check=True), 1)
            # Generate -> check passes
            self.assertEqual(build.run_build(manifest_path, check=False), 0)
            self.assertEqual(build.run_build(manifest_path, check=True), 0)

            out_text = (root / "docs" / "roadmap.md").read_text(encoding="utf-8")
            self.assertIn("## 1. Group", out_text)
            self.assertIn("### Phase A", out_text)

            # Modify source -> check fails
            (roadmap_dir / "01-a.md").write_text("# Phase A\n\nUpdated\n", encoding="utf-8")
            self.assertEqual(build.run_build(manifest_path, check=True), 1)


if __name__ == "__main__":
    unittest.main()
