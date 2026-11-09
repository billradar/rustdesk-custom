#!/usr/bin/env python3
"""Ensure an interface review never becomes an allow-all compatibility rule."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.build import build_adapter as adapter


class AdapterContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        known=json.loads((adapter.ROOT/'metadata/build/adapter-profiles.json').read_text())
        self.review=next(x for x in known['profiles'] if x['id']=='reviewed-151-1297da')
        self.assertEqual(self.review['reviewed_upstream_sha'],'1297da6d186e58d9096be24072ae3998cdbbf8fe')
        for f in adapter.CRITICAL_FILES:
            p=self.source/f;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# synthetic critical input\n')
        workflow={'env':self.review['critical']['tools'],'jobs':{'build-for-windows-flutter':{'strategy':{'matrix':{'job':[{'target':'x86_64-pc-windows-msvc','os':'windows-2022'}]}}}}}
        (self.source/'.github/workflows/flutter-build.yml').write_text(yaml.safe_dump(workflow))
        bridge={'env':{'RUST_VERSION':'1.75','CARGO_EXPAND_VERSION':'1.0.95','FLUTTER_RUST_BRIDGE_VERSION':'1.80.1'},'jobs':{'generate_bridge':{'strategy':{'matrix':{'job':[{'artifact-name':'bridge-artifact','flutter-version':'3.22.3'}]}}}}}
        (self.source/'.github/workflows/bridge.yml').write_text(yaml.safe_dump(bridge))
        (self.source/'.github/workflows/third-party-RustDeskTempTopMostWindow.yml').write_text('git checkout '+'a'*40+'\n')
        (self.source/'Cargo.toml').write_text('[package]\nversion = "1.5.1"\n')
        p,_=adapter.inspect(self.source)
        self.meta=self.root/'metadata/build/adapter-profiles.json';self.meta.parent.mkdir(parents=True)
        self.meta.write_text(json.dumps({'profiles':[dict(p,id='synthetic-reviewed')]}))

    def test_digest_normalizes_yaml_boolean_and_mixed_mapping_keys(self):
        sample={'workflow': {True: 'trigger', 'runs-on': 'ubuntu-22.04'}}
        canonical={'workflow': {'True': 'trigger', 'runs-on': 'ubuntu-22.04'}}
        expected=hashlib.sha256(json.dumps(
            canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(adapter.digest(sample),expected)
        string_only={'workflow': {'name': 'test', 'runs-on': 'ubuntu-22.04'}}
        self.assertEqual(adapter.digest(string_only),hashlib.sha256(json.dumps(
            string_only,sort_keys=True,separators=(',',':')).encode()).hexdigest())

    def test_exact_review_passes_but_critical_file_drift_fails(self):
        with patch.object(adapter,'ROOT',self.root):
            self.assertEqual(adapter.check(self.source)['reviewed_profile'],'synthetic-reviewed')
            for f in adapter.CRITICAL_FILES:
                p=self.source/f;old=p.read_text();p.write_text(old+'# drift\n')
                with self.assertRaisesRegex(ValueError,'unknown critical'):adapter.check(self.source)
                p.write_text(old)

    def test_toolchain_drift_and_wrong_runner_rejected(self):
        path=self.source/'.github/workflows/flutter-build.yml';original=yaml.safe_load(path.read_text())
        with patch.object(adapter,'ROOT',self.root):
            for name in adapter.TOOLS:
                d=copy.deepcopy(original);d['env'][name]='unreviewed';path.write_text(yaml.safe_dump(d))
                with self.assertRaisesRegex(ValueError,'unknown critical'):adapter.check(self.source)
            d=copy.deepcopy(original);d['jobs']['build-for-windows-flutter']['strategy']['matrix']['job'][0]['os']='unreviewed-runner';path.write_text(yaml.safe_dump(d))
            with self.assertRaisesRegex(ValueError,'Unsupported official'):adapter.check(self.source)

    def test_missing_review_does_not_succeed(self):
        self.meta.write_text('{"profiles":[]}')
        with patch.object(adapter,'ROOT',self.root),self.assertRaisesRegex(ValueError,'unknown critical'):
            adapter.check(self.source)

    def test_reviewed_template_profile_preserves_toolchain_and_critical_inputs(self):
        profiles=json.loads((adapter.ROOT/'metadata/build/adapter-profiles.json').read_text())['profiles']
        current=next(p for p in profiles if p['id']=='reviewed-151-94c321')
        self.assertEqual(current['reviewed_upstream_sha'],'94c321d05ce02ee73304e6cf99187e2d4d96e409')
        self.assertEqual(current['critical'],self.review['critical'])
        self.assertNotEqual(current['signature'],self.review['signature'])
        policy=json.loads((adapter.ROOT/'metadata/build/windows-arm64-policy.json').read_text())['profiles']
        old=next(p for p in policy if p['signature']==self.review['signature'])
        new=next(p for p in policy if p['signature']==current['signature'])
        self.assertEqual({k:v for k,v in old.items() if k!='signature'},
                         {k:v for k,v in new.items() if k!='signature'})

    def test_bridge_comment_review_is_exact_and_preserves_executable_commands(self):
        evidence=json.loads((adapter.ROOT/'docs/upstream-interface-reviews/bridge-comments-20261102.json').read_text())
        old,new=evidence['bridge_old_utf8'],evidence['bridge_new_utf8']
        old_comment,new_comment=evidence['replacement_old_shell_comments'],evidence['replacement_new_shell_comments']
        self.assertEqual(old.count(old_comment),1)
        self.assertEqual(new.count(new_comment),1)
        self.assertTrue(all(line.lstrip().startswith('#') for line in (old_comment+'\n'+new_comment).splitlines()))
        # Shell comments remain strings in YAML; replace only the two reviewed
        # full-line comments, without general comment/whitespace normalization.
        self.assertEqual(yaml.safe_load(old.replace(old_comment,new_comment)),yaml.safe_load(new))
        self.assertEqual(old.replace(old_comment,new_comment).replace(
            '# Dedicated bridge for the Windows arm64 build (Flutter 3.44); runs in parallel.',
            '# Dedicated bridge for the Windows and macOS arm64 builds (Flutter 3.44); runs in parallel.'),new)
        before,after=evidence['old_critical'],evidence['new_critical']
        self.assertEqual(before['windows_job'],after['windows_job'])
        self.assertEqual(before['tools'],after['tools'])
        bridge='.github/workflows/bridge.yml'
        self.assertEqual([k for k in before['files'] if before['files'][k]!=after['files'][k]],[bridge])
        for text,critical in ((old,before),(new,after)):
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),critical['files'][bridge])
        profiles=json.loads((adapter.ROOT/'metadata/build/adapter-profiles.json').read_text())['profiles']
        reviewed=next(p for p in profiles if p['id']=='reviewed-151-6aec30')
        previous=next(p for p in profiles if p['id']=='reviewed-151-94c321')
        self.assertEqual(adapter.digest(after),reviewed['signature'])
        self.assertEqual(adapter.digest(before),previous['signature'])
        self.assertEqual(reviewed['reviewed_upstream_sha'],evidence['new_upstream_sha'])
        self.assertEqual(reviewed['critical'],{k:v for k,v in after.items() if k!='windows_job'})
        ignored={'id','signature','reviewed_upstream_sha','review_notes','critical'}
        self.assertEqual({k:v for k,v in previous.items() if k not in ignored},
                         {k:v for k,v in reviewed.items() if k not in ignored})
        policy=json.loads((adapter.ROOT/'metadata/build/windows-arm64-policy.json').read_text())['profiles']
        arm_old=next(p for p in policy if p['signature']==previous['signature'])
        arm_new=next(p for p in policy if p['signature']==reviewed['signature'])
        self.assertEqual({k:v for k,v in arm_old.items() if k not in ('signature','patch_sha256')},
                         {k:v for k,v in arm_new.items() if k not in ('signature','patch_sha256')})
        for label,arm in (('old',arm_old),('new',arm_new)):
            text=evidence['source_patch_'+label+'_utf8']
            self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),arm['patch_sha256'])
            self.assertEqual(text.count('set -euo pipefail\n'),1)
            header,body=text.split('set -euo pipefail\n')
            self.assertTrue(all(not line.strip() or line.startswith('#') for line in header.splitlines()))
        self.assertEqual(evidence['source_patch_old_utf8'].split('set -euo pipefail\n')[1],
                         evidence['source_patch_new_utf8'].split('set -euo pipefail\n')[1])


if __name__=='__main__':unittest.main()
