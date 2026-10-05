#!/usr/bin/env python3
"""Per-target packages, architecture, configuration, credential and provenance checks."""
import argparse,datetime,hashlib,json,os,shutil,struct,subprocess,tempfile,zipfile
from pathlib import Path
from scripts.signing.production_config import configured,server_fingerprint,scan_bytes,FORBIDDEN
from scripts.upstream.patchsets import patch_hash,verify
ROOT=Path(__file__).resolve().parents[2]
ELF={'x86_64':62,'aarch64':183,'armv7':40}
MACH={'x86_64':0x1000007,'aarch64':0x100000c}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def architecture(data,platform,arch):
 if platform in ('linux','android'):
  if data[:4]!=b'\x7fELF' or len(data)<20:raise ValueError('ARCH: ELF header missing')
  endian='<' if data[5]==1 else '>'
  if struct.unpack_from(endian+'H',data,18)[0]!=ELF[arch]:raise ValueError('ARCH: incorrect ELF machine')
  if data[4]!=(1 if arch=='armv7' else 2):raise ValueError('ARCH: incorrect ELF class')
 elif platform=='macos':
  if data[:4]==b'\xcf\xfa\xed\xfe':cpus={struct.unpack_from('<I',data,4)[0]}
  elif data[:4]==b'\xfe\xed\xfa\xcf':cpus={struct.unpack_from('>I',data,4)[0]}
  elif data[:4]==b'\xca\xfe\xba\xbe':
   count=struct.unpack_from('>I',data,4)[0]
   if not 0<count<=16:raise ValueError('ARCH: invalid fat Mach-O')
   cpus={struct.unpack_from('>I',data,8+n*20)[0] for n in range(count)}
  else:raise ValueError('ARCH: Mach-O header missing')
  if MACH[arch] not in cpus:raise ValueError('ARCH: incorrect Mach-O CPU')
 else:raise ValueError('ARCH: unsupported validation platform')

def scan(data):
 scan_bytes(data)
 if any(v in data or v.decode().encode('utf-16-le') in data for v in FORBIDDEN):raise ValueError('PROVENANCE: test configuration marker in client payload')

def checksums(folder):
 rows=[sha(p)+'  '+p.relative_to(folder).as_posix() for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='SHA256SUMS']
 (folder/'SHA256SUMS').write_text('\n'.join(rows)+'\n')

def verify_checksums(folder):
 found=set()
 for line in (folder/'SHA256SUMS').read_text().splitlines():
  digest,name=line.split('  ',1);p=folder/name
  if name in found or not p.resolve().is_relative_to(folder.resolve()) or not p.is_file() or sha(p)!=digest:raise ValueError('PROVENANCE: checksum mismatch')
  found.add(name)
 expected={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p.name!='SHA256SUMS'}
 if found!=expected:raise ValueError('PROVENANCE: checksum coverage mismatch')

