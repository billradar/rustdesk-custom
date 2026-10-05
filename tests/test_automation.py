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
        from patchsets import mapped, verify
        m=verify('v1')
        self.assertEqual(m['hashes']['common'],'87b7fb949b3bbc55c6d1e166909e167ebb8e0b6586630c0269f6440ba0542531')
        self.assertEqual(m['hashes']['sos'],'d752022800a8008b10aedd1a79412a00af027464b1754b068c35a0b5b439ea34')
        self.assertEqual(mapped('6c578292e8ebbbec708b76986ba8c4bc7c509747'),'v1')
        self.assertIsNone(mapped('fada664df7a294d1d1a9ca3e7cd3637069122f17'))

    def test_unknown_incompatible_source_fails_closed(self):
        from patchsets import select
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

if __name__ == '__main__': unittest.main()
