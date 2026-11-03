"""Coordinator Lite's sole source+patchset routing identity and active gate."""
import unittest

from scripts.release.coordinator_lite import build_identity, from_hashes, matching_state, patchset_sha256


class CoordinatorLiteContract(unittest.TestCase):
    def test_only_upstream_and_combined_patchset_sha_define_identity(self):
        p = patchset_sha256('b'*64, 'c'*64)
        self.assertEqual(len(p), 64)
        self.assertEqual(from_hashes('a'*40, 'b'*64, 'c'*64),
                         build_identity('a'*40, p))
        self.assertNotEqual(from_hashes('a'*40, 'b'*64, 'c'*64),
                            from_hashes('d'*40, 'b'*64, 'c'*64))
        self.assertNotEqual(from_hashes('a'*40, 'b'*64, 'c'*64),
                            from_hashes('a'*40, 'b'*64, 'd'*64))

    def test_in_progress_queued_waiting_unknown_are_skipped(self):
        for status in ('queued', 'pending', 'waiting', 'in_progress', None):
            with self.subTest(status=status):
                self.assertEqual(matching_state([{'status':status}]), 'ACTIVE')
        self.assertEqual(matching_state([{'status':'completed', 'conclusion':'success'}]), 'SUCCESS')
        self.assertEqual(matching_state([{'status':'completed', 'conclusion':'failure'}]), 'RETRY')


if __name__ == '__main__':
    unittest.main()
