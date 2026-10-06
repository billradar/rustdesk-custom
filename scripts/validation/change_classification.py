#!/usr/bin/env python3
"""Classify repository changes into documentation-only or functional changes."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import PurePosixPath

NON_FUNCTIONAL_ROOT_NAMES = {
    ".gitignore",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
}
NON_FUNCTIONAL_GITHUB_PREFIXES = (
    ".github/ISSUE_TEMPLATE/",
    ".github/PULL_REQUEST_TEMPLATE/",
)
NON_FUNCTIONAL_GITHUB_FILES = {
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/CODEOWNERS",
    ".github/SECURITY.md",
}


def is_non_functional(path: str) -> bool:
    p = PurePosixPath(path)
    if path == "docs" or path.startswith("docs/"):
        return True
    if path in NON_FUNCTIONAL_GITHUB_FILES or any(
        path.startswith(prefix) for prefix in NON_FUNCTIONAL_GITHUB_PREFIXES
    ):
        return True
    if p.name in NON_FUNCTIONAL_ROOT_NAMES:
        return True
    if p.name.startswith("LICENSE."):
        return True
    if p.name.startswith("CHANGELOG."):
        return True
    if p.name.startswith("README.") and p.suffix.lower() == ".md":
        return True
    if p.name.startswith("CHANGELOG.") and p.suffix.lower() == ".md":
        return True
    if p.suffix.lower() == ".md":
        return True
    return False


def changed_paths(base: str | None, head: str | None) -> list[str]:
    if not base or not head:
        return []
    result = subprocess.run(
        ["git", "diff", "--name-status", "--find-renames", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if not fields:
            continue
        status = fields[0]
        if status.startswith(("R", "C")) and len(fields) >= 3:
            paths.extend(fields[1:3])
        elif len(fields) >= 2:
            paths.append(fields[1])
    return paths


def classify(event: str, force_rebuild: bool) -> tuple[str, list[str], str]:
    if event == "workflow_dispatch":
        return (
            "FUNCTIONAL",
            [],
            "manual workflow_dispatch is an explicit functional CI request",
        )

    base = (
        os.environ.get("GITHUB_BASE_REF")
        if event == "pull_request"
        else os.environ.get("GITHUB_EVENT_BEFORE")
    )
    head = os.environ.get("GITHUB_SHA")

    if event == "push" and (not base or set(base) == {"0"}):
        return (
            "FUNCTIONAL",
            [],
            "push has no usable previous revision; fail closed to full CI",
        )

    if force_rebuild:
        return (
            "FUNCTIONAL",
            changed_paths(base, head),
            "force_rebuild=true explicitly requests full CI",
        )

    paths = changed_paths(base, head)
    if paths and all(is_non_functional(path) for path in paths):
        return (
            "DOCS_ONLY",
            paths,
            "all changed paths are documentation/non-functional",
        )

    return "FUNCTIONAL", paths, "at least one changed path is functional"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    event = os.environ.get("GITHUB_EVENT_NAME", "")
    kind, paths, reason = classify(event, args.force_rebuild)

    print(f"Change classification: {kind}")
    print(f"Reason: {reason}")
    if paths:
        print("Changed paths:")
        for path in paths:
            print(f"  - {path}")
    elif event != "workflow_dispatch":
        print("Changed paths: (empty)")

    if args.github_output:
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(f"change_class={kind}\n")
                handle.write(f"docs_only={'true' if kind == 'DOCS_ONLY' else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
