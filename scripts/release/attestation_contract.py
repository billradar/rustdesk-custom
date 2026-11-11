"""Attestation coverage, exact package selection and fail-closed release contracts."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts.release import attestation as a

ROOT=Path(__file__).resolve().parents[2]


def fixture(directory, channel='stable'):
    p=directory/'rustdesk-1.5.1-linux-aarch64.deb';p.write_bytes(b'package')
    info=dict(platform='linux',architecture='aarch64',variant='standard',upstream_version='1.5.1',
              upstream_sha='a'*40,custom_repository_sha='b'*40,patchset='v2',
              patch_revision='v2.8' if channel=='stable' else None,
              common_patch_hash='c'*64,sos_patch_hash='d'*64)
    with patch.dict(os.environ,GITHUB_REPOSITORY=a.REPOSITORY,GITHUB_RUN_ID='42'):
        value=a.write(directory,channel,[a.entry(p,info)],info,{'result':'PASS'})
    (directory/a.BUNDLE).write_text('{"fixture":"signature verification is mocked only in tests"}')
    return value


class AttestationTests(unittest.TestCase):
    def test_manifest_generation_and_exact_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);v=fixture(root)
            self.assertEqual(v['assets'][0]['os'],'linux')
            self.assertEqual(v['assets'][0]['arch'],'aarch64')
            self.assertEqual(v['assets'][0]['flavor'],'ordinary')
            self.assertFalse((root/'SHA256SUMS').exists())
            with patch.object(a,'verify_signature') as verify,patch.dict(os.environ,clear=True):
                self.assertEqual(a.verify_local(root,'stable'),v)
                verify.assert_called_once()

    def test_tampering_missing_extra_and_symlink_fail_before_signature(self):
        for change in ('bytes','missing','extra','symlink','legacy'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as td:
                root=Path(td);v=fixture(root);p=root/v['assets'][0]['name']
                if change=='bytes':p.write_bytes(b'tampered')
                if change=='missing':p.unlink()
                if change=='extra':(root/'other.deb').write_bytes(b'other')
                if change=='legacy':(root/'SHA256SUMS').write_text('legacy')
                if change=='symlink':p.unlink();p.symlink_to('/etc/hosts')
                with patch.object(a,'verify_signature') as verify,patch.dict(os.environ,clear=True):
                    with self.assertRaises(ValueError):a.verify_local(root,'stable')
                    verify.assert_not_called()

    def test_schema_identity_selectors_and_stable_revision_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:v=fixture(Path(td))
        changes=[('schema','other'),('repository','other/repo'),('custom_repository_sha','bad'),
                 ('upstream_sha','bad'),('build_run','0'),('qualification','FAIL'),
                 ('patch_revision','v3.8'),('channel','ci')]
        for key,value in changes:
            with self.subTest(key=key),self.assertRaises(ValueError):
                a.validate(dict(v,**{key:value}))
        for key,value in [('name','../escape.deb'),('name','SHA256SUMS'),('size',True),
                          ('sha256','0'*63),('os','unknown'),('flavor','unknown'),
                          ('arch','armv7'),('package','exe')]:
            w=copy.deepcopy(v);w['assets'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):a.validate(w)
        for duplicate in (dict(v['assets'][0]),dict(v['assets'][0],name='different.deb')):
            with self.assertRaisesRegex(ValueError,'Duplicate'):a.validate(dict(v,assets=v['assets']+[duplicate]))
        with self.assertRaisesRegex(ValueError,'Duplicate JSON'):a.loads(b'{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError,'size limit'):a.loads(b' '*(a.LIMIT+1))

    def test_manifest_bytes_are_deterministic_across_aggregation_and_write_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);left=root/'aggregate';right=root/'writer';left.mkdir();right.mkdir()
            fixture(left);fixture(right)
            self.assertEqual((left/a.MANIFEST).read_bytes(),(right/a.MANIFEST).read_bytes())

    def test_writer_attaches_only_the_same_run_downloaded_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);assets=root/'assets';assets.mkdir();fixture(assets)
            proof=root/'.work/attested-aggregate';proof.mkdir(parents=True)
            (assets/a.BUNDLE).rename(proof/a.BUNDLE)
            previous=Path.cwd()
            try:
                os.chdir(root)
                with patch.object(a,'verify_signature') as signature,patch.dict(os.environ,clear=True):
                    a.attach(Path('assets'),'stable')
                signature.assert_called_once()
                self.assertEqual((assets/a.BUNDLE).read_bytes(),(proof/a.BUNDLE).read_bytes())
            finally:os.chdir(previous)

    def test_all_platform_variants_flavors_have_unique_selectors(self):
        from scripts.release.qualification import plan
        from scripts.release.naming import native_package_name,windows_installer_name
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);v=fixture(root);assets=[]
            for target in plan('stable')['selected']:
                formats={'windows':['exe','msi'],'linux':['deb','rpm','suse.rpm'],'macos':['dmg'],'android':['apk']}[target['platform']]
                for fmt in formats:
                    if target['platform']=='windows':name=windows_installer_name('1.5.1',target['variant'],fmt,target['arch'])
                    else:
                        tail=target['arch']+'.'+fmt if fmt in ('deb','dmg','apk') else target['arch']+'-0.'+target['arch']+('-suse.rpm' if fmt=='suse.rpm' else '.rpm')
                        name=native_package_name('1.5.1',target['variant'],target['platform'],target['arch'],'rustdesk-1.5.1-'+tail)
                    path=root/name;path.write_bytes(b'package')
                    assets.append(a.entry(path,dict(platform=target['platform'],architecture=target['arch'],variant=target['variant'])))
            for arch in ('x86_64','aarch64'):
                for variant in ('standard','sos'):
                    path=root/f'wayland-{variant}-{arch}.deb';path.write_bytes(b'package')
                    assets.append(a.entry(path,dict(platform='linux',architecture=arch,variant=variant,build_flavor='unattended-wayland')))
            a.validate(dict(v,assets=assets))
            self.assertEqual(len(assets),31)
            self.assertEqual(sum(x['package']=='suse-rpm' for x in assets),4)
            self.assertEqual(sum(x['flavor']=='unattended-wayland' for x in assets),4)

    def test_nightly_never_claims_stable_revision(self):
        with tempfile.TemporaryDirectory() as td:v=fixture(Path(td),'nightly')
        self.assertIsNone(v['patch_revision'])
        with self.assertRaises(ValueError):a.validate(dict(v,patch_revision='v2.8'))

    def test_signature_policy_and_failure_are_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);v=fixture(root)
            with patch.object(a.subprocess,'run') as run:
                a.verify_signature(root/a.MANIFEST,root/a.BUNDLE,v)
            args=run.call_args.args[0]
            self.assertIn('--bundle',args);self.assertIn('--deny-self-hosted-runners',args)
            self.assertEqual(args[args.index('--source-digest')+1],'b'*40)
            self.assertEqual(args[args.index('--source-ref')+1],'refs/heads/main')
            self.assertEqual(args[args.index('--signer-workflow')+1],a.REPOSITORY+'/.github/workflows/tag.yml')
            self.assertIn(a.PREDICATE,args)
            for failure in (subprocess.CalledProcessError(1,args),FileNotFoundError('gh'),subprocess.TimeoutExpired(args,120)):
                with patch.object(a.subprocess,'run',side_effect=failure),patch.dict(os.environ,clear=True):
                    with self.assertRaises(type(failure)):a.verify_local(root)

    def test_remote_json_downloads_use_asset_ids_and_require_exact_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);v=fixture(root)
            data={i:p.read_bytes() for i,p in enumerate(sorted(root.iterdir()),1)}
            assets=[dict(id=i,name=p.name,size=p.stat().st_size,state='uploaded',digest='sha256:'+a.sha(p))
                    for i,p in enumerate(sorted(root.iterdir()),1)]
            def run(args,**kwargs):
                self.assertEqual(args[:2],['gh','api'])
                kwargs['stdout'].write(data[int(args[2].rsplit('/',1)[1])])
            with patch.object(a.subprocess,'run',side_effect=run),patch.object(a,'verify_signature') as verify:
                self.assertTrue(a.verify_remote('v1.5.1-custom.v2.8',assets))
                verify.assert_called_once()
                with self.assertRaisesRegex(ValueError,'tag/channel'):a.verify_remote('v1.5.1-custom.v2.9',assets)
                with self.assertRaisesRegex(ValueError,'identity mismatch'):a.verify_remote('v1.5.1-custom.v2.8',assets,{'upstream_sha':'0'*40})
                bad=copy.deepcopy(assets);next(x for x in bad if x['name'].endswith('.deb'))['digest']='sha256:'+'0'*64
                with self.assertRaisesRegex(ValueError,'do not match'):a.verify_remote('v1.5.1-custom.v2.8',bad)
            for changed in (assets+assets[:1],[x for x in assets if x['name']!=a.BUNDLE],
                            [dict(x,id=True) for x in assets], [dict(x,size=9*a.LIMIT) for x in assets]):
                with patch.object(a.subprocess,'run') as run,self.assertRaises(ValueError):
                    a.verify_remote('v1.5.1-custom.v2.8',changed)
                run.assert_not_called()

    def test_remote_download_failure_and_digest_tampering_have_no_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fixture(root)
            assets=[dict(id=i,name=p.name,size=p.stat().st_size,state='uploaded',digest='sha256:'+a.sha(p))
                    for i,p in enumerate(sorted(root.iterdir()),1)]
            with patch.object(a.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['gh'])),patch.object(a,'verify_signature') as signature:
                with self.assertRaises(subprocess.CalledProcessError):a.verify_remote('v1.5.1-custom.v2.8',assets)
                signature.assert_not_called()
            def tamper(args,**kwargs):kwargs['stdout'].write(b'tampered')
            with patch.object(a.subprocess,'run',side_effect=tamper),patch.object(a,'verify_signature') as signature:
                with self.assertRaisesRegex(ValueError,'size/digest'):a.verify_remote('v1.5.1-custom.v2.8',assets)
                signature.assert_not_called()

    def test_only_gated_aggregate_jobs_mint_proofs_and_writers_download_them(self):
        for file,base in [('tag.yml','release-attestation-stable'),('nightly.yml','release-attestation-nightly')]:
            w=yaml.safe_load((ROOT/'.github/workflows'/file).read_text())
            jobs=w['jobs'];aggregate=jobs['aggregate']
            self.assertEqual(aggregate['permissions']['id-token'],'write')
            proof=next(s for s in aggregate['steps'] if s.get('id')=='release-attestation')
            self.assertRegex(proof['uses'],r'^actions/attest-build-provenance@[0-9a-f]{40}$')
            self.assertIn("github.ref == 'refs/heads/main'",proof['if'])
            self.assertIn("inputs.release_mode != 'dry-run'",proof['if'])
            self.assertEqual(proof['with']['subject-path'],'.work/qualification-aggregate/assets/'+a.MANIFEST)
            for name,job in jobs.items():
                if name!='aggregate':self.assertNotIn('attestations',job.get('permissions',{}))
                if name in ('release','draft'):
                    reader=next(s for s in job['steps'] if s.get('name')=='Download same-run attested aggregate')
                    self.assertIn(base,reader['run'])


if __name__=='__main__':unittest.main()