def validate(folder):
 folder=Path(folder);i=json.loads((folder/'build-info.json').read_text());verify(i['patchset']);verify_checksums(folder)
 if i['variant']=='sos' and i['platform'] not in ('linux','macos'):raise ValueError('Forbidden SOS platform')
 for k,e in [('upstream_sha','UPSTREAM_EXPECTED_SHA'),('custom_repository_sha','GITHUB_SHA'),('build_run','GITHUB_RUN_ID'),('patchset','PATCHSET')]:
  if os.environ.get(e) and str(i[k])!=os.environ[e]:raise ValueError('PROVENANCE: '+k)
 if i['common_patch_hash']!=patch_hash('common',i['patchset']) or i['sos_patch_hash']!=(patch_hash('sos',i['patchset']) if i['variant']=='sos' else None):raise ValueError('PROVENANCE: patch hash')
 m=json.loads((folder/'source-manifest.json').read_text())
 for k in ('upstream_sha','upstream_version','patchset','common_patch_hash','sos_patch_hash','custom_repository_sha','variant'):
  if m[k]!=i[k]:raise ValueError('PROVENANCE: prepared source '+k)
 if sha(folder/'source-manifest.json')!=i['prepared_source_identity']:raise ValueError('PROVENANCE: source identity hash')
 if str(m['prepare_workflow_run'])!=str(i['prepare_run']) or str(i['prepare_run'])!=str(i['build_run']):raise ValueError('PROVENANCE: workflow mismatch')
 for key in ('configuration_validation','architecture_validation','package_validation','credential_scan'):
  if i[key]!='PASS':raise ValueError('Required package gate missing: '+key)
 if i['runtime_ui_validation']!='SKIPPED BY USER' or i['real_remote_session_validation']!='NOT TESTED':raise ValueError('Incorrect runtime status')
 if i['signed_status']=='PRODUCTION SIGNED / IDENTITY VERIFIED':
  if i['platform']!='android' or i['variant']!='standard':raise ValueError('Signing policy mismatch')
  from scripts.signing.android_identity import verify_signed
  verify_signed(folder,i)
 elif i['signed_status'] not in ('NOT ENABLED','TEST SIGNED / NOT PRODUCTION SIGNED'):raise ValueError('Signing policy mismatch')
 for p in folder.rglob('*'):
  if p.is_file():scan(p.read_bytes())
 if i['platform']=='android':
  validation_native=folder/'validation'/'librustdesk.so'
  if (folder/'validation').is_symlink() or not validation_native.is_file() or validation_native.is_symlink() or not validation_native.resolve().is_relative_to(folder.resolve()):raise ValueError('ARCH: canonical Android validation binary missing or unsafe')
  if set((folder/'validation').iterdir())!={validation_native}:raise ValueError('ARCH: unexpected Android validation files')
  libs=[validation_native]
 else:
  libs=list((folder/'validation').glob('*'))
 if not libs:raise ValueError('ARCH: validation binary missing')
 for p in libs:architecture(p.read_bytes(),i['platform'],i['architecture'])
 packages=list((folder/'packages').glob('*'))
 if not packages:raise ValueError('PACKAGE: no package')
 if i['platform']=='android':
  abi={'aarch64':'arm64-v8a','armv7':'armeabi-v7a','x86_64':'x86_64'}[i['architecture']]
  for p in packages:
   with zipfile.ZipFile(p) as z:
    name='lib/'+abi+'/librustdesk.so'
    if z.read(name)!=validation_native.read_bytes():raise ValueError('PACKAGE: APK native library mismatch')
    for n in z.namelist():
     if not n.endswith('/'):scan(z.read(n))
 elif i['platform']=='linux':
  deb=next((p for p in packages if p.suffix=='.deb'),None)
  if deb is None or not any(p.suffix=='.rpm' for p in packages):raise ValueError('PACKAGE: missing deb/rpm')
  arch=subprocess.check_output(['dpkg-deb','-f',str(deb),'Architecture'],text=True).strip()
  if arch!={'x86_64':'amd64','aarch64':'arm64'}[i['architecture']]:raise ValueError('ARCH: Debian metadata mismatch')
  with tempfile.TemporaryDirectory() as tmp:
   subprocess.run(['dpkg-deb','-x',str(deb),tmp],check=True)
   native=list(Path(tmp).rglob('librustdesk.so'))
   if len(native)!=1 or sha(native[0])!=sha(libs[0]):raise ValueError('PACKAGE: Debian native library mismatch')
   for p in Path(tmp).rglob('*'):
    if p.is_file() and not p.is_symlink():scan(p.read_bytes())
  for rpm in [p for p in packages if p.suffix=='.rpm']:
   rpm_arch=subprocess.check_output(['rpm','-qp','--qf','%{ARCH}',str(rpm)],text=True).strip()
   if rpm_arch!=i['architecture']:raise ValueError('ARCH: RPM metadata mismatch')
   # Package path listing must be relative before extraction in an isolated directory.
   listing=subprocess.check_output(['rpm','-qpl',str(rpm)],text=True).splitlines()
   if any('..' in Path(n).parts for n in listing):raise ValueError('PACKAGE: unsafe RPM path')
   with tempfile.TemporaryDirectory() as tmp:
    reader=subprocess.Popen(['rpm2cpio',str(rpm.resolve())],stdout=subprocess.PIPE)
    extractor=subprocess.run(['cpio','-idm','--no-absolute-filenames'],stdin=reader.stdout,cwd=tmp,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    reader.stdout.close()
    if reader.wait() or extractor.returncode:raise ValueError('PACKAGE: RPM extraction failed')
    native=list(Path(tmp).rglob('librustdesk.so'))
    if len(native)!=1:raise ValueError('PACKAGE: RPM native library missing')
    architecture(native[0].read_bytes(),'linux',i['architecture'])
    for p in Path(tmp).rglob('*'):
     if p.is_file() and not p.is_symlink():scan(p.read_bytes())
 return i

def create(tree,platform,arch,variant):
 tree=Path(tree);values=configured();m=json.loads((tree/'source-manifest.json').read_text());profile=json.loads(Path('.work/platform-profile.json').read_text())
 if platform in ('linux','macos'):
  library=tree/('target/release/liblibrustdesk.so' if platform=='linux' else 'target/release/liblibrustdesk.dylib')
 else:
  target=profile['target'];library=tree/'target'/target/'release/liblibrustdesk.so'
 if not library.exists():raise ValueError('PACKAGE: native library not found')
 data=library.read_bytes();architecture(data,platform,arch);scan(data)
 for name,value in values.items():
  if not value or name=='RUSTDESK_PASSWORD' or (platform=='macos' and name=='RUSTDESK_API_SERVER'):continue
  if value.encode() not in data:raise ValueError('PLATFORM_API: compiled input missing: '+name+' (withheld)')
 if platform in ('macos','linux'):
  from scripts.validation.native_config_probe import verify as probe
  probe(library,check_api=True)
 if platform=='android':
  from config_mir import verify as verify_mir
  folder=Path(os.environ['CONFIG_MIR_DIR'])
  receipt=json.loads((folder/'validated.json').read_text())
  if receipt!={'result':'PASS','target':arch,'method':'compiler-mir'}:raise ValueError('PLATFORM_API: compiler receipt mismatch')
  verify_mir((folder/'client.mir').read_text(),values)
 version=os.environ['UPSTREAM_VERSION'];channel=os.environ['BUILD_CHANNEL'];dest=ROOT/'artifacts'/f'rustdesk-{channel}-{version}-{m["upstream_sha"]}-{variant}-{platform}-{arch}'
 dest.mkdir(parents=True,exist_ok=False);(dest/'packages').mkdir();(dest/'validation').mkdir()
 validation_name='librustdesk.so' if platform=='android' else library.name
 shutil.copy2(library,dest/'validation'/validation_name)
 if platform=='linux':packages=list(tree.glob('rustdesk*.deb'))+list(tree.glob('rustdesk*.rpm'));kind='deb/rpm'
 elif platform=='macos':packages=list(tree.glob('rustdesk*unsigned.dmg'));kind='unsigned-dmg'
 else:packages=list((tree/'signed-apk').glob('*.apk'));kind='debug-signed-apk'
 if not packages:raise ValueError('PACKAGE: official package absent')
 for p in packages:shutil.copy2(p,dest/'packages'/f'{variant}-{p.name}')
 if platform=='macos':
  # Validate the actual DMG bundle against the built Rust library on the macOS runner.
  with tempfile.TemporaryDirectory() as mount:
   subprocess.run(['hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,str(packages[0])],check=True,stdout=subprocess.DEVNULL)
   try:
    matches=list(Path(mount).rglob('liblibrustdesk.dylib'))
    bundled=list((tree/'flutter/build/macos/Build/Products/Release/RustDesk.app').rglob('liblibrustdesk.dylib'))
    if len(matches)!=1 or len(bundled)!=1 or sha(matches[0])!=sha(bundled[0]):raise ValueError('PACKAGE: DMG differs from the actual Xcode bundle')
    architecture(matches[0].read_bytes(),platform,arch)
    probe(matches[0],check_api=True)
    # Xcode may strip or ad-hoc sign its copy. Validate and retain the actual packaged library.
    shutil.copy2(matches[0],dest/'validation'/library.name)
    app=next(Path(mount).glob('*.app'))
    exe=app/'Contents/MacOS/RustDesk';architecture(exe.read_bytes(),platform,arch)
   finally:subprocess.run(['hdiutil','detach',mount],check=True,stdout=subprocess.DEVNULL)
 signed='TEST SIGNED / NOT PRODUCTION SIGNED' if platform=='android' else 'NOT ENABLED'
 info={k:m[k] for k in ('variant','upstream_repository','upstream_ref','upstream_version','upstream_sha','patchset','common_patch_hash','sos_patch_hash','custom_repository','custom_repository_sha')}
 info.update(channel=channel,platform=platform,architecture=arch,platform_patch_hash=None,prepared_source_identity=sha(tree/'source-manifest.json'),prepare_run=m['prepare_workflow_run'],build_run=os.environ['GITHUB_RUN_ID'],workflow_run=os.environ['GITHUB_RUN_ID'],build_job=os.environ.get('GITHUB_JOB'),runner=os.environ.get('RUNNER_OS'),runner_arch=os.environ.get('RUNNER_ARCH'),runner_image=os.environ.get('ImageOS'),package_type=kind,signed_status=signed,configuration='PRODUCTION',configuration_validation='PASS',password_validation_method='compiler-mir-and-package-native-identity' if platform=='android' else 'built-library-native-bridge',server_config_fingerprint=server_fingerprint(),build_time=datetime.datetime.now(datetime.timezone.utc).isoformat(),runtime_ui_validation='SKIPPED BY USER',real_remote_session_validation='NOT TESTED',architecture_validation='PASS',package_validation='PASS',credential_scan='PASS',platform_adapter_signature=profile['signature'],build_toolchain={k:profile[k] for k in ['rust','flutter','vcpkg','ndk','cargo_ndk']})
 (dest/'build-info.json').write_text(json.dumps(info,indent=2)+'\n');shutil.copy2(tree/'source-manifest.json',dest/'source-manifest.json');shutil.copy2(tree/'LICENCE',dest/'LICENCE');shutil.copy2(ROOT/'README.md',dest/'SOURCE-README.md')
 for layer in ['common']+(['sos'] if variant=='sos' else []):shutil.copytree(ROOT/'patchsets'/m['patchset']/layer,dest/'patches'/layer)
 if (tree/'custom-source.sbom.json').exists():shutil.copy2(tree/'custom-source.sbom.json',dest/'custom-source.sbom.json')
 checksums(dest);validate(dest);print('Package/checksum/architecture/source/configuration/known credential gates: PASS')

if __name__=='__main__':
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True);a=s.add_parser('create');a.add_argument('--tree',type=Path,required=True);a.add_argument('--platform',required=True);a.add_argument('--arch',required=True);a.add_argument('--variant',required=True);a=s.add_parser('validate');a.add_argument('folder',type=Path);a=p.parse_args()
 if a.mode=='create':create(a.tree,a.platform,a.arch,a.variant)
 else:validate(a.folder)
