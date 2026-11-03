"""Offline contracts for private draft asset verifier; no network, secrets or signing."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from . import audit_release_assets as audit

class AuditContracts(unittest.TestCase):
    def test_private_drafts_require_explicit_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "RELEASE_AUDIT_TOKEN"):
                audit.request("https://api.github.com/repos/billradar/rustdesk-custom/releases/1")
    def test_sums_accepts_standard_gnu_format(self):
        digest = "a" * 64
        self.assertEqual(audit.sums_parse(digest + "  test.apk\\n".replace("\\n", "\n")), {"test.apk": digest})
    def test_sums_rejects_duplicate(self):
        line = "a" * 64 + "  test.apk\n"
        with self.assertRaises(ValueError):
            audit.sums_parse(line + line)
    def test_sums_rejects_path(self):
        with self.assertRaises(ValueError):
            audit.sums_parse("a" * 64 + "  ../test.apk\n")
    def test_digest_format(self):
        self.assertTrue(audit.HEX.fullmatch("a" * 64))
        self.assertFalse(audit.HEX.fullmatch("z" * 64))

if __name__ == "__main__":
    unittest.main()
