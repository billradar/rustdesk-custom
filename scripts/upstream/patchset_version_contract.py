"""Git-backed allocation, immutable history and changelog contracts."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from scripts.upstream import patchset_version as version


class VersionContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(version.ROOT / 'patchsets/v2', self.root / 'patchsets/v2')
        self.run_git('init', '-q')
        self.run_git('config', 'user.name', 'Contract')
        self.run_git('config', 'user.email', 'contract@example.invalid')
        self.save_commit()
        self.base = version.commit('HEAD', self.root)
        self.old = version.manifest('v2', self.root)

    def run_git(self, *args):
        return version.git(*args, root=self.root)

    def save_commit(self):
        self.run_git('add', '.')
        self.run_git('commit', '-qm', 'fixture')

    def change(self, *folders):
        for folder in folders:
            p = next((self.root / f'patchsets/v2/{folder}').glob('*.patch'))
            p.write_bytes(p.read_bytes() + b'\ncontract content change\n')

    def write(self, data):
        (self.root / 'patchsets/v2/patchset.json').write_text(json.dumps(data, indent=2)+'\n')
        (self.root / 'patchsets/v2/CHANGELOG.md').write_text(version.render(data))

    def reviewed(self):
        data = version.manifest('v2', self.root)
        entry = data['versioning']['history'][-1]
        entry.update(reason='Fix fixture behavior for the documented reason.', compatibility='Same version selection boundary.',
                     limitations='Runtime not tested.', references=[self.base], review_status='reviewed')
        entry['categories']['Fixed'] = ['Correct fixture behavior.']
        self.write(data)
        return data

    def test_new_candidate_generation_requires_exact_parent_and_base(self):
        shutil.copytree(version.ROOT / 'patchsets/v3', self.root / 'patchsets/v3')
        target = self.root / 'patchsets/v3/patchset.json'
        data = json.loads(target.read_text())
        # Reconstruct the original candidate fixture, not live v3's later revisions.
        shutil.copy2(version.ROOT/'patchsets/v2/common/0005-custom-release-updates.patch', target.parent/'common/0005-custom-release-updates.patch')
        data['revision'] = 1
        data['hashes'] = copy.deepcopy(data['versioning']['history'][0]['after'])
        data['versioning']['history'] = [data['versioning']['history'][0]]
        data['status'] = 'candidate_only'  # This fixture creates a new generation, unlike live v3.
        data['versioning']['migration_base'] = self.base
        data['versioning']['history'][0]['base_sha'] = self.base
        def write():
            target.write_text(json.dumps(data))
            (target.parent / 'CHANGELOG.md').write_text(version.render(data))
        write()
        self.assertEqual(version.verify('v3', self.base, self.root)['result'], 'PASS')
        data['status'] = 'validation_pending'
        write()
        with self.assertRaisesRegex(ValueError, 'isolated candidate baseline'):
            version.verify('v3', self.base, self.root)
        data['status'] = 'candidate_only'
        data['derived_from']['revision'] += 1
        write()
        with self.assertRaisesRegex(ValueError, 'isolated candidate baseline'):
            version.verify('v3', self.base, self.root)

    def test_each_content_scope_increments_exactly_once(self):
        for folders in [('common',), ('sos',), ('common', 'sos')]:
            with self.subTest(folders=folders):
                # Restore bytes without rewriting any shared repository refs.
                shutil.rmtree(self.root / 'patchsets/v2')
                shutil.copytree(version.ROOT / 'patchsets/v2', self.root / 'patchsets/v2')
                self.change(*folders)
                first = version.bump('v2', self.base, root=self.root)
                version.bump('v2', self.base, root=self.root)
                data = self.reviewed()
                self.assertEqual(first['patchset_version'], f'v2.{self.old["revision"]+1}')
                self.assertEqual(data['versioning']['history'][-1]['scopes'], list(folders))
                self.assertEqual(version.verify('v2', self.base, self.root)['result'], 'PASS')

    def test_docs_ci_upstream_and_compatibility_do_not_increment(self):
        for filename in ('README.md', 'ci.yml', 'upstream.json'):
            (self.root / filename).write_text('changed')
        data = version.manifest('v2', self.root)
        data['compatibility_snapshots'] = []
        self.write(data)
        self.assertFalse(version.verify('v2', self.base, self.root)['content_changed'])
        with self.assertRaisesRegex(ValueError, 'No patch'):
            version.bump('v2', self.base, root=self.root)

    def test_unversioned_patch_change_rejected(self):
        self.change('common')
        with self.assertRaises(ValueError):
            version.verify('v2', self.base, self.root)

    def test_revision_without_content_rejected(self):
        data = version.manifest('v2', self.root)
        data['revision'] += 1
        self.write(data)
        with self.assertRaises(ValueError):
            version.verify('v2', self.base, self.root)

    def test_pending_semantics_and_missing_changelog_fail(self):
        self.change('sos')
        version.bump('v2', self.base, root=self.root)
        with self.assertRaisesRegex(ValueError, 'reviewed'):
            version.verify('v2', self.base, self.root)
        self.reviewed()
        (self.root / 'patchsets/v2/CHANGELOG.md').unlink()
        with self.assertRaisesRegex(ValueError, 'Changelog'):
            version.verify('v2', self.base, self.root)

    def test_history_cannot_be_modified(self):
        self.change('common')
        version.bump('v2', self.base, root=self.root)
        data = self.reviewed()
        data['versioning']['history'][0]['reason'] = 'Rewrite history'
        self.write(data)
        with self.assertRaisesRegex(ValueError, 'Historical'):
            version.verify('v2', self.base, self.root)

    def test_reversion_gets_new_number(self):
        self.change('common')
        version.bump('v2', self.base, root=self.root)
        self.reviewed()
        self.save_commit()
        newer = version.commit('HEAD', self.root)
        for path in (version.ROOT / 'patchsets/v2/common').glob('*.patch'):
            shutil.copyfile(path, self.root / 'patchsets/v2/common' / path.name)
        version.bump('v2', newer, root=self.root)
        data = self.reviewed()
        self.assertEqual(data['revision'], self.old['revision'] + 2)
        self.assertEqual(data['hashes'], self.old['hashes'])
        version.verify('v2', newer, self.root)

    def test_concurrent_old_base_cannot_reuse_number(self):
        self.change('common')
        version.bump('v2', self.base, root=self.root)
        self.reviewed()
        self.save_commit()
        latest = version.commit('HEAD', self.root)
        self.change('sos')
        # A PR that still believes its allocation is based on the old main.
        with self.assertRaises(ValueError):
            version.verify('v2', latest, self.root)
        version.bump('v2', latest, root=self.root)
        self.reviewed()
        self.assertEqual(version.verify('v2', latest, self.root)['result'], 'PASS')

    def test_read_only_check_and_line_endings(self):
        self.change('common')
        before = version.manifest('v2', self.root)
        result = version.bump('v2', self.base, check=True, root=self.root)
        self.assertFalse(result['written'])
        self.assertEqual(before, version.manifest('v2', self.root))
        first = version.hashes('v2', self.root)
        p = next((self.root / 'patchsets/v2/common').glob('*.patch'))
        p.write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))
        self.assertEqual(first, version.hashes('v2', self.root))

    def test_retired_unversioned_base_never_reactivates_cutover(self):
        data = version.manifest('v2', self.root)
        del data['versioning']
        (self.root / 'patchsets/v2/patchset.json').write_text(json.dumps(data))
        self.save_commit()
        old_sha = version.commit('HEAD', self.root)
        shutil.rmtree(self.root / 'patchsets/v2')
        shutil.copytree(version.ROOT / 'patchsets/v2', self.root / 'patchsets/v2')
        with self.assertRaisesRegex(ValueError, 'Unversioned Patchset base is retired'):
            version.verify('v2', old_sha, self.root)



if __name__ == '__main__':
    unittest.main()
