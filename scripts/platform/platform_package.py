#!/usr/bin/env python3
"""Per-target packages, architecture, configuration, credential and provenance checks."""
import argparse,datetime,hashlib,json,os,re,shutil,struct,subprocess,tempfile,zipfile
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
 folder=Path(folder);i=json.loads((folder/'build-info.json').read_text());
 if i.get('build_flavor') and (i['platform']!='linux' or i['variant']!='standard' or i['build_flavor']!='unattended-wayland'):raise ValueError('PACKAGE: invalid build flavor')
 verify(i['patchset']);verify_checksums(folder)
 if i['variant']=='sos' and i['platform'] not in ('linux','macos'):raise ValueError('Forbidden SOS platform')
 for k,e in [('upstream_sha','UPSTREAM_EXPECTED_SHA'),('custom_repository_sha','GITHUB_SHA'),('build_run','GITHUB_RUN_ID'),('patchset','PATCHSET')]:
  if os.environ.get(e) and str(i[k])!=os.environ[e]:raise ValueError('PROVENANCE: '+k)
 if i['common_patch_hash']!=patch_hash('common',i['patchset']) or i['sos_patch_hash']!=(patch_hash('sos',i['patchset']) if i['variant']=='sos' else None):raise ValueError('PROVENANCE: patch hash')
 m=json.loads((folder/'source-manifest.json').read_text())
 for k in ('upstream_sha','upstream_version','patchset','common_patch_hash','sos_patch_hash','custom_repository_sha','variant'):
  if m[k]!=i[k]:raise ValueError('PROVENANCE: prepared source '+k)
 if sha(folder/'source-manifest.json')!=i['prepared_source_identity']:raise ValueError('PROVENANCE: source identity hash')
 if i.get('build_flavor')=='unattended-wayland':
  from scripts.platform.wayland import validate_source_policy
  validate_source_policy(i,m)
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
  unattended=i.get('build_flavor')=='unattended-wayland'
  if i.get('build_flavor') not in (None,'unattended-wayland'):raise ValueError('PACKAGE: unknown build flavor')
  if unattended and (len(packages)!=1 or packages[0].suffix!='.deb'):raise ValueError('PACKAGE: unattended flavor must contain exactly one DEB')
  deb=next((p for p in packages if p.suffix=='.deb'),None)
  if deb is None or (not unattended and not any(p.suffix=='.rpm' for p in packages)):raise ValueError('PACKAGE: missing deb/rpm')
  arch=subprocess.check_output(['dpkg-deb','-f',str(deb),'Architecture'],text=True).strip()
  if arch!={'x86_64':'amd64','aarch64':'arm64'}[i['architecture']]:raise ValueError('ARCH: Debian metadata mismatch')
  with tempfile.TemporaryDirectory() as tmp:
   subprocess.run(['dpkg-deb','-x',str(deb),tmp],check=True)
   if unattended:validate_wayland_deb(deb,Path(tmp),i)
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

