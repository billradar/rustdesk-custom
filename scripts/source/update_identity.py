"""Embed a non-secret client identity before prepared-source inventory is frozen."""
import json
import re
from pathlib import Path


def write_identity(tree, *, repository, version, sha, variant, run, channel, revision=""):
    if (not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}", repository)
            or repository.rsplit('/', 1)[-1] in ('.', '..')
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or variant not in ("standard", "sos")
            or not re.fullmatch(r"[1-9][0-9]*", str(run))
            or channel not in ("ci", "stable", "nightly")):
        raise ValueError("Invalid client update source identity")
    if channel == "stable":
        if not re.fullmatch(r"v[1-9][0-9]*\.[1-9][0-9]*", revision):
            raise ValueError("Stable client requires the preflight patch revision")
    elif revision:
        raise ValueError("Non-release builds must not claim a Stable revision")
    data = dict(repository=repository, version=version, revision=revision or None, upstream_sha=sha,
                variant=variant, build_run=str(run))
    destination = Path(tree) / "src/custom_update/build.json"
    if not destination.is_file() or destination.is_symlink():
        raise ValueError("Client update patch must be applied before identity injection")
    destination.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    return data
