"""Validate repository-local links in Markdown documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", ".venv", "build", "dist"}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def markdown_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.md")
        if not any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in path.parts)
    ]


def local_target(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    path_part = unquote(target.split("#", maxsplit=1)[0])
    return (document.parent / path_part).resolve()


def main() -> int:
    missing: list[str] = []
    for document in markdown_files(PROJECT_ROOT):
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = local_target(document, raw_target)
            if target is not None and not target.exists():
                relative_document = document.relative_to(PROJECT_ROOT)
                missing.append(f"{relative_document}: missing {raw_target}")
    if missing:
        print("Documentation link check failed:", file=sys.stderr)
        for finding in missing:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Documentation link check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
