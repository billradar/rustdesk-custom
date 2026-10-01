import copy, contextlib, io, json, os, sys, tarfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import build_adapter, prepared_source, phase4
ROOT=Path(__file__).resolve().parents[1]
import yaml

class BuildInterfaceTests(unittest.TestCase):
    def test_unreviewed_build_definition_blocks(self):
        unknown={'signature':'0'*64}
        with patch.object(build_adapter,'inspect',return_value=(unknown,{})),self.assertRaisesRegex(ValueError,'BUILD_COMPATIBILITY=FAIL'):
            build_adapter.check(Path('.'))
    def test_known_profile_is_accepted_without_version_inference(self):
        approved=json.loads((ROOT/'metadata/build-adapter-profiles.json').read_text())['profiles'][0]
        profile={'signature':approved['signature'],'upstream_version':'9.8.7'}
        with patch.object(build_adapter,'inspect',return_value=(profile,{})):
            self.assertEqual(build_adapter.check(Path('.'))['upstream_version'],'9.8.7')

class SourceBoundaryTests(unittest.TestCase):
    def test_checksum_failure_happens_before_extraction(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);bundle=root/'bundle';bundle.mkdir();(bundle/'source.tar.gz').write_bytes(b'wrong');(bundle/'SHA256SUMS').write_text('0'*64+'  source.tar.gz\n')
            with self.assertRaisesRegex(ValueError,'checksum'):prepared_source.unpack(bundle,root/'output','standard','a'*40,'v1')
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
        m=dict(variant='standard',upstream_sha='a'*40,patchset='v1',custom_repository_sha='b'*40,
               prepare_workflow_run='3',upstream_repository='rustdesk/rustdesk',common_patch_hash='c'*64,sos_patch_hash=None,files={'main.rs':'unchanged'})
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'source-manifest.json').write_text(json.dumps(m));(root/'main.rs').write_text('modified')
            with patch.object(prepared_source,'git',return_value='a'*40),patch.object(prepared_source,'patch_hash',return_value='c'*64),self.assertRaisesRegex(ValueError,'inventory'):
                prepared_source.verify_tree(root,'standard','a'*40,'v1','b'*40,3)

class ChannelPolicyTests(unittest.TestCase):
    def test_nightly_uses_default_branch_not_stable(self):
        with patch.object(phase4,'api',return_value={'default_branch':'development'}),patch.object(phase4,'resolve_ref',return_value='a'*40) as resolve,patch.object(phase4,'outputs') as output:
            phase4.resolve('nightly');resolve.assert_called_once_with('development')
            self.assertEqual(output.call_args.args[0]['upstream_sha'],'a'*40)
            self.assertEqual(output.call_args.args[0]['upstream_tag'],'')
    def test_existing_draft_skips_costly_build_and_never_overwrites(self):
        sha='a'*40;existing={'body':f'Automation-State: complete\nUpstream SHA: {sha}\nPatch Set: v1\nCommon Patch Hash: {phase4.patch_hash("common","v1")}\nSOS Patch Hash: {phase4.patch_hash("sos","v1")}', 'draft':True,'prerelease':False, 'assets':[{'name':n,'state':'uploaded'} for n in ['SHA256SUMS','build-info-standard.json','build-info-sos.json','rustdesk-1.4.9-standard-windows-x86_64.zip','rustdesk-1.4.9-sos-windows-x86_64.zip']]}
        with patch.object(phase4,'choose_stable',return_value={'version':'1.4.9','upstream_tag':'1.4.9','upstream_sha':sha}),patch.object(phase4,'api',return_value=existing),patch.object(phase4,'outputs') as out:
            phase4.resolve('stable');data=out.call_args.args[0];self.assertFalse(data['build_needed']);self.assertFalse(data['draft_needed'])
            phase4.resolve('stable',force=True);data=out.call_args.args[0];self.assertTrue(data['build_needed']);self.assertFalse(data['draft_needed'])
    def test_entry_and_release_permissions(self):
        docs={p.name:yaml.safe_load(p.read_text()) for p in (ROOT/'.github/workflows').glob('*.yml')}
        self.assertEqual(docs['nightly.yml']['on']['schedule'],[{'cron':'0 2 * * *'}])
        for name in ('ci.yml','nightly.yml'):
            self.assertTrue(all(j.get('permissions',{}).get('contents')!='write' for j in docs[name]['jobs'].values()))
            self.assertNotIn('draft',docs[name]['jobs'])
        matrix=docs['build.yml']['jobs']['build']['strategy']['matrix']['include']
        self.assertEqual({(r['platform'],r['arch'],r['variant']) for r in matrix},{('windows','x86_64','standard'),('windows','x86_64','sos')})
        planned=json.loads((ROOT/'metadata/platform-matrix.json').read_text())['entries']
        self.assertFalse(any(r['variant']=='sos' and r['platform'] in ('android','ios','web') for r in planned))
    def test_no_auto_publish_calls(self):
        import ast
        for name in ('production.py','phase4.py'):
            tree=ast.parse((ROOT/'scripts'/name).read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.Dict):
                    for key,value in zip(node.keys,node.values):
                        if isinstance(key,ast.Constant) and key.value=='draft':
                            self.assertIsInstance(value,ast.Constant);self.assertIs(value.value,True)

if __name__=='__main__':unittest.main()
