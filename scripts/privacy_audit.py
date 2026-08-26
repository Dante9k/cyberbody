"""Fail when repository files contain high-confidence secrets or personal paths."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".example",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".spec",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
PLACEHOLDER_MARKERS = ("example", "fake", "placeholder", "redacted", "test")

SECRET_PATTERNS = {
    "OpenAI API key": re.compile(r"\b" + "s" + r"k-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "AWS access key": re.compile(r"\bA" + r"KIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "hard-coded API key": re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*['\"]([^'\"]{12,})['\"]"),
}
PERSONAL_PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:\\Users\\|/Users/|/home/)([^\\/\s]+)")


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.name == Path(__file__).name or ".egg-info" in path.as_posix():
            continue
        if path.suffix.casefold() in TEXT_SUFFIXES or path.name in {
            ".editorconfig",
            ".env.example",
            ".gitattributes",
            ".gitignore",
            "LICENSE",
        }:
            files.append(path)
    return files


def audit_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        lowered = line.casefold()
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(line) and not any(
                marker in lowered for marker in PLACEHOLDER_MARKERS
            ):
                findings.append(f"{path}:{line_number}: possible {label}")
        match = PERSONAL_PATH_PATTERN.search(line)
        if match and match.group(1).casefold() not in {"username", "user", "name"}:
            findings.append(f"{path}:{line_number}: possible personal home path")
    return findings


def main() -> int:
    findings = [finding for path in iter_text_files(PROJECT_ROOT) for finding in audit_file(path)]
    if findings:
        print("Privacy audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Privacy audit passed: no high-confidence secrets or personal paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
