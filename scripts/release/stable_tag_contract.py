"""Immutable Stable tag identity and post-validation ordering regressions."""
import ast
from pathlib import Path
import subprocess
import unittest
import urllib.error
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

    def test_created_tag_can_be_temporarily_missing_without_another_write(self):
        with patch.object(tags,'api',side_effect=[None,{'sha':SHA},None,None,REF]) as read,patch.object(tags,'request',return_value=REF) as write,patch.object(tags.time,'sleep') as sleep:
            self.assertEqual(tags.ensure(REPO,TAG,SHA),REF)
        self.assertEqual(write.call_count,1)
        self.assertEqual([call.args for call in sleep.call_args_list],[(1,),(2,)])
        for call in read.call_args_list[2:]:self.assertEqual(call.kwargs,{'missing':True})

    def test_absent_readback_exhausts_bounded_retries_and_still_fails(self):
        with patch.object(tags,'api',side_effect=[None,{'sha':SHA}]+[None]*5) as read,patch.object(tags,'request',return_value=REF) as write,patch.object(tags.time,'sleep') as sleep:
            with self.assertRaisesRegex(ValueError,'verification incomplete'):tags.ensure(REPO,TAG,SHA)
        self.assertEqual(read.call_count,7);self.assertEqual(write.call_count,1)
        self.assertEqual([call.args for call in sleep.call_args_list],[(1,),(2,),(4,),(8,)])

    def test_visible_wrong_sha_or_invalid_response_never_gets_retried(self):
        for wrong in (dict(REF,object=dict(type='commit',sha='b'*40)),{}):
            with self.subTest(response=wrong),patch.object(tags,'api',side_effect=[None,{'sha':SHA},None,wrong]) as read,patch.object(tags,'request',return_value=REF) as write,patch.object(tags.time,'sleep') as sleep:
                with self.assertRaisesRegex(ValueError,'never overwrite'):tags.ensure(REPO,TAG,SHA)
                self.assertEqual(read.call_count,4);self.assertEqual(write.call_count,1)
                sleep.assert_called_once_with(1)

    def test_non_404_read_errors_propagate_without_retry_or_another_write(self):
        for code in (401,403,500):
            error=urllib.error.HTTPError('https://api.github.com/ref',code,'read failed',{},None)
            with self.subTest(code=code),patch.object(tags,'api',side_effect=[None,{'sha':SHA},error]),patch.object(tags,'request',return_value=REF) as write,patch.object(tags.time,'sleep') as sleep:
                with self.assertRaises(urllib.error.HTTPError):tags.ensure(REPO,TAG,SHA)
                self.assertEqual(write.call_count,1);sleep.assert_not_called()

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
                                   ('qualification.py','publish_existing_draft',"read_release(existing,'stable',dict("),
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
        # Both Stable paths must rebind the metadata to the verified real
        # Git ref while keeping private Drafts unpublished.
        for file,function in [('qualification.py','_release'),('channel.py','draft')]:
            source=(ROOT/'scripts/release'/file).read_text()
            tree=ast.parse(source)
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function)
            body=ast.get_source_segment(source,node)
            self.assertIn("'tag_name':tag",body)
            self.assertIn("'target_commitish':",body)
            self.assertIn("'prerelease':False",body)
        # No per-run Nightly tags: nightly.py only uses a moving `nightly` ref.
        self.assertIn("tag = 'nightly'",nightly)
        self.assertIn("dict(ref='refs/tags/' + tag, sha=os.environ['GITHUB_SHA'])",nightly)
        self.assertNotIn("request('PATCH'",(ROOT/'scripts/release/stable_tag.py').read_text())
        self.assertNotIn("request('DELETE'",(ROOT/'scripts/release/stable_tag.py').read_text())


if __name__=='__main__':unittest.main()
