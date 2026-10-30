"""Immutable Stable tag identity and post-validation ordering regressions."""
import ast
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from scripts.release import stable_tag as tags

ROOT=Path(__file__).resolve().parents[2]
REPO='example/repo'
TAG='v1.5.0-custom.v2.5'
SHA='a'*40
REF=dict(ref='refs/tags/'+TAG,object=dict(type='commit',sha=SHA))


class StableTagTests(unittest.TestCase):
    def test_missing_tag_is_created_and_verified_at_exact_custom_commit(self):
        with patch.object(tags,'api',side_effect=[None,{'sha':SHA},REF]),patch.object(tags,'request',return_value=REF) as write:
            self.assertEqual(tags.ensure(REPO,TAG,SHA),REF)
        write.assert_called_once_with('POST',f'repos/{REPO}/git/refs',{'ref':'refs/tags/'+TAG,'sha':SHA})

    def test_same_existing_tag_is_idempotent_and_other_commit_is_never_overwritten(self):
        with patch.object(tags,'api',return_value=REF),patch.object(tags,'request') as write:
            tags.ensure(REPO,TAG,SHA)
            write.assert_not_called()
        with patch.object(tags,'api',return_value=dict(REF,object=dict(type='commit',sha='b'*40))),patch.object(tags,'request') as write:
            with self.assertRaisesRegex(ValueError,'never overwrite'):tags.ensure(REPO,TAG,SHA)
            write.assert_not_called()

    def test_annotated_tag_must_resolve_to_same_commit(self):
        annotated=dict(REF,object=dict(type='tag',sha='b'*40))
        with patch.object(tags,'api',side_effect=[annotated,{'object':REF['object']}]),patch.object(tags,'request') as write:
            self.assertEqual(tags.ensure(REPO,TAG,SHA),annotated)
            write.assert_not_called()
        with patch.object(tags,'api',side_effect=[annotated,{'object':dict(type='commit',sha='c'*40)}]):
            with self.assertRaises(ValueError):tags.ensure(REPO,TAG,SHA)

    def test_tag_creation_race_only_accepts_exact_existing_identity(self):
        failure=subprocess.CalledProcessError(1,['gh','api'])
        with patch.object(tags,'api',side_effect=[None,{'sha':SHA},REF]),patch.object(tags,'request',side_effect=failure):
            self.assertEqual(tags.ensure(REPO,TAG,SHA),REF)
        with patch.object(tags,'api',side_effect=[None,{'sha':SHA},None]),patch.object(tags,'request',side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError):tags.ensure(REPO,TAG,SHA)

    def test_wrong_identity_or_server_response_blocks_without_moving_ref(self):
        for tag,sha in [('nightly',SHA),(TAG,'main'),(TAG,'x'*40)]:
            with patch.object(tags,'api') as api:
                with self.assertRaises(ValueError):tags.ensure(REPO,tag,sha)
                api.assert_not_called()
        with patch.object(tags,'api',side_effect=[None,{'sha':'b'*40}]),patch.object(tags,'request') as write:
            with self.assertRaises(ValueError):tags.ensure(REPO,TAG,SHA)
            write.assert_not_called()
        with patch.object(tags,'api',side_effect=[None,{'sha':SHA}]),patch.object(tags,'request',return_value=dict(REF,object=dict(type='commit',sha='b'*40))):
            with self.assertRaises(ValueError):tags.ensure(REPO,TAG,SHA)

    def test_only_stable_paths_create_tags_after_asset_checks(self):
        for file,function,gate in [('qualification.py','_release','uploaded!=expected_assets'),
                                   ('qualification.py','publish_existing_draft','verify_release_asset_checksums(tag,assets)'),
                                   ('channel.py','draft','!=expected:')]:
            source=(ROOT/'scripts/release'/file).read_text()
            tree=ast.parse(source)
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
            body=ast.get_source_segment(source,node)
            self.assertIn(gate,body)
            self.assertGreater(body.index('    ensure('),body.index(gate))
            self.assertLess(body.index('    ensure('),body.rindex("request("))
        nightly=(ROOT/'scripts/release/nightly.py').read_text()
        self.assertNotIn('stable_tag',nightly)
        self.assertNotIn("request('PATCH'",(ROOT/'scripts/release/stable_tag.py').read_text())
        self.assertNotIn("request('DELETE'",(ROOT/'scripts/release/stable_tag.py').read_text())


if __name__=='__main__':unittest.main()
