"""Static Markdown roadmap builder and consistency checker.

Reads ``manifest.json`` in the roadmap directory, normalizes headings and
relative links across modular phase documents, and emits a single linear
Markdown file (e.g., ``docs/roadmap.md``). Uses only the Python standard
library so it runs identically in local environments and CI.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import posixpath
import re
import sys
from dataclasses import dataclass
from pathlib import Path

AUTO_GENERATED_BANNER = (
    "<!-- AUTO-GENERATED FILE: DO NOT EDIT DIRECTLY. "
    "Edit files under docs/roadmap/ and run `python docs/roadmap/build.py`. -->"
)

_ATX_HEADING_RE = re.compile(r"^(#{1,6})(\s+.*)$")
_FENCE_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})")
_LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")


@dataclass(frozen=True)
class SectionSpec:
    """Single source Markdown entry defined in the manifest."""

    file: str
    heading_offset: int = 0
    group: str | None = None


@dataclass(frozen=True)
class RoadmapManifest:
    """Parsed manifest describing how to assemble the linear roadmap."""

    title: str
    intro: str
    output: str
    sections: tuple[SectionSpec, ...]


def parse_manifest(manifest_path: Path) -> RoadmapManifest:
    """Load and validate ``manifest.json``."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    sections = tuple(
        SectionSpec(
            file=entry["file"],
            heading_offset=int(entry.get("heading_offset", 0)),
            group=entry.get("group"),
        )
        for entry in raw["sections"]
    )
    return RoadmapManifest(
        title=raw["title"],
        intro=raw.get("intro", ""),
        output=raw["output"],
        sections=sections,
    )


def strip_frontmatter(text: str) -> str:
    """Remove leading YAML frontmatter block if present."""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return normalized
    end_idx = normalized.find("\n---\n", 4)
    if end_idx == -1:
        return normalized
    return normalized[end_idx + 5 :].lstrip("\n")


def shift_headings(text: str, offset: int) -> str:
    """Shift ATX headings outside fenced code blocks by ``offset`` levels."""
    if offset == 0:
        return text

    out_lines: list[str] = []
    fence_char: str | None = None
    fence_len = 0

    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(2)
            if fence_char is None:
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                fence_char = None
                fence_len = 0
            out_lines.append(line)
            continue

        if fence_char is None:
            heading_match = _ATX_HEADING_RE.match(line)
            if heading_match:
                hashes, rest = heading_match.groups()
                new_level = max(1, min(6, len(hashes) + offset))
                out_lines.append(f"{'#' * new_level}{rest}")
                continue

        out_lines.append(line)

    return "\n".join(out_lines)


def _rewrite_link_target(target: str, source_dir: Path, output_dir: Path) -> str:
    """Rebase a single Markdown link target from ``source_dir`` to ``output_dir``."""
    if not target or target.startswith("#") or target.startswith(_EXTERNAL_SCHEMES):
        return target

    path_part, sep, fragment = target.partition("#")
    if not path_part:
        return target

    resolved = (source_dir / path_part).resolve()
    rel = os.path.relpath(resolved, start=output_dir.resolve())
    posix_rel = posixpath.normpath(rel.replace("\\", "/"))
    return f"{posix_rel}{sep}{fragment}" if sep else posix_rel


def _rewrite_inline_segments(line: str, source_dir: Path, output_dir: Path) -> str:
    """Rewrite Markdown links on a single line while skipping inline code spans."""
    parts = re.split(r"(`+[^`]*`+)", line)
    for idx in range(0, len(parts), 2):
        parts[idx] = _LINK_RE.sub(
            lambda m: (
                f"{m.group(1)}"
                f"{_rewrite_link_target(m.group(2), source_dir, output_dir)}"
                f"{m.group(3)}"
            ),
            parts[idx],
        )
    return "".join(parts)


def rewrite_relative_links(text: str, source_dir: Path, output_dir: Path) -> str:
    """Rewrite relative Markdown links outside fenced code blocks and inline code."""
    if source_dir.resolve() == output_dir.resolve():
        return text

    out_lines: list[str] = []
    fence_char: str | None = None
    fence_len = 0

    for line in text.split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(2)
            if fence_char is None:
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                fence_char = None
                fence_len = 0
            out_lines.append(line)
            continue

        if fence_char is None:
            out_lines.append(_rewrite_inline_segments(line, source_dir, output_dir))
        else:
            out_lines.append(line)

    return "\n".join(out_lines)


def assemble_roadmap(manifest: RoadmapManifest, base_dir: Path) -> str:
    """Assemble all source sections into a single linear Markdown document."""
    output_path = (base_dir / manifest.output).resolve()
    output_dir = output_path.parent

    blocks: list[str] = [AUTO_GENERATED_BANNER, f"# {manifest.title}"]
    if manifest.intro:
        blocks.append(manifest.intro.strip())

    current_group: str | None = None
    for spec in manifest.sections:
        source_path = (base_dir / spec.file).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Roadmap section not found: {source_path}")

        raw_text = source_path.read_text(encoding="utf-8")
        cleaned = strip_frontmatter(raw_text).strip()
        shifted = shift_headings(cleaned, spec.heading_offset)
        rebased = rewrite_relative_links(shifted, source_path.parent, output_dir)

        if spec.group and spec.group != current_group:
            blocks.append("---")
            blocks.append(f"## {spec.group}")
            current_group = spec.group
        elif spec.group is None:
            blocks.append("---")
            current_group = None
        else:
            blocks.append("---")

        blocks.append(rebased)

    return "\n\n".join(blocks).rstrip() + "\n"


def run_build(manifest_path: Path, check: bool = False) -> int:
    """Build the roadmap or verify that the existing output is up to date."""
    base_dir = manifest_path.parent
    manifest = parse_manifest(manifest_path)
    output_path = (base_dir / manifest.output).resolve()
    generated = assemble_roadmap(manifest, base_dir)

    if check:
        if not output_path.is_file():
            print(f"ERROR: Generated roadmap missing: {output_path}", file=sys.stderr)
            return 1
        existing = output_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if existing != generated:
            diff = "".join(
                difflib.unified_diff(
                    existing.splitlines(keepends=True),
                    generated.splitlines(keepends=True),
                    fromfile=str(output_path),
                    tofile="expected (generated)",
                    n=3,
                )
            )
            print(
                "ERROR: docs/roadmap.md is out of sync with docs/roadmap/. "
                "Run `uv run --no-project python docs/roadmap/build.py` to regenerate.\n"
                f"{diff}",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {output_path} is up to date.")
        return 0

    output_path.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Generated: {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble modular roadmap files into a single linear Markdown view."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("manifest.json"),
        help="Path to manifest.json (default: docs/roadmap/manifest.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the generated roadmap matches the existing output file.",
    )
    args = parser.parse_args(argv)
    return run_build(args.manifest.resolve(), check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
