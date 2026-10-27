#!/usr/bin/env python3
"""Nightly must follow exact official success and never open production signing."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.release import nightly, qualification
ROOT = Path(__file__).resolve().parents[2]


class NightlyTests(unittest.TestCase):
    def run_fixture(self):
        return dict(status='completed', conclusion='success', head_branch='master', event='schedule',
                    path='.github/workflows/flutter-nightly.yml', head_repository={'full_name':nightly.OFFICIAL},
                    head_sha='b'*40, id=17, html_url='https://github.com/rustdesk/rustdesk/actions/runs/17')

    def discover(self, run):
        def api(path):
            if path == 'repos/'+nightly.OFFICIAL:
                return {'default_branch':'master'}
            if '/contents/' in path:
                self.assertIn('?ref='+'b'*40,path)
                return {'content':base64.b64encode(b'[package]\nversion="1.5.1"\n').decode()}
            if '/workflows/' in path:
                return {'workflow_runs':[run]}
            return run
        with patch.object(nightly,'api',side_effect=api):
            return nightly.discover('17')

    def test_immutable_run_source_not_moving_nightly_tag(self):
        d=self.discover(self.run_fixture())
        self.assertEqual(d['upstream_sha'],'b'*40)
        self.assertEqual(d['upstream_ref'],d['upstream_sha'])
        self.assertEqual(d['upstream_tag'],'')
        self.assertEqual(d['patchset'],'v2')

    def test_failed_running_foreign_or_wrong_workflow_is_blocked(self):
        for k,v in [('status','in_progress'),('conclusion','failure'),('head_branch','other'),
                    ('event','pull_request'),('path','.github/workflows/ci.yml'),
                    ('head_repository',{'full_name':'attacker/fork'}),('head_sha','nightly')]:
            r=self.run_fixture();r[k]=v
            with self.assertRaises(ValueError):self.discover(r)

    def test_dedup_and_bounded_retries(self):
        data=dict(upstream_sha='b'*40,patchset='v2',common_patch_hash='c'*64,
                  sos_patch_hash='d'*64,wayland_policy_sha256='e'*64)
        identity=nightly.nightly_identity(data,'draft')
        row=dict(display_title='Nightly '+'b'*40+' / '+'a'*40+' / draft / wayland=true / android-signing=false',
                 _upstream_sha='b'*40, _nightly_identity=identity, head_sha='a'*40, event='workflow_dispatch',
                 head_branch='main', status='completed', conclusion='failure', id=21)
        state=lambda rows, build_id=identity:nightly.route_state(rows,build_id)
        self.assertEqual(state([]),'RETRY')
        self.assertEqual(state([row]*3),'EXHAUSTED')
        self.assertEqual(state([dict(row,conclusion='success')]),'SUCCESS')
        self.assertEqual(state([dict(row,status='queued')]),'ACTIVE')
        # A different custom commit or official run ID does not change patch identity.
        self.assertEqual(state([dict(row,head_sha='f'*40,id=22,conclusion='success')]),'SUCCESS')
        self.assertEqual(state([dict(row,_upstream_sha='c'*40)]),'RETRY')
        changed_patch=dict(data,common_patch_hash='f'*64)
        self.assertEqual(state([row],nightly.nightly_identity(changed_patch)),'RETRY')
        self.assertEqual(nightly.nightly_identity(data),nightly.nightly_identity(dict(data,custom_repository_sha='f'*40)))
        self.assertEqual(state([dict(row,display_title=row['display_title'].replace('/ draft /','/ dry-run /'))]),'RETRY')
        self.assertEqual(state([dict(row,display_title=row['display_title'].replace('wayland=true','wayland=false'))]),'RETRY')
        self.assertEqual(nightly.route_state([dict(row,id=99)],identity,current_run_id='99'),'RETRY')

    def test_matching_run_without_discovery_fails_closed(self):
        suffix=' / draft / wayland=true / android-signing=false'
        unknown=dict(display_title='Nightly '+'b'*40+' / '+'a'*40+suffix,
                     _upstream_sha='b'*40,_nightly_identity_unresolved=True,
                     event='workflow_dispatch',head_branch='main',status='completed',id=23)
        self.assertEqual(nightly.route_state([unknown], 'f'*64, upstream_sha='b'*40), 'UNKNOWN')
        active=dict(unknown,status='in_progress')
        self.assertEqual(nightly.route_state([active], 'f'*64, upstream_sha='b'*40), 'ACTIVE')
        other_source=dict(unknown,_upstream_sha='c'*40)
        self.assertEqual(nightly.route_state([other_source], 'f'*64, upstream_sha='b'*40), 'RETRY')

    def test_legacy_run_titles_recover_source_sha(self):
        old=dict(display_title='Nightly 17 / '+'a'*40+' / draft / wayland=true')
        with patch.object(nightly,'discover',return_value={'upstream_sha':'b'*40}):
            self.assertEqual(nightly.source_sha_from_run(old),'b'*40)
        modern=dict(display_title='Nightly '+'b'*40+' / '+'a'*40+' / draft / wayland=true / android-signing=false')
        self.assertEqual(nightly.source_sha_from_run(modern),'b'*40)

    def test_prior_history_ignores_later_queued_run(self):
        current=dict(id=10,run_number=10)
        later=dict(id=11,run_number=11,status='queued')
        self.assertEqual(nightly.prior_history([current,later],'10'),[])
        with self.assertRaisesRegex(ValueError,'missing from workflow history'):
            nightly.prior_history([later],'10')

    def test_unresolvable_legacy_official_run_does_not_abort_history(self):
        row=dict(display_title='Nightly 17 / '+'a'*40+' / draft / wayland=true')
        with patch.object(nightly,'discover',side_effect=ValueError('missing run')):
            self.assertEqual(nightly.source_sha_from_run(row),'')

    def test_annotate_marks_runs_without_discovery_as_unresolved(self):
        row=dict(display_title='Nightly '+'b'*40+' / '+'a'*40+' / draft / wayland=true / android-signing=false',
                 event='workflow_dispatch',head_branch='main',id=21)
        with patch.object(nightly,'source_sha_from_run',return_value='b'*40), \
             patch.object(nightly,'discovery_from_run',return_value=None):
            nightly.annotate_history([row], 'b'*40)
        self.assertTrue(row['_nightly_identity_unresolved'])

    def test_legacy_latest_without_discovery_stops_retries_conservatively(self):
        row=dict(display_title='Nightly latest / '+'a'*40+' / draft / wayland=true / android-signing=false',
                 event='workflow_dispatch',head_branch='main',status='completed',id=21)
        with patch.object(nightly,'source_sha_from_run',return_value=''), \
             patch.object(nightly,'discovery_from_run',return_value=None):
            nightly.annotate_history([row], 'b'*40)
        self.assertTrue(row['_nightly_identity_unresolved'])
        self.assertEqual(nightly.route_state([row],'f'*64,upstream_sha='b'*40), 'UNKNOWN')

    def test_manual_dedup_skips_active_or_successful_batch(self):
        env=dict(GITHUB_REPOSITORY='example/rustdesk-custom',GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='workflow_dispatch',
                 GITHUB_RUN_ID='99',GITHUB_SHA='a'*40,UPSTREAM_EXPECTED_SHA='b'*40,
                 UPSTREAM_VERSION='1.5.1',PATCHSET='v2',RELEASE_MODE='draft',INCLUDE_WAYLAND='true')
        row=dict(display_title='Nightly '+'b'*40+' / '+'a'*40+' / draft / wayland=true / android-signing=false',
                 _upstream_sha='b'*40,head_sha='a'*40,event='workflow_dispatch',head_branch='main',
                 status='completed',conclusion='success',id=21)
        current=dict(display_title='Nightly '+'b'*40+' / '+'a'*40+' / draft / wayland=true / android-signing=false',
                     head_sha='a'*40,event='workflow_dispatch',head_branch='main',
                     status='in_progress',conclusion='',id=99,run_number=12)
        row['run_number']=11
        artifact=dict(upstream_sha='b'*40,patchset='v2',common_patch_hash=nightly.patch_hash('common','v2'),
                      sos_patch_hash=nightly.patch_hash('sos','v2'),
                      wayland_policy_sha256=nightly.wayland_policy_hash(True))
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,dict(env,GITHUB_OUTPUT=str(Path(td)/'out'))), \
             patch.object(nightly,'api',return_value={'workflow_runs':[row,current]}), \
             patch.object(nightly,'discovery_from_run',return_value=artifact):
            nightly.dedup()
            self.assertIn('skip=true',(Path(td)/'out').read_text())

    def test_manual_and_scheduled_entrypoints_both_resolve_latest(self):
        for mode, event in [('resolve', 'workflow_dispatch'), ('route', 'schedule'), ('route', 'workflow_dispatch')]:
            with self.subTest(mode=mode, event=event), patch.dict(os.environ, GITHUB_EVENT_NAME=event), patch.object(nightly, 'discover', return_value={'upstream_sha': 'b'*40}) as discover, patch.object(nightly, 'save') as save, patch.object(nightly, 'route') as route:
                nightly.main([mode])
                discover.assert_called_once_with()
                save.assert_called_once_with({'upstream_sha': 'b'*40})
                self.assertEqual(route.call_count, int(mode == 'route'))

    def test_route_rejects_non_main_before_dispatch(self):
        with patch.dict(os.environ,GITHUB_REPOSITORY=nightly.REPO,GITHUB_REF='refs/heads/development',GITHUB_EVENT_NAME='workflow_dispatch'),patch.object(nightly,'api') as api:
            with self.assertRaises(ValueError):nightly.route({})
            api.assert_not_called()

    def test_route_dispatches_latest_successful_source(self):
        clone='example/rustdesk-custom'
        env=dict(GITHUB_REPOSITORY=clone,GITHUB_REF='refs/heads/main',GITHUB_EVENT_NAME='schedule',GITHUB_SHA='a'*40)
        with patch.dict(os.environ,env),patch.object(nightly,'api',return_value={'workflow_runs':[]}),patch.object(nightly.subprocess,'run') as dispatch:
            nightly.route({'official_run_id':'17','upstream_sha':'b'*40,'patchset':'v2',
                           'common_patch_hash':'c'*64,'sos_patch_hash':'d'*64})
            args=dispatch.call_args.args[0]
            self.assertFalse(any(x.startswith(('official_run_id=', 'expected_sha=')) for x in args))
            self.assertIn('release_mode=draft',args)
            self.assertEqual(args[args.index('--repo')+1],clone)
            self.assertEqual(args[args.index('--ref')+1],'main')

    def test_nightly_cannot_enter_stable_publication(self):
        with patch.object(qualification,'aggregate') as gate:
            with self.assertRaisesRegex(ValueError,'Only Stable'):
                qualification._release(Path('.'),True,'nightly')
            gate.assert_not_called()

    def test_matrix_matches_tag_and_excludes_dedicated_flavors(self):
        self.assertEqual({r['id'] for r in qualification.plan('nightly')['selected']},
                         {r['id'] for r in qualification.plan('stable')['selected']})
        self.assertFalse(any('wayland' in r['id'] for r in qualification.plan('nightly')['selected']))

    def test_aggregate_rejects_stale_channel_and_run_before_qualification(self):
        env=dict(UPSTREAM_EXPECTED_SHA='b'*40,UPSTREAM_VERSION='1.5.1',PATCHSET='v2',GITHUB_SHA='a'*40,GITHUB_RUN_ID='9')
        discovery=dict(channel='nightly',upstream_sha='b'*40,upstream_version='1.5.1',patchset='v2',upstream_repository=nightly.OFFICIAL)
        info=dict(discovery,custom_repository_sha='a'*40,common_patch_hash=nightly.patch_hash('common','v2'),build_run='9',upstream_tag='')
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,env),patch.object(qualification,'aggregate') as gate:
            root=Path(td);d=root/'discovery.json';d.write_text(json.dumps(discovery))
            for edit in [dict(channel='stable'),dict(build_run='8'),dict(custom_repository_sha='c'*40),dict(upstream_sha='c'*40),dict(upstream_tag='1.5.1')]:
                (root/'build-info.json').write_text(json.dumps(dict(info,**edit)))
                with self.assertRaises(ValueError):nightly.aggregate(root,d)
                gate.assert_not_called()

    def test_release_mode_requires_signed_android_aggregate(self):
        env=dict(UPSTREAM_EXPECTED_SHA='b'*40,UPSTREAM_VERSION='1.5.1',PATCHSET='v2',
                 GITHUB_SHA='a'*40,GITHUB_RUN_ID='9',RELEASE_MODE='release',
                 ANDROID_PRODUCTION_SIGNING_ENABLED='true')
        discovery=dict(channel='nightly',upstream_sha='b'*40,upstream_version='1.5.1',patchset='v2',upstream_repository=nightly.OFFICIAL,
                       official_run_id='17',official_run_url='https://github.com/rustdesk/rustdesk/actions/runs/17')
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,env):
            root=Path(td);(root/'.work/qualification-aggregate').mkdir(parents=True)
            (root/'discovery.json').write_text(json.dumps(discovery))
            for arch in ('aarch64','armv7','x86_64'):
                folder=root/arch;folder.mkdir()
                (folder/'build-info.json').write_text(json.dumps(dict(channel='nightly',upstream_sha='b'*40,upstream_version='1.5.1',patchset='v2',
                    custom_repository_sha='a'*40,common_patch_hash=nightly.patch_hash('common','v2'),build_run='9',upstream_tag='',platform='android',
                    signed_status='PRODUCTION SIGNED / IDENTITY VERIFIED',signing_identity_verified=True,signing_schemes=[2,3])))
            with patch.object(nightly,'ROOT',root),patch.object(qualification,'aggregate',return_value=dict(result='PASS')):
                report=nightly.aggregate(root,root/'discovery.json')
            self.assertTrue(report['android_production_signing'])
            self.assertEqual(os.environ['REQUIRE_ANDROID_PRODUCTION_SIGNING'],'true')

    def test_workflows_reuse_tag_cores_with_isolated_signing_and_draft(self):
        w=yaml.safe_load((ROOT/'.github/workflows/nightly.yml').read_text())
        self.assertEqual(w['permissions'],{'contents':'read','actions':'read'})
        self.assertEqual(set(w['on']),{'workflow_dispatch'})
        self.assertEqual(w['on']['workflow_dispatch']['inputs']['release_mode']['default'],'draft')
        self.assertEqual(w['on']['workflow_dispatch']['inputs']['release_mode']['options'],['dry-run','draft','release'])
        self.assertIn("github.ref == 'refs/heads/main'",w['jobs']['resolve']['if'])
        self.assertNotIn('billradar/rustdesk-custom',w['jobs']['resolve']['if'])
        self.assertTrue(w['run-name'].startswith('Nightly latest /'))
        self.assertEqual(set(w['on']['workflow_dispatch']['inputs']), {'release_mode', 'include_wayland'})
        resolve = next(s for s in w['jobs']['resolve']['steps'] if s.get('id') == 'resolve')
        self.assertEqual(resolve['run'], 'python3 scripts/release/nightly.py resolve')
        self.assertEqual(w['jobs']['resolve']['outputs']['dedup_skip'],'${{ steps.dedup.outputs.skip }}')
        self.assertIn('dedup',w['jobs']['resolve']['steps'][next(i for i,s in enumerate(w['jobs']['resolve']['steps']) if s.get('id')=='dedup')]['run'])
        discovery_upload=next(s for s in w['jobs']['resolve']['steps'] if s.get('uses','').startswith('actions/upload-artifact@'))
        self.assertEqual(discovery_upload['if'],'always()')
        self.assertEqual(discovery_upload['with']['if-no-files-found'],'warn')
        self.assertIn('needs.resolve.outputs.dedup_skip',w['jobs']['prepare']['if'])
        self.assertTrue(w['concurrency']['group'].startswith('nightly-latest-'))
        self.assertNotIn('github.sha',w['concurrency']['group'])
        for family in ['windows','platforms','android']:
            j=w['jobs'][family+'-build']
            self.assertEqual(j['uses'],'./.github/workflows/build-stable-'+family+'.yml')
            self.assertEqual(j['with']['channel'],'nightly')
            self.assertEqual(set(j['secrets']),{'RUSTDESK_KEY','RUSTDESK_PASSWORD'})
        for name,j in w['jobs'].items():
            if name!='android-sign':self.assertNotIn('environment',j)
            if name!='draft':self.assertNotIn('write',json.dumps(j.get('permissions',{})))
            if name!='android-sign':self.assertNotIn('YUBIKEY_PIV_PIN',json.dumps(j))
        signer=w['jobs']['android-sign'];tag=yaml.safe_load((ROOT/'.github/workflows/tag.yml').read_text())['jobs']['android-sign']
        for key in ['runs-on','environment','concurrency']:self.assertEqual(signer[key],tag[key])
        for name in ['android-sign','draft']:
            guard=w['jobs'][name]['if']
            for token in ["github.ref == 'refs/heads/main'","github.event_name == 'workflow_dispatch'","inputs.release_mode == 'draft'", "inputs.release_mode == 'release'","format('{0}/.github/workflows/nightly.yml@refs/heads/main', github.repository)"]:
                self.assertIn(token,guard)
        action=next(x for x in signer['steps'] if x.get('uses')=='./.github/actions/android-yubikey-sign')
        self.assertEqual(action['with']['channel'],'nightly')
        aggregate=w['jobs']['aggregate']
        self.assertEqual(set(aggregate['needs']),{'resolve','windows-build','platforms-build','android-build','wayland-build','android-sign'})
        self.assertIn("needs.android-sign.result == 'success'",aggregate['if'])
        self.assertIn("inputs.release_mode != 'dry-run'",aggregate['env']['REQUIRE_ANDROID_PRODUCTION_SIGNING'])
        self.assertIn("vars.ANDROID_PRODUCTION_SIGNING_ENABLED == 'true'",aggregate['env']['REQUIRE_ANDROID_PRODUCTION_SIGNING'])
        self.assertTrue(any('nightly.py aggregate' in s.get('run','') for s in aggregate['steps']))
        unsigned=next(x for x in aggregate['steps'] if x.get('with',{}).get('pattern')=='android-build-input-nightly-*')
        self.assertIn("inputs.release_mode == 'dry-run'",unsigned['if'])
        self.assertIn("vars.ANDROID_PRODUCTION_SIGNING_ENABLED != 'true'",unsigned['if'])
        draft=w['jobs']['draft']
        self.assertEqual(draft['permissions'],{'contents':'write','actions':'read'})
        self.assertEqual(draft['concurrency'],{'group':'rustdesk-nightly-release-write','cancel-in-progress':False})
        self.assertIn('aggregate',draft['needs'])
        self.assertTrue(any('nightly.py draft' in s.get('run','') for s in draft['steps']))
        for token in ['qualification.py release','secrets: inherit','continue-on-error']:
            self.assertNotIn(token,(ROOT/'.github/workflows/nightly.yml').read_text())

    def test_all_platform_review_happens_before_bridge_dependencies(self):
        w=yaml.safe_load((ROOT/'.github/workflows/prepare-source.yml').read_text())
        steps=w['jobs']['prepare']['steps']
        index=next(i for i,s in enumerate(steps) if 'nightly.py preflight' in s.get('run',''))
        self.assertEqual(steps[index]['if'],"inputs.channel == 'nightly'")
        self.assertLess(index,next(i for i,s in enumerate(steps) if s.get('name')=='Install official bridge prerequisites'))
        with patch.dict(os.environ,UPSTREAM_EXPECTED_SHA='b'*40),patch.object(nightly.subprocess,'check_output',return_value='c'*40):
            with self.assertRaisesRegex(ValueError,'SHA mismatch'):nightly.preflight(Path('.'))

    def test_polling_and_unique_plan_artifacts(self):
        w=yaml.safe_load((ROOT/'.github/workflows/upstream-nightly.yml').read_text())
        self.assertEqual(w['on']['schedule'],[{'cron':'0 12 * * *'}])
        self.assertIn("github.ref == 'refs/heads/main'",w['jobs']['route']['if'])
        self.assertEqual(w['jobs']['route']['permissions'],{'contents':'read','actions':'write'})
        self.assertEqual(w['jobs']['route']['timeout-minutes'],180)
        names=[]
        for family in ['platforms','android']:
            w=yaml.safe_load((ROOT/f'.github/workflows/build-stable-{family}.yml').read_text())
            names += [s['with']['name'] for s in w['jobs']['plan']['steps'] if s.get('uses','').startswith('actions/upload-artifact@')]
        self.assertEqual(len(names),len(set(names)))


class NightlyDraftTests(unittest.TestCase):
    def setUp(self):
        self.repo='example/rustdesk-custom'
        self.env={'GITHUB_REPOSITORY':self.repo,'GITHUB_REF':'refs/heads/main',
                  'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_WORKFLOW_REF':self.repo+'/.github/workflows/nightly.yml@refs/heads/main',
                  'RELEASE_MODE':'draft','GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'9',
                  'REQUIRE_ANDROID_PRODUCTION_SIGNING':'true'}
        self.data=dict(channel='nightly',upstream_sha='b'*40,upstream_version='1.5.1',patchset='v2',
                       official_run_id='17',official_run_url='https://github.com/rustdesk/rustdesk/actions/runs/17')
        self.upstream_notes='# This is a nightly build, which is built every day with the latest code.\n\nChangelog\n\n# Added\n\n- [Example change #123](https://github.com/rustdesk/rustdesk/pull/123)'

    def perform(self, mode='ok'):
        import hashlib
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env):
            root=Path(td);assets=root/'.work/qualification-aggregate/assets';assets.mkdir(parents=True)
            (assets/'client.apk').write_bytes(b'validated package fixture')
            (assets/'SHA256SUMS').write_text(hashlib.sha256((assets/'client.apk').read_bytes()).hexdigest()+'  client.apk\n')
            if mode == 'bad-checksum':
                (assets/'SHA256SUMS').write_text('0'*64 + '  client.apk\n')
            if mode == 'forbidden-json':
                (assets/'build-info-secret.json').write_text('{}')
            discovery=root/'discovery.json';discovery.write_text(json.dumps(self.data))
            uploaded=[dict(name=p.name,state='uploaded',size=p.stat().st_size,digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for p in assets.iterdir()]
            if mode=='bad-upload':uploaded[0]['digest']='sha256:'+'0'*64
            def api(path,missing=False):
                if path==f'repos/{nightly.OFFICIAL}/releases/tags/nightly':return {'name':'nightly','body':self.upstream_notes}
                if '/releases/tags/' in path:return {'id':7} if mode=='existing' else None
                if '/git/ref/tags/' in path:return None
                if '/releases?' in path:return []
                if '/actions/runs/' in path:return {'jobs':[]}
                if '/assets?' in path:return uploaded
                if path.endswith('/releases/7'):return {'id':7,'tag_name':'nightly','draft':True}
                raise AssertionError(path)
            report=dict(result='PASS',android_production_signing=mode!='unsigned')
            with patch.object(nightly,'ROOT',root),patch.object(nightly,'ASSETS',assets),patch.object(nightly,'aggregate',return_value=report),patch.object(nightly,'api',side_effect=api),patch.object(nightly.time,'sleep'),patch('scripts.release.github.gh') as upload,patch('scripts.release.github.request',return_value={'id':7,'draft':True,'prerelease':True,'tag_name':'nightly','target_commitish':'a'*40}) as write:
                if mode!='ok':
                    with self.assertRaises(ValueError):nightly.draft(root,discovery)
                    if mode in ['unsigned','existing','bad-checksum','forbidden-json']:write.assert_not_called()
                    if mode=='bad-upload':self.assertEqual(write.call_count,1)
                else:
                    result=nightly.draft(root,discovery)
                    self.assertTrue(result['draft']);self.assertTrue(result['prerelease'])
                    self.assertEqual(write.call_count,2)
                    for call in write.call_args_list:
                        self.assertTrue(call.args[2]['draft']);self.assertTrue(call.args[2]['prerelease'])
                    self.assertIn('automation_state=complete',write.call_args.args[2]['body'])
                    self.assertIn('<!-- rustdesk-custom-release-metadata',write.call_args.args[2]['body'])
                    self.assertTrue(write.call_args.args[2]['body'].startswith(self.upstream_notes+'\n\n<!-- rustdesk-custom-release-metadata'))
                    self.assertEqual(write.call_args.args[2]['name'],'nightly')
                    self.assertIn('asset_inventory=',write.call_args.args[2]['body'])
                    self.assertNotIn('--clobber',upload.call_args.args)
                    self.assertEqual(result['tag'], 'nightly')

    def test_create_verified_draft_only(self):self.perform()

    def test_complete_matching_draft_is_reused_unchanged(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,self.env):
            root=Path(td);assets=root/'.work/qualification-aggregate/assets';assets.mkdir(parents=True)
            (assets/'client.apk').write_bytes(b'validated package fixture')
            digest=hashlib.sha256((assets/'client.apk').read_bytes()).hexdigest()
            (assets/'SHA256SUMS').write_text(digest+'  client.apk\n')
            discovery=root/'discovery.json';discovery.write_text(json.dumps(self.data))
            remote=[dict(name=p.name,state='uploaded',size=p.stat().st_size,digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for p in assets.iterdir()]
            create_payload={}
            def first_request(method,path,payload):
                if method=='POST':create_payload.update(payload);return {'id':7,'draft':True,'prerelease':True,'tag_name':'nightly','target_commitish':'a'*40}
                if method=='PATCH':create_payload['body']=payload['body']
                return {'id':7,'draft':True,'prerelease':True}
            def first_api(path,missing=False):
                if path==f'repos/{nightly.OFFICIAL}/releases/tags/nightly':return {'name':'nightly','body':self.upstream_notes}
                if '/releases/tags/' in path or '/git/ref/tags/' in path:return None
                if '/actions/runs/' in path:return {'jobs':[]}
                if '/assets?' in path:return remote
                if path.endswith('/releases/7'):return {'id':7,'tag_name':'nightly','draft':True}
                raise AssertionError(path)
            with patch.object(nightly,'ROOT',root),patch.object(nightly,'ASSETS',assets),patch.object(nightly,'aggregate',return_value=dict(result='PASS',android_production_signing=True)),patch.object(nightly,'api',side_effect=first_api),patch.object(nightly.time,'sleep'),patch('scripts.release.github.gh'),patch('scripts.release.github.request',side_effect=first_request):
                first=nightly.draft(root,discovery)
            def reused_api(path,missing=False):
                if path==f'repos/{nightly.OFFICIAL}/releases/tags/nightly':return {'name':'nightly','body':self.upstream_notes}
                if '/releases/tags/' in path:return {'id':7,'name':'nightly','draft':True,'prerelease':True,'body':create_payload['body']}
                if '/git/ref/tags/' in path:return {'object':{'sha':'a'*40}}
                if '/actions/runs/' in path:return {'jobs':[]}
                if '/assets?' in path:return remote
                return None
            with patch.object(nightly,'ROOT',root),patch.object(nightly,'ASSETS',assets),patch.object(nightly,'aggregate',return_value=dict(result='PASS',android_production_signing=True)),patch.object(nightly,'api',side_effect=reused_api),patch('scripts.release.github.request') as write:
                second=nightly.draft(root,discovery)
                self.assertTrue(second['reused'])
                self.assertEqual(second['tag'],first['tag'])
                write.assert_not_called()

    def test_release_mode_promotes_only_a_complete_matching_draft(self):
        import hashlib
        env=dict(self.env)
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,env):
            root=Path(td);assets=root/'.work/qualification-aggregate/assets';assets.mkdir(parents=True)
            (assets/'client.apk').write_bytes(b'validated package fixture')
            digest=hashlib.sha256((assets/'client.apk').read_bytes()).hexdigest()
            (assets/'SHA256SUMS').write_text(digest+'  client.apk\n')
            discovery=root/'discovery.json';discovery.write_text(json.dumps(self.data))
            remote=[dict(name=p.name,state='uploaded',size=p.stat().st_size,digest='sha256:'+hashlib.sha256(p.read_bytes()).hexdigest()) for p in assets.iterdir()]
            create_payload={}
            def first_request(method,path,payload):
                if method=='POST':create_payload.update(payload);return {'id':7,'draft':True,'prerelease':True,'tag_name':'nightly','target_commitish':'a'*40}
                if method=='PATCH':create_payload['body']=payload['body']
                return {'id':7,'draft':True,'prerelease':True}
            def first_api(path,missing=False):
                if path==f'repos/{nightly.OFFICIAL}/releases/tags/nightly':return {'name':'nightly','body':self.upstream_notes}
                if '/releases/tags/' in path or '/git/ref/tags/' in path:return None
                if '/actions/runs/' in path:return {'jobs':[]}
                if '/assets?' in path:return remote
                if path.endswith('/releases/7'):return {'id':7,'tag_name':'nightly','draft':True}
                raise AssertionError(path)
            with patch.object(nightly,'ROOT',root),patch.object(nightly,'ASSETS',assets),patch.object(nightly,'aggregate',return_value=dict(result='PASS',android_production_signing=True)),patch.object(nightly,'api',side_effect=first_api),patch.object(nightly.time,'sleep'),patch('scripts.release.github.gh'),patch('scripts.release.github.request',side_effect=first_request):
                nightly.draft(root,discovery)
            def reused_api(path,missing=False):
                if path==f'repos/{nightly.OFFICIAL}/releases/tags/nightly':return {'name':'nightly','body':self.upstream_notes}
                if '/releases/tags/' in path:return {'id':7,'name':'nightly','draft':True,'prerelease':True,'body':create_payload['body']}
                if '/git/ref/tags/' in path:return {'object':{'sha':'a'*40}}
                if '/actions/runs/' in path:return {'jobs':[]}
                if '/assets?' in path:return remote
                return None
            with patch.dict(os.environ,RELEASE_MODE='release'),patch.object(nightly,'ROOT',root),patch.object(nightly,'ASSETS',assets),patch.object(nightly,'aggregate',return_value=dict(result='PASS',android_production_signing=True)),patch.object(nightly,'api',side_effect=reused_api),patch('scripts.release.github.request',return_value={'draft':False,'prerelease':True}) as write:
                result=nightly.draft(root,discovery)
                self.assertTrue(result['reused'])
                self.assertFalse(result['draft'])
                write.assert_called_once()
                self.assertEqual(write.call_args.args[0],'PATCH')

    def test_release_mode_publishes_only_after_verified_upload(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,dict(self.env,RELEASE_MODE='release')):
            root=Path(td);assets=root/'.work/qualification-aggregate/assets';assets.mkdir(parents=True)
            (assets/'client.apk').write_bytes(b'validated package fixture')
            (assets/'SHA256SUMS').write_text(hashlib.sha256((assets/'client.apk').read_bytes()).hexdigest()+'  client.apk\n')
            discovery=root/'discovery.json';discovery.write_text(json.dumps(self.data))
            uploaded=[dict(name=x.name,state='uploaded',size=x.stat().st_size,digest='sha256:'+hashlib.sha256(x.read_bytes()).hexdigest()) for x in assets.iterdir()]
            def api(path,missing=False):
                if path==f'repos/{nightly.OFFICIAL}/releases/tags/nightly':return {'name':'nightly','body':self.upstream_notes}
                if '/releases/tags/' in path or '/git/ref/tags/' in path:return None
                if '/releases?' in path:return []
                if '/actions/runs/' in path:return {'jobs':[]}
                if '/assets?' in path:return uploaded
                if path.endswith('/releases/7'):return {'id':7,'tag_name':'nightly','draft':True}
                raise AssertionError(path)
            calls=[]
            def request(method,path,payload):
                calls.append((method,payload))
                if method=='POST':return {'id':7,'draft':True,'prerelease':True,'tag_name':'nightly','target_commitish':'a'*40}
                return {'id':7,**payload}
            with patch.object(nightly,'ROOT',root),patch.object(nightly,'ASSETS',assets),patch.object(nightly,'aggregate',return_value={'result':'PASS','android_production_signing':True}),patch.object(nightly,'api',side_effect=api),patch('scripts.release.github.gh'),patch('scripts.release.github.request',side_effect=request):
                result=nightly.draft(root,discovery)
            self.assertEqual([x[0] for x in calls],['POST','PATCH'])
            self.assertTrue(calls[0][1]['draft'])
            self.assertFalse(calls[1][1]['draft'])
            self.assertTrue(calls[1][1]['prerelease'])
            self.assertFalse(result['draft'])
            self.assertIn('automation_state=complete',calls[1][1]['body'])
    def test_unsigned_matrix_blocks_all_writes(self):self.perform('unsigned')
    def test_existing_release_never_overwritten(self):self.perform('existing')
    def test_bad_upload_digest_cannot_mark_draft_complete(self):self.perform('bad-upload')
    def test_bad_checksums_block_publication(self):self.perform('bad-checksum')
    def test_nonpublic_json_blocks_publication(self):self.perform('forbidden-json')

    def test_wrong_branch_event_or_mode_blocks_before_validation(self):
        for key,value in [('GITHUB_REF','refs/heads/development'),('GITHUB_EVENT_NAME','pull_request'),('RELEASE_MODE','dry-run')]:
            with patch.dict(os.environ,dict(self.env,**{key:value})),patch.object(nightly,'aggregate') as validate:
                with self.assertRaises(ValueError):nightly.draft(Path('.'),Path('.'))
                validate.assert_not_called()


if __name__ == '__main__':unittest.main()
