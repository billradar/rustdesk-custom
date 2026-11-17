"""Offline contract tests for v3 WSS candidate selection."""
import unittest
from scripts.validation.wss_failover_policy import (
    Failure, candidates, should_try_fallback,
)

PRIMARY = "https://rustdesk.houxnan.com"
BACKUP = "https://rustdesk-backup.houxnan.com"
OWN = "rustdesk.houxnan.com:21116"


class WssFailoverPolicyTest(unittest.TestCase):
    def pair(self, endpoint=OWN, role="id", **kwargs):
        return candidates(endpoint, OWN, PRIMARY, BACKUP, role, **kwargs)

    def test_owned_id_primary_fallback(self):
        pair = self.pair()
        self.assertEqual([x.url for x in pair], [
            "wss://rustdesk.houxnan.com/ws/id",
            "wss://rustdesk-backup.houxnan.com/ws/id",
        ])

    def test_owned_relay_requires_verification(self):
        self.assertEqual(self.pair(role="relay"), ())
        self.assertEqual(self.pair(role="relay", verified_own_relay=True)[1].url,
                         "wss://rustdesk-backup.houxnan.com/ws/relay")

    def test_unrelated_and_explicit_endpoints_are_not_rewritten(self):
        for endpoint in ("other.example.com:21116", "ws://rustdesk.houxnan.com/ws/id",
                         "wss://rustdesk.houxnan.com/ws/id", "127.0.0.1:21116"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.pair(endpoint), ())

    def test_disabled_and_custom_port(self):
        self.assertEqual(self.pair(enabled=False), ())
        self.assertEqual(self.pair(explicit_websocket_port=True), ())

    def test_origin_validation(self):
        for fallback in ("http://backup.example.com", "https://backup.example.com/other",
                         "https://user:pass@backup.example.com", PRIMARY):
            with self.subTest(fallback=fallback):
                self.assertEqual(candidates(OWN, OWN, PRIMARY, fallback), ())

    def test_only_pre_handshake_connectivity_failures_eligible(self):
        for failure in Failure:
            with self.subTest(failure=failure):
                self.assertEqual(should_try_fallback(failure), failure in {
                    Failure.DNS, Failure.CONNECT_REFUSED, Failure.UNREACHABLE,
                    Failure.CONNECT_TIMEOUT,
                })


if __name__ == "__main__":
    unittest.main()
