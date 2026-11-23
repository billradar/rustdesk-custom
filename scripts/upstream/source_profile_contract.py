#!/usr/bin/env python3
"""Contract for SHA-first Patch Profile routing; no candidate is approved here."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts.upstream import patchsets

SHA = "9724512429b053be04cdb843345e99ddcccdb80e"
OLD = "6aec3069aec486ad7df07429a0a1ee411fc8d73a"
APPROVED = "95cca3f661f635b3cc85c04935fe8d96d8f432ef"
NEW_MAIN = "51f94394ce61e1f3d26229565c326b2862cbdd1f"

def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "metadata").mkdir()
        for name in ("v3", "v4"):
            for part in ("common", "sos"):
                (root / "patchsets" / name / part).mkdir(parents=True)
        registry = {
            "schema": "patch-profiles-v1",
            "latest_maintained": "rd-1.5.3",
            "retired_patchsets": [],
            "profiles": {
                "rd-1.5.3": {"patchset": "v3", "stable_allowed": True},
                "rd-1.5.3-sha-candidate": {"patchset": "v4", "stable_allowed": False}
            },
            "exact_versions": {"1.5.3": "rd-1.5.3"},
            "exact_sources": {
                SHA: {"version": "1.5.3", "profile": "rd-1.5.3-sha-candidate"},
                APPROVED: {"version": "1.5.3", "profile": "rd-1.5.3"},
                NEW_MAIN: {"version": "1.5.3", "profile": "rd-1.5.3-sha-candidate"},
            }
        }
        (root / "metadata" / "patch-profiles.json").write_text(json.dumps(registry))
        with patch.object(patchsets, "ROOT", root):
            new = patchsets.profile_for_version("1.5.3", "ci", source_sha=SHA)
            assert new["selected"] == "v4" and new["source_match"]
            assert new["compatibility_test_only"] and not new["stable_allowed"]
            updated = patchsets.profile_for_version("1.5.3", "ci", source_sha=NEW_MAIN)
            assert updated["selected"] == "v4" and updated["source_match"]
            assert updated["compatibility_test_only"] and not updated["stable_allowed"]
            old = patchsets.profile_for_version("1.5.3", "ci", source_sha=OLD)
            assert old["selected"] == "v3" and not old["source_match"]
            assert old["fallback"] and old["compatibility_test_only"]
            assert not old["stable_allowed"]
            reviewed = patchsets.profile_for_version("1.5.3", "stable", source_sha=APPROVED)
            assert reviewed["selected"] == "v3" and reviewed["source_match"]
            assert reviewed["stable_allowed"] and not reviewed["fallback"]
            try:
                patchsets.profile_for_version("1.5.3", "stable", source_sha=OLD)
                raise AssertionError("Unknown same-version source unexpectedly allowed Stable")
            except ValueError as exc:
                assert "Stable requires" in str(exc)
            assert patchsets.profile_for_version("1.5.3", "ci")["selected"] == "v3"
            try:
                patchsets.profile_for_version("1.5.3", "stable", source_sha=SHA)
                raise AssertionError("Candidate source unexpectedly allowed Stable")
            except ValueError as exc:
                assert "Stable requires" in str(exc)
            try:
                patchsets.profile_for_version("1.5.1", "ci", source_sha=SHA)
                raise AssertionError("Mismatched source version accepted")
            except ValueError as exc:
                assert "version mismatch" in str(exc)
            try:
                patchsets.profile_for_version("1.5.3", "ci", source_sha="not-a-sha")
                raise AssertionError("Invalid SHA accepted")
            except ValueError as exc:
                assert "Invalid official source SHA" in str(exc)
    print("SHA-first routing, version fallback and Stable candidate denial: PASS")

if __name__ == "__main__":
    main()
