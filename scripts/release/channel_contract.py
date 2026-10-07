#!/usr/bin/env python3
import copy, contextlib, io, json, os, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import scripts.build.build_adapter as build_adapter
import scripts.source.prepared_source as prepared_source
import scripts.release.channel as channel
import scripts.release.qualification as qualification
from scripts.release.naming import native_package_name, windows_installer_name
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
            with self.assertRaisesRegex(ValueError,'checksum'):prepared_source.unpack(bundle,root/'output','standard','a'*40,'v999999')
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
        m=dict(variant='standard',upstream_sha='a'*40,patchset='v999999',custom_repository_sha='b'*40,
               prepare_workflow_run='3',upstream_repository='rustdesk/rustdesk',common_patch_hash='c'*64,sos_patch_hash=None,files={'main.rs':'unchanged'})
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'source-manifest.json').write_text(json.dumps(m));(root/'main.rs').write_text('modified')
            with patch.object(prepared_source,'git',return_value='a'*40),patch.object(prepared_source,'patch_hash',return_value='c'*64),self.assertRaisesRegex(ValueError,'inventory'):
                prepared_source.verify_tree(root,'standard','a'*40,'v999999','b'*40,3)

class ChannelPolicyTests(unittest.TestCase):
    def setUp(self):
        self._verify=patch.object(channel,'verify',return_value=True);self._verify.start()
        self._hash=patch.object(channel,'patch_hash',return_value='c'*64);self._hash.start()
        self.addCleanup(self._verify.stop);self.addCleanup(self._hash.stop)
    def discovery(self):
        return dict(channel='stable',version='1.4.9',upstream_tag='1.4.9',upstream_ref='1.4.9',upstream_sha='a'*40,revision='1',release_tag='v1.4.9-custom.1')
    def draft_fixture(self):
        return dict(name='v1.4.9-custom.1',tag_name='untagged-123',draft=True,prerelease=False,
            body='Automation-State: complete\nUpstream SHA: '+'a'*40+'\nPatch Set: v999999\nCommon Patch Hash: '+'c'*64+'\nSOS Patch Hash: '+'d'*64,
            assets=[dict(name=n,state='uploaded') for n in ['SHA256SUMS','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']])
    def test_discovery_only_does_not_query_drafts_or_resolve_sha_again(self):
        with patch.object(channel,'choose_stable',return_value={'version':'1.4.9','upstream_tag':'1.4.9','upstream_sha':'a'*40}),patch.object(channel,'api') as api,patch.object(channel,'outputs') as out:
            channel.resolve('stable',discovery_only=True)
            api.assert_not_called();self.assertNotIn('build_needed',out.call_args.args[0])
    def test_untagged_draft_gate_and_force_artifacts_only(self):
        for force in (False,True):
            with patch.object(channel,'api',side_effect=[None,[self.draft_fixture()]]),patch.object(channel,'choose_stable') as resolve:
                data=channel.release_preflight(self.discovery(),force)
                resolve.assert_not_called();self.assertEqual(data['build_needed'],force);self.assertFalse(data['draft_needed'])
                self.assertTrue(data['publish_existing'])
    def test_legacy_complete_draft_without_automation_marker_is_accepted(self):
        draft=self.draft_fixture()
        draft['body']=draft['body'].replace('Automation-State: complete\n','')
        with patch.object(channel,'api',side_effect=[None,[draft]]):
            data=channel.release_preflight(self.discovery(),False)
            self.assertFalse(data['build_needed'])
            self.assertFalse(data['draft_needed'])
            self.assertTrue(data['publish_existing'])

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
        self.assertEqual({n for n,j in jobs.items() if j.get('permissions',{}).get('contents')=='write'},{'draft-preflight','draft','release','publish-existing'})
        self.assertNotIn('qualification',jobs)
        self.assertNotIn('stable-ci-qualification',jobs)
        self.assertEqual(jobs['draft-preflight']['needs'],'resolve')
        self.assertEqual(set(jobs['prepare']['needs']),{'resolve','draft-preflight'})
        self.assertIn('needs.aggregate.outputs.draft_needed',jobs['draft']['if'])
        self.assertEqual(jobs['windows-build']['uses'],'./.github/workflows/build-stable-windows.yml')
        self.assertEqual(jobs['platforms-build']['uses'],'./.github/workflows/build-stable-platforms.yml')
        self.assertEqual(jobs['android-build']['uses'],'./.github/workflows/build-stable-android.yml')
        for name in ('windows-build','platforms-build','android-build'):
            self.assertNotIn('windows_only',jobs[name].get('with',{}))
            self.assertNotIn('other_platforms_only',jobs[name].get('with',{}))
            self.assertNotIn('android_only',jobs[name].get('with',{}))
        self.assertEqual(jobs['release']['needs'],'aggregate')
        self.assertEqual(jobs['draft']['needs'],'aggregate')
        self.assertEqual(jobs['aggregate']['needs'],['resolve','draft-preflight','windows-build','platforms-build','android-build','android-sign'])
        self.assertIn('--discovery-only',jobs['resolve']['steps'][1]['run'])
        for name in ('windows-build','platforms-build','android-build','android-sign','aggregate','release','draft'):
            self.assertNotIn('qualification',str(jobs[name].get('needs',[])))

    def test_stable_concurrency_and_ci_contract(self):
        tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        self.assertEqual(tag['concurrency']['group'],"stable-${{ inputs.upstream_ref || format('manual-{0}', github.run_id) }}")
        self.assertFalse(tag['concurrency']['cancel-in-progress'])
        ci=yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
        concurrency=ci['concurrency']
        self.assertIn("inputs.automation_source == 'upstream-event-router'",concurrency['group'])
        self.assertIn("'action-created-ci'",concurrency['group'])
        self.assertIn("format('normal-ci-{0}', github.ref)",concurrency['group'])
        self.assertIn("inputs.automation_source != 'upstream-event-router'",concurrency['cancel-in-progress'])
        self.assertIn('workflow_dispatch',ci['on'])
        self.assertIn('automation_source',ci['on']['workflow_dispatch']['inputs'])
        self.assertNotIn('qualification_mode',ci['on']['workflow_dispatch']['inputs'])
        self.assertNotIn('stable_owner_run_id',ci['on']['workflow_dispatch']['inputs'])
        self.assertNotIn('stable_custom_sha',ci['on']['workflow_dispatch']['inputs'])
        self.assertNotIn('stable_upstream_sha',ci['on']['workflow_dispatch']['inputs'])
        qual=ci['jobs']['qualification']
        steps='\n'.join(st.get('name','')+'\n'+st.get('run','') for st in qual['steps'] if isinstance(st,dict))
        self.assertIn('Create exact CI qualification record',steps)
        self.assertNotIn('Validate Stable qualification ownership and source',steps)
    def test_ci_cd_isolation_contract(self):
        ci=yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
        router=yaml.safe_load((ROOT/'.github/workflows/upstream-event-router.yml').read_text())
        tag=(ROOT/'.github/workflows/tag.yml').read_text()
        ci_text=(ROOT/'.github/workflows/ci.yml').read_text()
        self.assertNotIn('promote_stable',ci['on']['workflow_dispatch']['inputs'])
        self.assertNotIn('gh workflow run tag.yml',ci_text)
        stable_run=router['jobs']['stable-tag']['steps'][1].get('run','')
        self.assertNotIn('ci-qualification-',stable_run)
        self.assertNotIn('workflow run ci.yml',stable_run)
        self.assertIn('gh workflow run tag.yml',stable_run)
        self.assertNotIn('compat-check.yml',tag)
        self.assertNotIn('verify_source.py',tag)
        self.assertIn('--exact',tag)
        self.assertNotIn('ci-qualification',tag)

    def test_qualification_identity_and_lookup_semantics(self):
        common='c'*64; sos='d'*64
        def record(custom='a'*40, upstream='b'*40, ref='v2', patchset='v2', common_hash=common, sos_hash=sos, mode='manual'):
            return {
                'schema':'ci-qualification-v1','qualified':True,'workflow_run_id':101,
                'event':'workflow_dispatch','custom_repository_sha':custom,
                'upstream_repository':'rustdesk/rustdesk','upstream_sha':upstream,
                'upstream_ref':ref,'patchset':patchset,
                'common_patch_hash':common_hash,'sos_patch_hash':sos_hash,
                'qualification_mode':mode
            }
        with patch.object(qualification,'patch_hash',side_effect=lambda folder,name: common if folder=='common' else sos), \
             patch.object(qualification,'_workflow_dispatch_success_runs',return_value=[{'id':101,'head_branch':'main','head_sha':'a'*40}]), \
             patch.object(qualification,'gh_json',return_value={'artifacts':[{'name':'ci-qualification-'+'a'*40,'expired':False}]}), \
             patch.object(qualification,'_download_qualification',return_value=record()):
            result=qualification.lookup_ci_qualification('repo','a'*40,'b'*40,'v2','v2')
            self.assertEqual(result['status'],'FOUND')
        with patch.object(qualification,'_workflow_dispatch_success_runs',return_value=[]):
            result=qualification.lookup_ci_qualification('repo','a'*40,'b'*40,'v2','v2')
            self.assertEqual(result['status'],'MISSING')
        bad_upstream=record(upstream='e'*40)
        with patch.object(qualification,'patch_hash',side_effect=lambda folder,name: common if folder=='common' else sos), \
             patch.object(qualification,'_workflow_dispatch_success_runs',return_value=[{'id':101,'head_branch':'main','head_sha':'a'*40}]), \
             patch.object(qualification,'gh_json',return_value={'artifacts':[{'name':'ci-qualification-'+'a'*40,'expired':False}]}), \
             patch.object(qualification,'_download_qualification',return_value=bad_upstream):
            self.assertEqual(qualification.lookup_ci_qualification('repo','a'*40,'b'*40,'v2','v2')['status'],'INVALID')
        bad_patchset=record(patchset='v888888')
        with patch.object(qualification,'patch_hash',side_effect=lambda folder,name: common if folder=='common' else sos), \
             patch.object(qualification,'_workflow_dispatch_success_runs',return_value=[{'id':101,'head_branch':'main','head_sha':'f'*40}]), \
             patch.object(qualification,'gh_json',return_value={'artifacts':[{'name':'ci-qualification-'+'f'*40,'expired':False}]}), \
             patch.object(qualification,'_download_qualification',return_value=bad_patchset):
            self.assertEqual(qualification.lookup_ci_qualification('repo','a'*40,'b'*40,'v2','v2')['status'],'INVALID')
        bad_hash=record(common_hash='0'*64)
        with patch.object(qualification,'patch_hash',side_effect=lambda folder,name: common if folder=='common' else sos), \
             patch.object(qualification,'_workflow_dispatch_success_runs',return_value=[{'id':101,'head_branch':'main','head_sha':'a'*40}]), \
             patch.object(qualification,'gh_json',return_value={'artifacts':[{'name':'ci-qualification-'+'a'*40,'expired':False}]}), \
             patch.object(qualification,'_download_qualification',return_value=bad_hash):
            self.assertEqual(qualification.lookup_ci_qualification('repo','a'*40,'b'*40,'v2','v2')['status'],'INVALID')
        reused=record(custom='f'*40)
        with patch.object(qualification,'patch_hash',side_effect=lambda folder,name: common if folder=='common' else sos), \
             patch.object(qualification,'_workflow_dispatch_success_runs',return_value=[{'id':101,'head_branch':'main','head_sha':'f'*40}]), \
             patch.object(qualification,'gh_json',return_value={'artifacts':[{'name':'ci-qualification-'+'f'*40,'expired':False}]}), \
             patch.object(qualification,'_download_qualification',return_value=reused):
            self.assertEqual(qualification.lookup_ci_qualification('repo','a'*40,'b'*40,'v2','v2')['status'],'FOUND')

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
    def test_public_release_assets_are_binary_only(self):
        source=(ROOT/'scripts/release/qualification.py').read_text()
        self.assertNotIn("source-'+name+'.zip",source)
        self.assertNotIn("build-info-'+name+'.json",source)
        self.assertNotIn("shutil.copy2(folder/'build-info.json',assets/metadata_name)",source)
        self.assertIn("package.suffix.lower() not in allowed_suffixes",source)
        self.assertIn("allowed_suffixes={'android': {'.apk'}, 'linux': {'.deb', '.rpm'}, 'macos': {'.dmg'}}",source)
        self.assertIn("name.startswith('source-')",source)
        self.assertIn("name.startswith('build-info-')",source)
        names=['SHA256SUMS',
               windows_installer_name('1.4.9','standard','exe'),
               windows_installer_name('1.4.9','standard','msi'),
               windows_installer_name('1.4.9','sos','exe'),
               windows_installer_name('1.4.9','sos','msi'),
               native_package_name('1.4.9','standard','linux','x86_64','standard-rustdesk-1.4.9-x86_64.deb'),
               native_package_name('1.4.9','standard','macos','x86_64','standard-rustdesk-1.4.9-x86_64.dmg')]
        forbidden=[n for n in names if n.lower().endswith('.json') or n.startswith('source-') or n.startswith('build-info-')]
        self.assertEqual(forbidden,[])
        qualification=source
        self.assertIn("packages_dir=folder/'packages'", qualification)
        self.assertIn("Windows release requires exactly one EXE and one MSI", qualification)
        self.assertNotIn("windows-x86_64.zip", qualification)

    def test_canonical_variant_naming(self):
        self.assertEqual(windows_installer_name('1.4.9','standard','exe'), 'rustdesk-1.4.9-windows-x86_64.exe')
        self.assertEqual(windows_installer_name('1.4.9','sos','msi'), 'rustdesk-1.4.9-sos-windows-x86_64.msi')
        self.assertEqual(native_package_name('1.4.9','standard','android','aarch64','standard-rustdesk-1.4.9-aarch64.apk'), 'rustdesk-1.4.9-android-aarch64.apk')
        self.assertEqual(native_package_name('1.4.9','sos','linux','x86_64','sos-rustdesk-1.4.9-x86_64.deb'), 'rustdesk-1.4.9-sos-linux-x86_64.deb')
        self.assertEqual(native_package_name('1.4.9','standard','macos','aarch64','standard-rustdesk-1.4.9-aarch64-unsigned.dmg'), 'rustdesk-1.4.9-macos-aarch64-unsigned.dmg')

    def test_existing_draft_skips_costly_build_and_never_overwrites(self):
        sha='a'*40;existing={'body':f'Automation-State: complete\nUpstream SHA: {sha}\nPatch Set: v999999\nCommon Patch Hash: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\nSOS Patch Hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', 'draft':True,'prerelease':False, 'assets':[{'name':n,'state':'uploaded'} for n in ['SHA256SUMS','build-info-standard.json','build-info-sos.json','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']]}
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
