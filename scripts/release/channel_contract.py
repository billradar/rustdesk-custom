#!/usr/bin/env python3
import copy, contextlib, io, json, os, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import scripts.build.build_adapter as build_adapter
import scripts.source.prepared_source as prepared_source
import scripts.release.channel as channel
ROOT = Path(__file__).resolve().parents[2]
import yaml

class BuildInterfaceTests(unittest.TestCase):
    def test_unreviewed_build_definition_blocks(self):
        unknown={'signature':'0'*64}
        with patch.object(build_adapter,'inspect',return_value=(unknown,{})),self.assertRaisesRegex(ValueError,'BUILD_COMPATIBILITY=FAIL'):
            build_adapter.check(Path('.'))
    def test_known_profile_is_accepted_without_version_inference(self):
        approved=json.loads((ROOT/'metadata/build/adapter-profiles.json').read_text())['profiles'][0]
        profile={'signature':approved['signature'],'upstream_version':'9.8.7'}
        with patch.object(build_adapter,'inspect',return_value=(profile,{})):
            self.assertEqual(build_adapter.check(Path('.'))['upstream_version'],'9.8.7')

class SourceBoundaryTests(unittest.TestCase):
    def test_checksum_failure_happens_before_extraction(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);bundle=root/'bundle';bundle.mkdir();(bundle/'source.tar.gz').write_bytes(b'wrong');(bundle/'SHA256SUMS').write_text('0'*64+'  source.tar.gz\n')
            with self.assertRaisesRegex(ValueError,'checksum'):prepared_source.unpack(bundle,root/'output','standard','a'*40,'v1')
            self.assertFalse((root/'output').exists())
    def test_path_traversal_is_blocked(self):
        import hashlib
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);bundle=root/'bundle';bundle.mkdir();archive=bundle/'source.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                item=tarfile.TarInfo('source/../../escape');item.size=3;tar.addfile(item,io.BytesIO(b'bad'))
            (bundle/'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  source.tar.gz\n')
            with self.assertRaisesRegex(ValueError,'Unsafe archive'):prepared_source.unpack(bundle,root/'output','standard','a'*40,'v1')
            self.assertFalse((root/'escape').exists())
    def test_changed_source_inventory_blocks(self):
        m=dict(variant='standard',upstream_sha='a'*40,patchset='v1',custom_repository_sha='b'*40,
               prepare_workflow_run='3',upstream_repository='rustdesk/rustdesk',common_patch_hash='c'*64,sos_patch_hash=None,files={'main.rs':'unchanged'})
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'source-manifest.json').write_text(json.dumps(m));(root/'main.rs').write_text('modified')
            with patch.object(prepared_source,'git',return_value='a'*40),patch.object(prepared_source,'patch_hash',return_value='c'*64),self.assertRaisesRegex(ValueError,'inventory'):
                prepared_source.verify_tree(root,'standard','a'*40,'v1','b'*40,3)