def validate_wayland_deb(deb, root, info):
 from scripts.platform.wayland import POLICY,policy_for_pin,policy_for_tree
 p=policy_for_pin(info.get('libdrmtap_sha'))
 if info.get('wayland_policy_sha256')!=sha(POLICY) or info.get('libdrmtap_sha')!=p['libdrmtap_sha'] or info.get('drm_tests')!='PASS':raise ValueError('PROVENANCE: DRM pin, test or policy gate missing')
 if info.get('drm_test_groups')!=p['drm_test_groups'] or info.get('drm_test_count',0)<p['drm_test_groups']:raise ValueError('PROVENANCE: DRM tests did not execute')
 if info['variant']!='standard' or info['channel'] not in ('stable','nightly'):raise ValueError('PROVENANCE: DRM source/channel mismatch')
 if not deb.name.startswith('unattended-wayland-rustdesk-unattended-wayland-'):raise ValueError('PACKAGE: ambiguous artifact filename')
 control={k:subprocess.check_output(['dpkg-deb','-f',str(deb),k],text=True).strip() for k in ['Package','Conflicts','Provides','Replaces','Depends']}
 if control['Package']!='rustdesk-unattended-wayland':raise ValueError('PACKAGE: misleading DRM package name')
 for k in ['Conflicts','Provides','Replaces']:
  if not re.search(r'(?:^|,)\s*rustdesk(?:\s|,|$)',control[k]):raise ValueError('PACKAGE: missing stock package relationship: '+k)
 for dep in ['libdrm2','libegl1','libgles2']:
  if dep not in control['Depends']:raise ValueError('PACKAGE: missing capture runtime dependency')
 objects=list((root/'usr/lib/rustdesk').glob('libdrmtap.so.0.*'))
 objects=[x for x in objects if x.is_file() and not x.is_symlink()]
 link=root/'usr/lib/rustdesk/libdrmtap.so.0'
 if len(objects)!=1 or objects[0].name!='libdrmtap.so.'+p['libdrmtap_version'] or not link.is_symlink() or link.resolve()!=objects[0].resolve():raise ValueError('PACKAGE: capture library/soname mismatch')
 data=objects[0].read_bytes();architecture(data,'linux',info['architecture'])
 for marker in [b'socketpair',b'/usr/libexec/drmtap-helper']:
  if marker in data:raise ValueError('PACKAGE: privileged helper path present')
 # The pinned library must include EGL detiling, not a CPU-only stub.
 if any(x not in data for x in [b'libEGL.so.1',b'eglCreateImageKHR']):raise ValueError('PACKAGE: EGL capture path missing')
 libs=list((root/'usr/share/rustdesk').rglob('librustdesk.so'))
 if len(libs)!=1:raise ValueError('PACKAGE: ambiguous DRM client library')
 binary=libs[0].read_bytes()
 versions=[tuple(map(int,m)) for m in re.findall(rb'GLIBC_(\d+)\.(\d+)',data+binary)]
 floor=re.search(r'(?:^|,)\s*libc6\s*\(>=\s*(\d+)\.(\d+)',control['Depends'])
 if not versions or not floor or tuple(map(int,floor.groups()))<max(versions):raise ValueError('PACKAGE: libc6 dependency below actual ELF requirement')
 for marker in [b'/usr/lib/rustdesk/libdrmtap.so.0',b'enable-drm-display-wake']:
  if marker not in binary:raise ValueError('PACKAGE: stock/no-wake binary under unattended name')

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
  from scripts.build.config_mir import verify as verify_mir
  folder=Path(os.environ['CONFIG_MIR_DIR'])
  receipt=json.loads((folder/'validated.json').read_text())
  if receipt!={'result':'PASS','target':arch,'method':'compiler-mir'}:raise ValueError('PLATFORM_API: compiler receipt mismatch')
  verify_mir((folder/'client.mir').read_text(),values)
 version=os.environ['UPSTREAM_VERSION'];channel=os.environ['BUILD_CHANNEL'];flavor=os.environ.get('BUILD_FLAVOR')
 if flavor and (flavor!='unattended-wayland' or platform!='linux' or variant!='standard'):raise ValueError('PACKAGE: invalid build flavor')
 artifact_variant=flavor or variant
 dest=ROOT/'artifacts'/f'rustdesk-{channel}-{version}-{m["upstream_sha"]}-{artifact_variant}-{platform}-{arch}'
 dest.mkdir(parents=True,exist_ok=False);(dest/'packages').mkdir();(dest/'validation').mkdir()
 validation_name='librustdesk.so' if platform=='android' else library.name
 shutil.copy2(library,dest/'validation'/validation_name)
 if platform=='linux':packages=list(tree.glob('rustdesk-unattended-wayland*.deb')) if flavor else list(tree.glob('rustdesk*.deb'))+list(tree.glob('rustdesk*.rpm'));kind='deb' if flavor else 'deb/rpm'
 elif platform=='macos':packages=list(tree.glob('rustdesk*unsigned.dmg'));kind='unsigned-dmg'
 else:packages=list((tree/'signed-apk').glob('*.apk'));kind='debug-signed-apk'
 if not packages:raise ValueError('PACKAGE: official package absent')
 for p in packages:shutil.copy2(p,dest/'packages'/f'{artifact_variant}-{p.name}')
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
 if flavor:
  from scripts.platform.wayland import POLICY,policy_for_built_tree
  pin=policy_for_built_tree(tree,arch)
  actual=subprocess.check_output(['git','-C',str(tree/'third_party/libdrmtap'),'rev-parse','HEAD'],text=True).strip()
  if actual!=pin['libdrmtap_sha']:raise ValueError('PROVENANCE: actual libdrmtap checkout mismatch')
  tests=json.loads((tree/'wayland-tests.json').read_text())
  if tests.get('groups')!=pin['drm_test_groups'] or tests.get('tests',0)<pin['drm_test_groups']:raise ValueError('BUILD_COMPAT: missing DRM test execution evidence')
  info.update(drm_test_groups=tests['groups'],drm_test_count=tests['tests'],build_flavor=flavor,wayland_policy_sha256=sha(POLICY),libdrmtap_sha=actual,drm_tests='PASS',support_scope='EXPERIMENTAL BUILD ONLY')
 (dest/'build-info.json').write_text(json.dumps(info,indent=2)+'\n');shutil.copy2(tree/'source-manifest.json',dest/'source-manifest.json');shutil.copy2(tree/'LICENCE',dest/'LICENCE');shutil.copy2(ROOT/'README.md',dest/'SOURCE-README.md')
 for layer in ['common']+(['sos'] if variant=='sos' else []):shutil.copytree(ROOT/'patchsets'/m['patchset']/layer,dest/'patches'/layer)
 if (tree/'custom-source.sbom.json').exists():shutil.copy2(tree/'custom-source.sbom.json',dest/'custom-source.sbom.json')
 checksums(dest);validate(dest);print('Package/checksum/architecture/source/configuration/known credential gates: PASS')

if __name__=='__main__':
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True);a=s.add_parser('create');a.add_argument('--tree',type=Path,required=True);a.add_argument('--platform',required=True);a.add_argument('--arch',required=True);a.add_argument('--variant',required=True);a=s.add_parser('validate');a.add_argument('folder',type=Path);a=p.parse_args()
 if a.mode=='create':create(a.tree,a.platform,a.arch,a.variant)
 else:validate(a.folder)
