import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import production
import production_config as config
import upstream
import test_automation as automation
import release

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

class ProductionGateTests(automation.ReleaseGateTests):
    def setUp(self):
        self.policy = patch.dict(os.environ, {"BUILD_CONFIGURATION":"PRODUCTION"})
        self.policy.start()
        self.addCleanup(self.policy.stop)

    def payload(self, folder, variant):
        info = super().payload(folder, variant)
        info.update(configuration='PRODUCTION', configuration_validation='PASS',
                    custom_repository='billradar/rustdesk-custom', architecture='x86_64',
                    server_config_fingerprint='e'*64)
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
