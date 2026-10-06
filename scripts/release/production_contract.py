#!/usr/bin/env python3
"""Release provenance, discovery, production-input and publication safety contracts."""
#!/usr/bin/env python3
"""Regression tests for discovery/dedup and the release provenance/security gate."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import scripts.upstream.resolve as upstream
import scripts.release.github as release

class DiscoveryTests(unittest.TestCase):
    def test_official_release_metadata_controls_stability(self):
        rows = [dict(id=1, tag_name='1.4.9', draft=False, prerelease=False),
                dict(id=2, tag_name='1.5.0', draft=False, prerelease=True),
                dict(id=3, tag_name='nightly', draft=False, prerelease=False),
                dict(id=4, tag_name='1.6.0', draft=True, prerelease=False)]
        with patch.object(upstream, 'api', return_value=rows), patch.object(upstream, 'resolve_ref', return_value='a'*40):
            self.assertEqual(upstream.choose_stable()['upstream_tag'], '1.4.9')
            with self.assertRaises(ValueError): upstream.choose_stable('1.5.0')
            with self.assertRaises(ValueError): upstream.choose_stable('a'*40)

    def discovery(self, completed=True, force=False):
        def api(path, missing=False):
            if '/releases/tags/' in path:
                if not completed: return None
                sos = '-sos-' in path
                return dict(prerelease=True, draft=False,
                    body=f'Patch Set: v1\nUpstream SHA: {"a"*40}\nCommon Patch Hash: {upstream.patch_hash("common")}\nSOS Patch Hash: {upstream.patch_hash("sos") if sos else "N/A"}\nAutomation-State: complete',
                    assets=[{'name': n} for n in ('client.zip','build-info.json','SHA256SUMS')])
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp, patch.object(upstream, 'api', side_effect=api), patch.object(upstream, 'mapped', return_value='v1'), \
             patch.object(upstream, 'choose_stable', return_value=dict(upstream_tag='1.4.9', version='1.4.9', upstream_sha='a'*40, official_release_id=1)), \
             patch.object(sys, 'argv', ['upstream.py', 'stable'] + (['--force'] if force else [])), \
             patch.dict(os.environ, {'GITHUB_OUTPUT': ''}), contextlib.redirect_stdout(io.StringIO()):
            previous=Path.cwd()
            try:
                os.chdir(tmp); upstream.main()
                return json.loads(Path('.work/discovery.json').read_text())
            finally: os.chdir(previous)

    def test_no_new_version_is_clean_no_build_no_publish(self):
        data=self.discovery(); self.assertFalse(data['build_needed']); self.assertFalse(data['publish_needed'])
    def test_new_stable_requests_build_and_publish(self):
        data=self.discovery(False); self.assertTrue(data['build_needed']); self.assertTrue(data['publish_needed'])
    def test_forced_existing_revision_never_overwrites_release(self):
        data=self.discovery(force=True); self.assertTrue(data['build_needed']); self.assertFalse(data['publish_needed'])

class ReleaseGateTests(unittest.TestCase):
    def payload(self, folder, variant):
        (folder/'rustdesk').mkdir(parents=True)
        pe=bytearray(128); pe[:2]=b'MZ'; struct.pack_into('<I',pe,0x3c,64); pe[64:68]=b'PE\0\0'; struct.pack_into('<H',pe,68,0x8664)
        (folder/'rustdesk/rustdesk.exe').write_bytes(pe)
        info=dict(patchset='v1',variant=variant, platform='windows-x86_64', upstream_sha='a'*40, upstream_tag='1.4.9',
                  custom_repository_sha='b'*40, common_patch_hash=upstream.patch_hash('common'),
                  sos_patch_hash=upstream.patch_hash('sos') if variant=='sos' else None,
                  workflow_run='42', patch_revision='1', signed=False, configuration='TEST ONLY',
                  runtime_ui_validation='SKIPPED BY USER',real_remote_session_validation='NOT TESTED')
        (folder/'build-info.json').write_text(json.dumps(info))
        self.sums(folder); return info
    def sums(self, folder):
        (folder/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(folder).as_posix()+'\n' for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
    def test_pair_requires_matching_source_and_both_variants(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'PATCHSET':'v1','GITHUB_RUN_ID':'','UPSTREAM_EXPECTED_SHA':'','UPSTREAM_TAG':'','GITHUB_SHA':''}):
            root=Path(tmp); self.payload(root/'standard','standard')
            with self.assertRaises(ValueError): release.collect(root)
            info=self.payload(root/'sos','sos'); release.collect(root)
            info['upstream_sha']='c'*40; (root/'sos/build-info.json').write_text(json.dumps(info)); self.sums(root/'sos')
            with self.assertRaises(ValueError): release.collect(root)
    def test_checksum_architecture_and_runtime_lies_block(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'PATCHSET':'v1','GITHUB_RUN_ID':'','UPSTREAM_EXPECTED_SHA':'','UPSTREAM_TAG':'','GITHUB_SHA':''}):
            folder=Path(tmp); info=self.payload(folder,'standard'); release.validate(folder)
            exe=folder/'rustdesk/rustdesk.exe'; data=bytearray(exe.read_bytes()); data[68:70]=b'\x4c\x01'; exe.write_bytes(data)
            with self.assertRaises(ValueError): release.validate(folder)
            self.sums(folder)
            with self.assertRaises(ValueError): release.validate(folder)
            info['runtime_ui_validation']='PASS'; (folder/'build-info.json').write_text(json.dumps(info)); self.sums(folder)
            with self.assertRaises(ValueError): release.validate(folder)


class GenerationTests(unittest.TestCase):
    def test_v1_hashes_frozen_and_exact_mapping(self):
        from scripts.upstream.patchsets import mapped, verify
        m=verify('v1')
        self.assertEqual(m['hashes']['common'],'87b7fb949b3bbc55c6d1e166909e167ebb8e0b6586630c0269f6440ba0542531')
        self.assertEqual(m['hashes']['sos'],'d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34')
        self.assertEqual(mapped('1.4.9'),'v1')
        self.assertEqual(mapped('1.5.0'),'v2')
        self.assertIsNone(mapped('9.9.9'))

    def test_unknown_incompatible_source_fails_closed(self):
        from scripts.upstream.patchsets import select
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir()
            subprocess.run(['git','init','--quiet',str(source)],check=True)
            (source/'README').write_text('Synthetic incompatible fixture; no real RustDesk source\n')
            subprocess.run(['git','-C',str(source),'add','README'],check=True)
            subprocess.run(['git','-C',str(source),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','--quiet','-m','test fixture'],check=True)
            sha=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
            report=Path(tmp)/'report.json'
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError,'NO COMPATIBLE PATCH SET'):
                select(sha,source,report)
            data=json.loads(report.read_text())
            self.assertIsNone(data['selected']);self.assertEqual(data['overall'],'FAIL')
            self.assertEqual({r['status'] for r in data['patchsets']},{'INCOMPATIBLE'})

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import scripts.release.production as production
import scripts.signing.production_config as config
import scripts.upstream.resolve as upstream
import scripts.release.github as release

class ProductionInputTests(unittest.TestCase):
    def values(self):
        return dict(RUSTDESK_ID_SERVER='id.example.com', RUSTDESK_RELAY_SERVER='relay.example.com',
                    RUSTDESK_API_SERVER='https://api.example.com', RUSTDESK_KEY='AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=',
                    RUSTDESK_PASSWORD='UNIT-TEST-PASSWORD-NOT-A-PRODUCTION-CREDENTIAL')

    def test_empty_relay_preserves_historical_discovery(self):
        for relay in ('', None):
            values = self.values()
            if relay is None:
                values.pop('RUSTDESK_RELAY_SERVER')
            else:
                values['RUSTDESK_RELAY_SERVER'] = relay
            with patch.dict(os.environ, values, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(config.configured()['RUSTDESK_RELAY_SERVER'], '')
                self.assertEqual(len(config.server_fingerprint()), 64)

    def test_input_never_prints_values(self):
        out = io.StringIO()
        with patch.dict(os.environ, self.values()), contextlib.redirect_stdout(out):
            config.configured()
        for value in self.values().values():
            self.assertNotIn(value, out.getvalue())

    def test_missing_fixture_and_credential_inputs_block(self):
        for change in ({'RUSTDESK_PASSWORD':''}, {'RUSTDESK_ID_SERVER':'test.invalid'},
                       {'RUSTDESK_PASSWORD':'ghp_'+'a'*36}, {'RUSTDESK_KEY':'-----BEGIN PRIVATE KEY-----'},
                       {'RUSTDESK_API_SERVER':'https://user:password@api.example.com'},
                       {'RUSTDESK_PASSWORD':'bad\nvalue'}):
            with patch.dict(os.environ, self.values() | change), self.assertRaises(ValueError):
                config.configured()

    def test_binary_credential_scan_covers_ascii_and_utf16(self):
        for value in ['ghp_'+'z'*36, '-----BEGIN OPENSSH PRIVATE KEY-----']:
            for encoding in ('utf-8', 'utf-16-le'):
                with self.assertRaises(ValueError): config.scan_bytes(value.encode(encoding))

class ProductionGateTests(ReleaseGateTests):
    def setUp(self):
        self.policy = patch.dict(os.environ, {"BUILD_CONFIGURATION":"PRODUCTION"})
        self.policy.start()
        self.addCleanup(self.policy.stop)

    def payload(self, folder, variant):
        info = super().payload(folder, variant)
        info.update(configuration='PRODUCTION', configuration_validation='PASS',
                    custom_repository='billradar/rustdesk-custom', architecture='x86_64',
                    server_config_fingerprint='e'*64,
                    password_configuration_validation='PASS',
                    password_validation_method='built-dll-native-bridge')
        (folder/'rustdesk/librustdesk.dll').write_bytes((folder/'rustdesk/rustdesk.exe').read_bytes())
        (folder/'build-info.json').write_text(json.dumps(info)); self.sums(folder)
        return info

    def test_production_payload_and_shared_server_gate(self):
        env = {'BUILD_CONFIGURATION':'PRODUCTION','PATCHSET':'v1','GITHUB_RUN_ID':'',
               'UPSTREAM_EXPECTED_SHA':'','UPSTREAM_TAG':'','GITHUB_SHA':''}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, env):
            root=Path(tmp); self.payload(root/'standard','standard'); info=self.payload(root/'sos','sos')
            release.collect(root)
            info['server_config_fingerprint']='f'*64
            (root/'sos/build-info.json').write_text(json.dumps(info)); self.sums(root/'sos')
            with self.assertRaisesRegex(ValueError,'configuration mismatch'):release.collect(root)

    def test_fictional_marker_and_private_key_block_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.payload(folder,'standard')
            for marker in (b'test.invalid', b'FICTIONAL-TEST-ONLY-Password-149', b'-----BEGIN PRIVATE KEY-----'):
                (folder/'rustdesk/leak.txt').write_bytes(marker)
                with self.assertRaises(ValueError):config.payload(folder)

class ProductionDiscoveryTests(unittest.TestCase):
    def discovery(self, existing=False, force=False, dry_run=False, partial=False):
        sha='6c578292e8ebbbec708b76986ba8c4bc7c509747'
        def api(path, missing=False):
            if '/git/ref/' in path: return None
            if not existing:return None
            names=['SHA256SUMS','build-info-standard.json','build-info-sos.json',
                   'rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']
            if partial:names.pop()
            return {'draft':False,'prerelease':False,'body':f'Upstream SHA: {sha}\nPatch Set: v1\nCommon Patch Hash: {upstream.patch_hash("common")}\nSOS Patch Hash: {upstream.patch_hash("sos")}\nAutomation-State: complete',
                    'assets':[{'name':x,'state':'uploaded'} for x in names]}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'GITHUB_REPOSITORY':production.REPOSITORY,'GITHUB_OUTPUT':''}), \
             patch.object(production,'choose_stable',return_value={'upstream_tag':'1.4.9','version':'1.4.9','upstream_sha':sha}), \
             patch.object(production,'api',side_effect=api),contextlib.redirect_stdout(io.StringIO()):
            prev=Path.cwd()
            try:
                os.chdir(tmp);return production.discover('1.4.9',force,dry_run)
            finally:os.chdir(prev)

    def test_new_stable_dryrun_cannot_publish(self):
        d=self.discovery(dry_run=True);self.assertTrue(d['build_needed']);self.assertFalse(d['publish_needed'])
    def test_existing_complete_release_skips_build(self):
        d=self.discovery(existing=True);self.assertFalse(d['build_needed']);self.assertFalse(d['publish_needed'])
    def test_force_never_overwrites(self):
        d=self.discovery(existing=True,force=True);self.assertTrue(d['build_needed']);self.assertFalse(d['publish_needed'])
    def test_incomplete_release_fails_closed(self):
        with self.assertRaises(ValueError):self.discovery(existing=True,partial=True)
    def test_wrong_repository_never_writes(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':'billradar/rustdesk'}), self.assertRaises(ValueError):
            production.publish(Path('.'), '')
    def test_first_release_without_dryrun_cannot_write(self):
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':production.REPOSITORY}),patch.object(production,'api',return_value=[]), \
             patch.object(production,'request') as writes,self.assertRaisesRegex(ValueError,'First production release'):
            production.publish(Path('.'), '')
        writes.assert_not_called()

    def test_completed_log_credential_blocks_before_publication(self):
        def api(path, **kwargs):
            if '/actions/runs/' in path:
                return {'jobs':[{'id':12,'status':'completed','conclusion':'success'}]}
            return [{'draft':False,'prerelease':False,'tag_name':'v1.4.9-custom.1',
                     'body':'Automation-State: complete'}]
        with patch.dict(os.environ,{'GITHUB_REPOSITORY':production.REPOSITORY,'GITHUB_RUN_ID':'43'}), \
             patch.object(production,'api',side_effect=api),patch.object(production,'gh',return_value='ghp_'+'a'*36), \
             patch.object(production,'request') as writes, self.assertRaisesRegex(ValueError,'credential'):
            production.publish(Path('.'), '')
        writes.assert_not_called()

class JobLogScanTests(unittest.TestCase):
    def test_ansi_logs_are_captured_and_scanned_without_output(self):
        out=io.StringIO()
        with patch.object(production,'gh',return_value='\x1b[32mFinished\x1b[0m'), contextlib.redirect_stdout(out) as output:
            production.scan_job_log(12)
            production.gh.assert_called_once_with('api','--allow-escape-sequences',f'repos/{production.REPOSITORY}/actions/jobs/12/logs')
        self.assertEqual(output.getvalue(),'')
    def test_color_split_credential_still_blocks(self):
        token='ghp_'+'a'*36
        formatted=token[:10]+'\x1b[32m'+token[10:]+'\x1b[0m'
        with patch.object(production,'gh',return_value=formatted), self.assertRaisesRegex(ValueError,'credential'):
            production.scan_job_log(12)
    def test_unreadable_log_blocks(self):
        import subprocess
        with patch.object(production,'gh',side_effect=subprocess.CalledProcessError(1,['gh','api'])), self.assertRaises(subprocess.CalledProcessError):
            production.scan_job_log(12)

if __name__ == "__main__": unittest.main()