class ChannelPolicyTests(unittest.TestCase):
    def discovery(self):
        return dict(channel='stable',version='1.4.9',upstream_tag='1.4.9',upstream_ref='1.4.9',upstream_sha='a'*40,revision='1',release_tag='v1.4.9-custom.1')
    def draft_fixture(self):
        return dict(name='v1.4.9-custom.1',tag_name='untagged-123',draft=True,prerelease=False,
            body=f'Automation-State: complete\nUpstream SHA: {"a"*40}\nPatch Set: v1\nCommon Patch Hash: {channel.patch_hash("common","v1")}\nSOS Patch Hash: {channel.patch_hash("sos","v1")}',
            assets=[dict(name=n,state='uploaded') for n in ['SHA256SUMS','build-info-standard.json','build-info-sos.json','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']])
    def test_discovery_only_does_not_query_drafts_or_resolve_sha_again(self):
        with patch.object(channel,'choose_stable',return_value={'version':'1.4.9','upstream_tag':'1.4.9','upstream_sha':'a'*40}),patch.object(channel,'api') as api,patch.object(channel,'outputs') as out:
            channel.resolve('stable',discovery_only=True)
            api.assert_not_called();self.assertNotIn('build_needed',out.call_args.args[0])
    def test_untagged_draft_gate_and_force_artifacts_only(self):
        for force in (False,True):
            with patch.object(channel,'api',side_effect=[None,[self.draft_fixture()]]),patch.object(channel,'choose_stable') as resolve:
                data=channel.release_preflight(self.discovery(),force)
                resolve.assert_not_called();self.assertEqual(data['build_needed'],force);self.assertFalse(data['draft_needed'])
    def test_incomplete_or_mismatched_draft_blocks_before_build(self):
        for mutate in ('missing-asset','wrong-sha','incomplete'):
            draft=self.draft_fixture()
            if mutate=='missing-asset':draft['assets'].pop()
            elif mutate=='wrong-sha':draft['body']=draft['body'].replace('a'*40,'b'*40)
            else:draft['body']=draft['body'].replace('Automation-State: complete','Automation-State: incomplete')
            with patch.object(channel,'api',side_effect=[None,[draft]]),self.assertRaisesRegex(ValueError,'incomplete or incompatible'):
                channel.release_preflight(self.discovery(),True)
    def test_new_revision_permits_build_and_draft(self):
        with patch.object(channel,'api',side_effect=[None,[],None]):
            data=channel.release_preflight(self.discovery());self.assertTrue(data['build_needed']);self.assertTrue(data['draft_needed'])
    def test_duplicate_and_later_page_drafts(self):
        with patch.object(channel,'api',side_effect=[None,[self.draft_fixture(),self.draft_fixture()]]),self.assertRaisesRegex(ValueError,'Duplicate'):
            channel.release_preflight(self.discovery())
        with patch.object(channel,'api',side_effect=[None,[{'draft':False}]*100,[self.draft_fixture()]]):
            self.assertFalse(channel.release_preflight(self.discovery())['build_needed'])
    def test_release_preflight_workflow_permissions_and_gate(self):
        jobs=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())['jobs']
        self.assertEqual({n for n,j in jobs.items() if j.get('permissions',{}).get('contents')=='write'},{'draft-preflight','draft','release'})
        self.assertIn('draft-preflight',jobs['qualification']['needs'])
        self.assertIn('qualification',jobs['prepare']['needs'])
        self.assertIn('needs.draft-preflight.outputs.draft_needed',jobs['draft']['if'])
        self.assertIn('--discovery-only',jobs['resolve']['steps'][1]['run'])
    def test_nightly_uses_default_branch_not_stable(self):
        with patch.object(channel,'api',return_value={'default_branch':'development'}),patch.object(channel,'resolve_ref',return_value='a'*40) as resolve,patch.object(channel,'outputs') as output:
            channel.resolve('nightly');resolve.assert_called_once_with('development')
            self.assertEqual(output.call_args.args[0]['upstream_sha'],'a'*40)
            self.assertEqual(output.call_args.args[0]['upstream_tag'],'')
    def test_nightly_explicit_ref_bypasses_default_branch(self):
        with patch.object(channel,'api',return_value={'default_branch':'development'}),patch.object(channel,'resolve_ref',return_value='a'*40) as resolve,patch.object(channel,'outputs') as output:
            channel.resolve('nightly','test')
            resolve.assert_called_once_with('test')
            self.assertEqual(output.call_args.args[0]['upstream_ref'],'test')

    def test_nightly_workflow_uses_official_test_ref_and_router_default_branch(self):
        nightly=(ROOT/'.github/workflows/nightly.yml').read_text()
        router=(ROOT/'.github/workflows/upstream-event-router.yml').read_text()
        self.assertIn('UPSTREAM_TEST_REF: ${{ vars.UPSTREAM_TEST_REF || vars.UPSTREAM_TEST_BRANCH || \'test\' }}',nightly)
        self.assertIn('REQUESTED_REF="$UPSTREAM_TEST_REF"',nightly)
        self.assertIn('REQUESTED_REF="${REQUESTED_REF:-$UPSTREAM_TEST_REF}"',nightly)
        self.assertIn("repo='rustdesk/rustdesk'",router)
        self.assertIn("api(f'repos/{repo}')['default_branch']",router)
        self.assertIn("-f upstream_ref='${{ needs.detect.outputs.production_ref }}'",router)
        self.assertIn('--ref main',router)
        self.assertNotIn('billradar/rustdesk-custom:test/development',nightly+router)
    def test_existing_draft_skips_costly_build_and_never_overwrites(self):
        sha='a'*40;existing={'body':f'Automation-State: complete\nUpstream SHA: {sha}\nPatch Set: v1\nCommon Patch Hash: {channel.patch_hash("common","v1")}\nSOS Patch Hash: {channel.patch_hash("sos","v1")}', 'draft':True,'prerelease':False, 'assets':[{'name':n,'state':'uploaded'} for n in ['SHA256SUMS','build-info-standard.json','build-info-sos.json','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']]}
        with patch.object(channel,'choose_stable',return_value={'version':'1.4.9','upstream_tag':'1.4.9','upstream_sha':sha}),patch.object(channel,'api',return_value=existing),patch.object(channel,'outputs') as out:
            channel.resolve('stable');data=out.call_args.args[0];self.assertFalse(data['build_needed']);self.assertFalse(data['draft_needed'])
            channel.resolve('stable',force=True);data=out.call_args.args[0];self.assertTrue(data['build_needed']);self.assertFalse(data['draft_needed'])
    def test_entry_and_release_permissions(self):
        docs={p.name:yaml.safe_load(p.read_text()) for p in (ROOT/'.github/workflows').glob('*.yml')}
        self.assertEqual(docs['nightly.yml']['on']['schedule'],[{'cron':'0 16 * * *'}])
        self.assertTrue(all(j.get('permissions',{}).get('contents')!='write' for j in docs['ci.yml']['jobs'].values()))
        self.assertEqual(docs['nightly.yml']['jobs']['draft']['permissions']['contents'],'write')
        matrix=docs['build.yml']['jobs']['build']['strategy']['matrix']['include']
        self.assertEqual({(r['platform'],r['arch'],r['variant']) for r in matrix},{('windows','x86_64','standard'),('windows','x86_64','sos')})
        planned=json.loads((ROOT/'metadata/platform/matrix.json').read_text())['entries']
        self.assertFalse(any(r['variant']=='sos' and r['platform'] in ('android','ios','web') for r in planned))
    def test_no_auto_publish_calls(self):
        import ast
        for path in (ROOT/'scripts/release/production.py',ROOT/'scripts/release/channel.py'):
            tree=ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.Dict):
                    for key,value in zip(node.keys,node.values):
                        if isinstance(key,ast.Constant) and key.value=='draft':
                            self.assertIsInstance(value,ast.Constant);self.assertIs(value.value,True)

if __name__ == "__main__": unittest.main()
