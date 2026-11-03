"""Independent content versions and shared-identity release integration."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from scripts.release import content, channel, nightly
from scripts.release.coordinator.identity import BuildIdentity, SourceIdentity


class ContentContract(unittest.TestCase):
    def test_revision_and_policy_are_shared_build_identity_inputs(self):
        source = SourceIdentity('a'*40, 'v2', 'b'*64, 'c'*64)
        for name in ('stable','nightly'):
            old = BuildIdentity(name, source, False, '', False)
            modern = replace(old, policy_version=2, patchset_version='v2.7', build_policy_sha256='d'*64)
            self.assertNotEqual(old.key, modern.key)
            self.assertNotEqual(modern.key, replace(modern, patchset_version='v2.9').key)
            self.assertNotEqual(modern.key, replace(modern, build_policy_sha256='e'*64).key)
            data = dict(upstream_sha=source.upstream_sha, patchset='v2', common_patch_hash='b'*64,
                        sos_patch_hash='c'*64, patchset_version='v2.7', build_policy_sha256='d'*64)
            if name == 'stable':
                digest = channel.build_identity(source.upstream_sha,'v2','b'*64,'c'*64,
                    wayland_included=False, patchset_version='v2.7',build_policy_sha256='d'*64)
            else:
                digest = nightly.nightly_identity(data, 'draft', 'false', 'false')
            self.assertEqual(digest, modern.historical_digest)

    def test_nightly_reads_same_revision_without_mutating_metadata(self):
        import base64
        before = (content.ROOT / 'patchsets/v2/patchset.json').read_bytes()
        run = dict(id=17, status='completed', conclusion='success', head_branch='master',
                   event='schedule', path='.github/workflows/flutter-nightly.yml', head_sha='a'*40,
                   head_repository={'full_name':nightly.OFFICIAL}, html_url='https://github.com/rustdesk/rustdesk/actions/runs/17')
        def api(path):
            if path == 'repos/'+nightly.OFFICIAL:
                return {'default_branch':'master'}
            if '/contents/' in path:
                return {'content':base64.b64encode(b'[package]\nversion="1.5.1"\n').decode()}
            return {'workflow_runs':[run]}
        with patch.object(nightly,'api',side_effect=api):
            for _ in range(3):
                data=nightly.discover()
                self.assertEqual(data['patchset_version'],content.inputs('v2')['patchset_version'])
        self.assertEqual(before,(content.ROOT / 'patchsets/v2/patchset.json').read_bytes())

    def test_upstream_version_does_not_allocate_revision(self):
        self.assertEqual(channel.next_patch_revision('1.5.0','v2'), channel.next_patch_revision('1.5.1','v2'))

    def test_notes_are_deterministic_and_separate_inventory_from_delta(self):
        stable = content.notes('v2')
        self.assertEqual(stable, content.notes('v2'))
        self.assertIn('Current included customizations', stable)
        self.assertIn('Recorded Patchset revision delta', stable)
        self.assertIn('Kind: content-change', stable)
        self.assertIn('not claims of new changes', content.notes('v2', nightly=True))

    def test_cutover_has_no_environment_boolean_bypass(self):
        with patch.dict(os.environ, PATCHSET_CUTOVER_ENABLED='true'):
            with self.assertRaisesRegex(ValueError, 'CUTOVER_REVIEW_REQUIRED'):
                content.require_cutover()

    def test_cutover_remains_blocked_even_if_metadata_status_is_changed(self):
        # A metadata-only PR must never be able to activate production v2.
        with tempfile.TemporaryDirectory() as directory:
            gate = Path(directory) / 'patchset-cutover.json'
            for status in ('BLOCKED', 'READY', 'GO', 'ACTIVE'):
                gate.write_text(json.dumps({
                    'schema': 'patchset-cutover-v1',
                    'status': status,
                    'blockers': [],
                }))
                with patch.object(content, 'CUTOVER', gate):
                    with self.assertRaisesRegex(ValueError, 'PATCHSET_CUTOVER_REVIEW_REQUIRED'):
                        content.require_cutover()

    def test_active_cutover_requires_digest_pinned_complete_attestation(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'metadata/release/attestations'
            folder.mkdir(parents=True)
            evidence_path = folder / 'content-v2.json'
            evidence = dict(schema='content-v2-activation-attestation-v1', decision='GO',
                            v2_only=True, journal_reconciled=True, workers_quiescent=True,
                            releases_inventoried=True, version_gate_passed=True)
            raw = json.dumps(evidence).encode()
            evidence_path.write_bytes(raw)
            gate = root / 'patchset-cutover.json'
            value = dict(schema='patchset-cutover-v1', status='ACTIVE', blockers=[],
                         activation_evidence=dict(path='metadata/release/attestations/content-v2.json',
                                                  sha256=hashlib.sha256(raw).hexdigest()))
            gate.write_text(json.dumps(value))
            with patch.object(content, 'ROOT', root), patch.object(content, 'CUTOVER', gate):
                content.require_cutover()
                evidence['workers_quiescent'] = False
                changed = json.dumps(evidence).encode()
                evidence_path.write_bytes(changed)
                value['activation_evidence']['sha256'] = hashlib.sha256(changed).hexdigest()
                gate.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'incomplete activation evidence'):
                    content.require_cutover()
                value['activation_evidence']['sha256'] = '0' * 64
                gate.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'evidence digest mismatch'):
                    content.require_cutover()

    def test_policy_hash_changes_for_toolchain_but_not_docs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'requirements.txt').write_text('dependencies')
            (root/'scripts/build').mkdir(parents=True)
            sdk=root/'scripts/build/sdk.sh';sdk.write_text('SDK=1')
            first=content.policy_digest(root)
            (root/'README.md').write_text('documentation')
            self.assertEqual(first, content.policy_digest(root))
            sdk.write_text('SDK=2')
            self.assertNotEqual(first, content.policy_digest(root))

    def test_policy_matches_lf_and_crlf_git_checkouts(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / 'source'
            source.mkdir()
            def git(*args, cwd=source):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.PIPE)
            git('init', '-q')
            git('config', 'user.name', 'Contract')
            git('config', 'user.email', 'contract@example.invalid')
            git('config', 'core.autocrlf', 'false')
            (source / '.gitattributes').write_bytes(b'* text=auto\n')
            files = {
                'requirements.txt': b'dependency==1\n',
                'scripts/build/SDK.sh': b'SDK=1\necho ready\n',
                'scripts/build/sdk-helper.py': b'print("ready")\n',
                'metadata/build/profile.json': b'{"sdk": 1}\n',
                '.github/actions/example/action.yml': b'name: example\n',
                '.github/workflows/build.yml': b'name: build\n',
                '.github/actions/example/payload.bin': b'\x00binary\r\n\xff',
            }
            for name, raw in files.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            git('add', '.')
            git('commit', '-qm', 'canonical inputs')
            expected = git('rev-parse', 'HEAD')
            checkouts = []
            for name, setting in [('lf', 'false'), ('crlf', 'true')]:
                destination = base / name
                git('clone', '-q', '--no-hardlinks', '--config', 'core.autocrlf='+setting,
                    str(source), str(destination), cwd=base)
                self.assertEqual(git('rev-parse', 'HEAD', cwd=destination), expected)
                checkouts.append(destination)
            lf, crlf = checkouts
            self.assertEqual((lf/'scripts/build/SDK.sh').read_bytes(), files['scripts/build/SDK.sh'])
            self.assertEqual((crlf/'scripts/build/SDK.sh').read_bytes(), files['scripts/build/SDK.sh'].replace(b'\n', b'\r\n'))
            self.assertEqual(content.policy_digest(lf), content.policy_digest(crlf))
            # Binary bytes still bind identity, even when CRLF is the only change.
            payload = crlf / '.github/actions/example/payload.bin'
            payload.write_bytes(payload.read_bytes().replace(b'\r\n', b'\n'))
            self.assertNotEqual(content.policy_digest(lf), content.policy_digest(crlf))

    def fixture(self):
        inputs=content.inputs('v2')
        common=channel.patch_hash('common','v2');sos=channel.patch_hash('sos','v2')
        identity=channel.build_identity('a'*40,'v2',common,sos,wayland_included=False,
            patchset_version=inputs['patchset_version'],build_policy_sha256=inputs['build_policy_sha256'])
        tag='v1.5.1-custom.'+inputs['patchset_version']
        names=['SHA256SUMS','rustdesk-1.5.1-standard-windows-x86_64.zip','rustdesk-1.5.1-sos-windows-x86_64.zip']
        body='\n'.join(['Automation-State: complete','Upstream SHA: '+'a'*40,'Patch Set: v2',
            'Common Patch Hash: '+common,'SOS Patch Hash: '+sos,'Patch Revision: '+inputs['patchset_version'],
            'Build Identity: '+identity,'Wayland Included: false','version_semantics=patchset-content-v1',
            'Asset Inventory: '+json.dumps(names)])
        return dict(tag_name=tag,name=tag,draft=True,prerelease=False,body=body,
                    assets=[dict(name=n,state='uploaded',size=1,digest='sha256:'+'b'*64) for n in names])

    def test_same_tag_identity_reuses_existing_asset_gates(self):
        existing=self.fixture()
        data=dict(channel='stable',version='1.5.1',upstream_tag='1.5.1',upstream_ref='1.5.1',
                  upstream_sha='a'*40,patchset='v2')
        with patch.dict(os.environ,GITHUB_SHA='f'*40,INCLUDE_WAYLAND='false',ANDROID_PRODUCTION_SIGNING_ENABLED='false'),\
             patch.object(channel,'api',return_value=existing),\
             patch.object(channel,'verify_release_asset_checksums') as checks:
            result=channel.release_preflight(data)
            self.assertFalse(result['build_needed'])
            self.assertTrue(result['publish_existing'])
            checks.assert_called_once()

    def test_same_tag_different_identity_rejects_without_bump(self):
        existing=self.fixture();existing['body']=existing['body'].replace('Build Identity: ', 'Build Identity: '+'e'*64+'\nold=')
        data=dict(channel='stable',version='1.5.1',upstream_tag='1.5.1',upstream_ref='1.5.1',
                  upstream_sha='a'*40,patchset='v2')
        with patch.dict(os.environ,GITHUB_SHA='f'*40,INCLUDE_WAYLAND='false'),patch.object(channel,'api',return_value=existing):
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_TAG_BUILD_IDENTITY_COLLISION'):
                channel.release_preflight(data)


if __name__ == '__main__':
    unittest.main()
