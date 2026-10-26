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
        self._env=patch.dict(os.environ,GITHUB_SHA='b'*40,INCLUDE_WAYLAND='false');self._env.start()
        self._verify=patch.object(channel,'verify',return_value=True);self._verify.start()
        self._hash=patch.object(channel,'patch_hash',return_value='c'*64);self._hash.start()
        self._assets=patch.object(channel,'verify_release_asset_checksums',return_value=True);self._assets.start()
        self.addCleanup(self._verify.stop);self.addCleanup(self._hash.stop);self.addCleanup(self._assets.stop);self.addCleanup(self._env.stop)
    def discovery(self, patchset='v999999'):
        return dict(channel='stable',version='1.4.9',upstream_tag='1.4.9',upstream_ref='1.4.9',upstream_sha='a'*40,patchset=patchset)

    def draft_fixture(self, patchset='v999999', revision='1'):
        tag=f'v1.4.9-custom.{patchset}.{revision}'
        included,policy=channel.wayland_identity()
        identity=channel.build_identity('a'*40,patchset,'c'*64,'c'*64,'b'*40,included,policy)
        assets=['SHA256SUMS','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']
        if included:assets += ['unattended-wayland-rustdesk-unattended-wayland-1.4.9-x86_64.deb','unattended-wayland-rustdesk-unattended-wayland-1.4.9-aarch64.deb']
        lines=['Automation-State: complete','Upstream SHA: '+'a'*40,'Patch Set: '+patchset,'Patch Revision: v'+patchset[1:]+'.'+revision,
               'Common Patch Hash: '+'c'*64,'SOS Patch Hash: '+'c'*64,'Custom Repository SHA: '+'b'*40,
               'Wayland Included: '+str(included).lower(),'Build Identity: '+identity,'Asset Inventory: '+json.dumps(assets)]
        if policy:lines.append('Wayland Policy SHA256: '+policy)
        return dict(name=tag,tag_name='untagged-123',draft=True,prerelease=False,
            body='\n'.join(lines),assets=[dict(name=n,state='uploaded',size=1,digest='sha256:'+'a'*64) for n in assets])

    def test_existing_release_cannot_gain_wayland_without_new_identity(self):
        existing=self.draft_fixture()
        with patch.dict(os.environ,INCLUDE_WAYLAND='true'),patch.object(channel,'same_identity_release',return_value=existing),patch.object(channel,'api',return_value=existing):
            with self.assertRaisesRegex(ValueError,'immutable revision lacks matching Wayland'):
                channel.release_preflight(self.discovery())

    def test_discovery_only_does_not_query_drafts_or_resolve_sha_again(self):
        with patch.object(channel,'choose_stable',return_value={'version':'1.4.9','upstream_tag':'1.4.9','upstream_sha':'a'*40}),patch.object(channel,'api') as api,patch.object(channel,'outputs') as out:
            channel.resolve('stable',discovery_only=True)
            api.assert_not_called();self.assertNotIn('build_needed',out.call_args.args[0])

    def test_patch_revision_counters_are_independent(self):
        rows=[
            {'name':'v1.4.9-custom.v1.1'},
            {'name':'v1.4.9-custom.v1.2'},
            {'name':'v1.4.9-custom.v2.1'},
        ]
        with patch.object(channel,'release_rows',return_value=rows):
            self.assertEqual(channel.next_patch_revision('1.4.9','v1'),'v1.3')
            self.assertEqual(channel.next_patch_revision('1.4.9','v2'),'v2.2')
            self.assertEqual(channel.next_patch_revision('1.4.9','v3'),'v3.1')

    def test_same_build_identity_reuses_existing_patch_revision(self):
        existing=self.draft_fixture('v1','2')
        with patch.object(channel,'release_rows',return_value=[existing]),patch.object(channel,'api',return_value=existing):
            data=channel.release_preflight(self.discovery('v1'))
            self.assertFalse(data['build_needed'])
            self.assertFalse(data['draft_needed'])
            self.assertEqual(data['patch_revision'],'v1.2')
            self.assertEqual(data['release_tag'],'v1.4.9-custom.v1.2')

    def test_matching_draft_requires_exact_remote_asset_digests(self):
        existing=self.draft_fixture('v1','2')
        existing['assets'][0]['digest']=''
        with patch.object(channel,'release_rows',return_value=[existing]),patch.object(channel,'api',return_value=existing):
            with self.assertRaisesRegex(ValueError,'Existing release incomplete'):
                channel.release_preflight(self.discovery('v1'))

    def test_published_same_identity_is_idempotently_skipped(self):
        existing=self.draft_fixture('v1','2')
        existing.update(draft=False)
        existing['body']=existing['body'].replace('Automation-State: complete','automation_state=published')
        with patch.object(channel,'release_rows',return_value=[existing]),patch.object(channel,'api',return_value=existing):
            data=channel.release_preflight(self.discovery('v1'))
            self.assertFalse(data['build_needed'])
            self.assertFalse(data['draft_needed'])
            self.assertFalse(data['publish_existing'])

    def test_remote_sha256_manifest_must_match_github_asset_digests(self):
        import hashlib
        self._assets.stop()
        package=b'package';package_hash=hashlib.sha256(package).hexdigest()
        sums=(package_hash+'  package.deb\n').encode();sums_hash=hashlib.sha256(sums).hexdigest()
        assets=[{'name':'SHA256SUMS','state':'uploaded','size':len(sums),'digest':'sha256:'+sums_hash},
                {'name':'package.deb','state':'uploaded','size':len(package),'digest':'sha256:'+package_hash}]
        def download(args,**kwargs):
            Path(args[-1],'SHA256SUMS').write_bytes(sums)
        try:
            with patch.object(channel.subprocess,'run',side_effect=download):
                self.assertTrue(channel.verify_release_asset_checksums('v1.4.9-custom.v1.1',assets))
            bad=[dict(assets[0]),dict(assets[1],digest='sha256:'+'0'*64)]
            with patch.object(channel.subprocess,'run',side_effect=download):
                with self.assertRaisesRegex(ValueError,'do not match'):
                    channel.verify_release_asset_checksums('v1.4.9-custom.v1.1',bad)
        finally:
            self._assets.start()

    def test_custom_commit_and_wayland_selection_change_build_identity(self):
        base=self.discovery('v1')
        with patch.object(channel,'release_rows',return_value=[]),patch.object(channel,'api',return_value=None):
            first=channel.release_preflight(base)
        with patch.dict(os.environ,GITHUB_SHA='d'*40),patch.object(channel,'release_rows',return_value=[]),patch.object(channel,'api',return_value=None):
            changed_commit=channel.release_preflight(self.discovery('v1'))
        with patch.dict(os.environ,INCLUDE_WAYLAND='true'),patch.object(channel,'release_rows',return_value=[]),patch.object(channel,'api',return_value=None):
            changed_wayland=channel.release_preflight(self.discovery('v1'))
        self.assertNotEqual(first['build_identity'],changed_commit['build_identity'])
        self.assertNotEqual(first['build_identity'],changed_wayland['build_identity'])

    def test_switching_patchset_allocates_its_own_counter(self):
        existing_v1=self.draft_fixture('v1','2')
        rows=[existing_v1]
        with patch.object(channel,'release_rows',return_value=rows),patch.object(channel,'api',return_value=None):
            data=channel.release_preflight(self.discovery('v2'))
            self.assertTrue(data['build_needed'])
            self.assertTrue(data['draft_needed'])
            self.assertEqual(data['patch_revision'],'v2.1')
            self.assertEqual(data['release_tag'],'v1.4.9-custom.v2.1')

    def test_legacy_draft_without_automation_marker_is_rejected(self):
        draft=self.draft_fixture()
        draft['body']=draft['body'].replace('Automation-State: complete\n','')
        with patch.object(channel,'release_rows',return_value=[draft]),patch.object(channel,'api',return_value=draft):
            with self.assertRaisesRegex(ValueError,'missing its automation completion marker'):
                channel.release_preflight(self.discovery())

    def test_incomplete_or_mismatched_draft_blocks_before_build(self):
        draft=self.draft_fixture()
        draft['body']=draft['body'].replace('Automation-State: complete','Automation-State: incomplete')
        with patch.object(channel,'release_rows',return_value=[draft]),patch.object(channel,'api',return_value=draft),self.assertRaisesRegex(ValueError,'incomplete or incompatible'):
            channel.release_preflight(self.discovery())

    def test_release_preflight_workflow_permissions_and_gate(self):
        jobs=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())['jobs']
        self.assertNotIn('queue', jobs['android-sign'].get('concurrency', {}))
        self.assertEqual({n for n,j in jobs.items() if j.get('permissions',{}).get('contents')=='write'},{'draft-preflight','draft','release','publish-existing'})
        self.assertNotIn('qualification',jobs)
        self.assertNotIn('stable-ci-qualification',jobs)
        self.assertEqual(jobs['draft-preflight']['needs'],'resolve')
        self.assertIn('wayland_included',jobs['draft-preflight']['outputs'])
        self.assertIn('github.sha',jobs['publish-existing']['env']['CUSTOM_REPOSITORY_SHA'])
        self.assertIn('build_identity',jobs['publish-existing']['env']['BUILD_IDENTITY'])
        self.assertIn('github.sha',yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())['concurrency']['group'])
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
        self.assertEqual(jobs['aggregate']['needs'],['resolve','draft-preflight','windows-build','platforms-build','android-build','android-sign','wayland-build'])
        self.assertIn('--discovery-only',jobs['resolve']['steps'][1]['run'])
        for name in ('windows-build','platforms-build','android-build','android-sign','aggregate','release','draft'):
            self.assertNotIn('qualification',str(jobs[name].get('needs',[])))

    def test_windows_validation_receives_preflight_patch_revision(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/build-stable-windows.yml').read_text())
        validate_env=workflow['jobs']['validate']['env']
        self.assertEqual(validate_env['PATCH_REVISION'], '${{ inputs.revision }}')

    def test_stable_concurrency_and_ci_contract(self):
        tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())
        self.assertIn('github.sha',tag['concurrency']['group'])
        self.assertIn('inputs.include_wayland',tag['concurrency']['group'])
        self.assertFalse(tag['concurrency']['cancel-in-progress'])
        ci=yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
        concurrency=ci['concurrency']
        self.assertIn("inputs.automation_source == 'upstream-stable-router'",concurrency['group'])
        self.assertIn("'action-created-ci'",concurrency['group'])
        self.assertIn("format('normal-ci-{0}', github.ref)",concurrency['group'])
        self.assertIn("inputs.automation_source != 'upstream-stable-router'",concurrency['cancel-in-progress'])
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
        stable=yaml.safe_load((ROOT/'.github/workflows/upstream-stable.yml').read_text())
        tag=(ROOT/'.github/workflows/tag.yml').read_text()
        ci_text=(ROOT/'.github/workflows/ci.yml').read_text()
        self.assertNotIn('promote_stable',ci['on']['workflow_dispatch']['inputs'])
        self.assertNotIn('gh workflow run tag.yml',ci_text)
        stable_run=stable['jobs']['route']['steps'][-1].get('run','')
        self.assertEqual(stable_run,'python3 -m scripts.release.stable_router')
        router=(ROOT/'scripts/release/stable_router.py').read_text()
        self.assertNotIn('ci-qualification-',router)
        self.assertNotIn('workflow run ci.yml',router)
        self.assertIn("'gh', 'workflow', 'run', WORKFLOW",router)
        self.assertIn("'release_mode=draft'",router)
        self.assertIn("'include_wayland=true'",router)
        self.assertIn('release_preflight(data)',router)
        self.assertIn('wayland=${{ inputs.include_wayland',tag)
        self.assertNotIn('compat-check.yml',tag)
        self.assertNotIn('verify_source.py',tag)
        self.assertIn('Select Stable patchset by version boundary',tag)
        self.assertIn('patchsets.py --version "$UPSTREAM_VERSION"',tag)
        self.assertNotIn('--exact',tag)
        self.assertNotIn('ci-qualification',tag)
        self.assertTrue((ROOT/'.github/workflows/nightly.yml').exists())
        self.assertTrue((ROOT/'.github/workflows/upstream-nightly.yml').exists())

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

    def test_nightly_channel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'verified official-run Nightly resolver'):
            channel.resolve('nightly')

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

    def test_new_metadata_automation_state_is_accepted(self):
        sha='a'*40; common='c'*64
        identity=channel.build_identity(sha,'v999999',common,common,'b'*40,False)
        existing={
            'name':'v1.4.9-custom.v999999.1','tag_name':'v1.4.9-custom.v999999.1','draft':True,'prerelease':False,
            'body':chr(10).join(['Patch Set: v999999',f'Upstream SHA: {sha}',f'Common Patch Hash: {common}',f'SOS Patch Hash: {common}',
                'Custom Repository SHA: '+'b'*40,'Wayland Included: false','Patch Revision: v999999.1',
                'Build Identity: '+identity,'Asset Inventory: '+json.dumps(['SHA256SUMS','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']),
                'automation_state=complete']),
            'assets':[{'name':n,'state':'uploaded','size':1,'digest':'sha256:'+'a'*64} for n in ['SHA256SUMS','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']]
        }
        with patch.object(channel,'release_rows',return_value=[existing]),patch.object(channel,'api',return_value=existing):
            data=channel.release_preflight(self.discovery())
            self.assertFalse(data['build_needed'])
            self.assertTrue(data['publish_existing'])

    def test_changed_patch_allocates_new_scoped_revision(self):
        sha='a'*40
        with patch.object(channel,'release_rows',return_value=[{'name':'v1.4.9-custom.v999999.1'}]),patch.object(channel,'api',return_value=None):
            data=channel.release_preflight(self.discovery('v888888'))
            self.assertTrue(data['build_needed'])
            self.assertTrue(data['draft_needed'])
            self.assertEqual(data['patch_revision'],'v888888.1')
            self.assertEqual(data['release_tag'],'v1.4.9-custom.v888888.1')
            self.assertEqual(data['rebuild_reason'],'NEW_PATCH_REVISION')

    def test_upstream_main_compatibility_workflow_is_the_single_main_probe(self):
        path=ROOT/'.github/workflows/upstream-main-compatibility.yml'
        self.assertTrue(path.is_file())
        workflow=yaml.safe_load(path.read_text())
        self.assertIn('schedule',workflow['on'])
        self.assertIn('workflow_dispatch',workflow['on'])
        self.assertEqual(workflow['concurrency']['group'],'upstream-main-compatibility')
        jobs=workflow['jobs']
        self.assertEqual(jobs['compatibility']['uses'],'./.github/workflows/compat-check.yml')
        self.assertEqual(jobs['compatibility']['with']['upstream_repository'],'rustdesk/rustdesk')
        self.assertEqual(jobs['compatibility']['with']['channel'],'ci')
        resolve=jobs['resolve']
        resolve_text=str(resolve)
        self.assertIn('repos/rustdesk/rustdesk',resolve_text)
        self.assertIn('default_branch',resolve_text)
        self.assertIn('commits/',resolve_text)
        self.assertIn('40',resolve_text)
        self.assertNotIn('gh workflow run tag.yml',path.read_text())
        self.assertFalse((ROOT/'.github/workflows/upstream-main-sync.yml').exists())

    def test_entry_and_release_permissions(self):
        docs={p.name:yaml.safe_load(p.read_text()) for p in (ROOT/'.github/workflows').glob('*.yml')}
        self.assertIn('nightly.yml',docs)
        self.assertIn('upstream-nightly.yml',docs)
        self.assertTrue(all(j.get('permissions',{}).get('contents')!='write' for j in docs['ci.yml']['jobs'].values()))
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
