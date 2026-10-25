#!/usr/bin/env python3
"""Ensure an interface review never becomes an allow-all compatibility rule."""
import copy
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


if __name__=='__main__':unittest.main()
