#!/usr/bin/env python3
"""Audit a public source tree or its Git history without printing file contents."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RULE_BANNED = "banned-file"
RULE_SECRET = "possible-secret"

_SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|passwd|secret|token)\b"
        r"\s*[:=]\s*(?:\"([A-Za-z0-9/+_.=-]{12,})\"|'([A-Za-z0-9/+_.=-]{12,})')"
    ),
)
_PLACEHOLDER = re.compile(
    r"(?i)^(?:$|<[^>]+>|\$\{[^}]+\}|your[-_ ]|replace[-_ ]|change[-_ ]|"
    r"example|sample|dummy|placeholder|none$|null$|false$|todo$|xxx+$)"
)
_TEXT_SUFFIXES = {
    ".py",
    ".pyi",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".md",
    ".txt",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".sh",
    ".ps1",
    ".bat",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".sql",
    ".xml",
    ".cff",
    ".example",
    ".sample",
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str
    commit: str = ""
    object_id: str = ""


def _is_banned(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    parts = normalized.split("/")
    if name.startswith(".env") and name not in {".env.example", ".env.sample"}:
        return True
    if any(
        part in {".git", ".worktrees", "worktrees", "node_modules", ".venv", "venv"}
        for part in parts
    ):
        return True
    if "__pycache__" in parts or name.endswith((".pyc", ".pyo", ".log")):
        return True
    if name.endswith(".ipynb"):
        return True
    if name == "all_messages.txt" or (name.startswith("all_messages_") and name.endswith(".txt")):
        return True
    return any(
        part in {"data", "datasets", "eval", "logs", "private", "private-data", "private_data"}
        for part in parts
    )


def _secret_found(content: bytes) -> bool:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    for pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            candidate = next((group for group in match.groups() if group), match.group(0))
            if pattern is _SECRET_PATTERNS[-1] and _PLACEHOLDER.match(candidate):
                continue
            return True
    return False


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def _git_with_input(root: Path, input_bytes: bytes, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def scan_working_tree(root: Path, export: bool = False) -> list[Finding]:
    if export:
        paths = _export_paths(root)
    else:
        listed = _git(root, "ls-files", "-z").decode("utf-8").split("\0")
        paths = (root / item for item in listed if item)
    findings: list[Finding] = []
    for file_path in paths:
        try:
            relative = file_path.relative_to(root).as_posix()
            if _is_banned(relative):
                findings.append(Finding(relative, RULE_BANNED))
            elif file_path.is_symlink():
                continue
            elif file_path.is_file() and file_path.suffix.lower() in _TEXT_SUFFIXES:
                if _secret_found(file_path.read_bytes()):
                    findings.append(Finding(relative, RULE_SECRET))
        except (OSError, ValueError):
            continue
    return findings


def _export_paths(root: Path) -> Iterable[Path]:
    excluded_dirs = {
        ".git",
        ".worktrees",
        "worktrees",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".cache",
        ".local",
        ".ruff_cache",
        ".pytest_cache",
    }
    for directory, child_dirs, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        descend: list[str] = []
        for name in child_dirs:
            child = current / name
            relative = child.relative_to(root).as_posix()
            if name.lower() in excluded_dirs or name.lower().startswith("pytest-cache-files-"):
                continue
            if _is_banned(relative):
                yield child
            elif not child.is_symlink():
                descend.append(name)
        child_dirs[:] = descend
        for filename in filenames:
            if filename.lower() == ".git":
                continue
            yield current / filename


def _cat_file_batch(root: Path, object_ids: list[str]) -> Iterable[tuple[str, bytes]]:
    request = b"".join(object_id.encode("ascii") + b"\n" for object_id in object_ids)
    response = _git_with_input(root, request, "cat-file", "--batch")
    offset = 0
    for object_id in object_ids:
        header_end = response.find(b"\n", offset)
        if header_end < 0:
            raise ValueError("incomplete Git object batch")
        header = response[offset:header_end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("unexpected Git object batch entry")
        content_start = header_end + 1
        content_end = content_start + int(header[2])
        yield object_id, response[content_start:content_end]
        offset = content_end + 1


def scan_history(root: Path) -> list[Finding]:
    objects: dict[str, str] = {}
    findings: set[Finding] = set()
    entries = (
        _git(root, "rev-list", "--objects", "--all").decode("utf-8", errors="replace").splitlines()
    )
    for entry in entries:
        object_id, separator, path = entry.partition(" ")
        if not separator or not path:
            continue
        if _is_banned(path):
            findings.add(Finding(path, RULE_BANNED, object_id=object_id))
        elif Path(path).suffix.lower() in _TEXT_SUFFIXES:
            objects[object_id] = path
    for object_id, content in _cat_file_batch(root, list(objects)):
        if _secret_found(content):
            findings.add(Finding(objects[object_id], RULE_SECRET, object_id=object_id))
    return sorted(findings)


def audit(root: Path, *, export: bool = False, history: bool = False) -> list[Finding]:
    findings = scan_working_tree(root, export=export)
    if history:
        findings.extend(scan_history(root))
    return sorted(set(findings))


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="repository or export directory"
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="scan every file under root, including untracked files",
    )
    parser.add_argument(
        "--history", action="store_true", help="also inspect commits reachable from Git refs"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        findings = audit(root, export=args.export, history=args.history)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # Deliberately omit exception text: tool errors can contain data from scanned files.
        print(f"audit failed ({type(error).__name__})", file=sys.stderr)
        return 2
    for finding in findings:
        suffix = f" commit={finding.commit}" if finding.commit else ""
        suffix += f" object={finding.object_id}" if finding.object_id else ""
        print(f"{finding.path}\t{finding.rule}{suffix}")
    print(f"findings={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
