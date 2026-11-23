#!/usr/bin/env python3
"""Review-bounded official platform recipes from the exact prepared-source commit."""
import argparse,hashlib,json,os,re,subprocess
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[2]
JOBS={'linux':'build-rustdesk-linux','macos':'build-for-macOS','android':'build-rustdesk-android','ios':'build-rustdesk-ios','windows':'build-for-windows-flutter','web':'build-rustdesk-web'}
FILES=['build.py','build.rs','Cargo.toml','flutter/pubspec.yaml','.github/workflows/bridge.yml']
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def inspect(tree,platform,arch):
 tree=Path(tree);d=yaml.safe_load((tree/'.github/workflows/flutter-build.yml').read_text());job=d['jobs'][JOBS[platform]]
 env={k:str(v) for k,v in d['env'].items() if 'secrets.' not in str(v) and 'inputs.' not in str(v)}
 rows=job.get('strategy',{}).get('matrix',{}).get('job',[{'arch':'web','os':job.get('runs-on')}]);row=next((r for r in rows if r.get('arch')==arch),None)
 if row is None:raise ValueError('BUILD_COMPAT: official architecture not present')
 upstream_runner=row.get('os') or row.get('on') or row.get(True)
 from scripts.platform.runner_migrations import effective_runner
 runner=effective_runner(platform,arch,upstream_runner)
 # YAML 1.1 parses the official matrix field "on" as boolean True. Normalize keys.
 normalized=json.loads(json.dumps(job));identity={'job':normalized,'env':env,'files':{}}
 for p in FILES:
  from scripts.build.updater_dependencies import cargo_for_adapter
  raw=cargo_for_adapter(tree) if p=='Cargo.toml' else (tree/p).read_bytes().replace(b'\r\n',b'\n')
  identity['files'][p]=hashlib.sha256(raw).hexdigest()
 if platform=='android':
  for p in ['flutter/build_android_deps.sh','flutter/ndk_arm64.sh','flutter/ndk_arm.sh','flutter/ndk_x64.sh','flutter/android/app/build.gradle']:
   identity['files'][p]=hashlib.sha256((tree/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
 result={'platform':platform,'architecture':arch,'runner':runner,'upstream_runner':upstream_runner,'target':row.get('target'),'triplet':row.get('vcpkg-triplet'),'official_matrix':row,'signature':digest(identity),'rust':env.get('MAC_RUST_VERSION') if platform=='macos' else env['RUST_VERSION'],'flutter':env.get('ANDROID_FLUTTER_VERSION') if platform=='android' else env.get('FLUTTER_MACOS_ARM_VERSION',env['FLUTTER_VERSION']) if platform=='macos' and arch=='aarch64' else env['FLUTTER_VERSION'],'vcpkg':env['VCPKG_COMMIT_ID'],'ndk':env.get('NDK_VERSION'),'cargo_ndk':env.get('CARGO_NDK_VERSION'),'cmake':env.get('VCPKG_CMAKE_VERSION',''),'official_disabled':job.get('if') is False,'tools':env}
 return result,job

def _ci_linux_candidate(tree,p,platform,arch):
 """Allow exact reviewed Linux source+signature for CI tests only."""
 if platform!='linux' or p['platform']!='linux' or arch not in ('x86_64','aarch64'):
  raise ValueError('BUILD_COMPAT: CI candidate permission is Linux Standard/SOS only')
 if os.environ.get('BUILD_FLAVOR')=='unattended-wayland':
  raise ValueError('BUILD_COMPAT: CI candidate cannot approve unattended Wayland')
 sha=subprocess.check_output(['git','-C',str(Path(tree)),'rev-parse','HEAD'],text=True).strip()
 if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('BUILD_COMPAT: malformed source SHA')
 registry=json.loads((ROOT/'metadata/platform/ci-candidates.json').read_text())
 if registry.get('schema')!='platform-ci-candidates-v1' or not isinstance(registry.get('candidates'),list):
  raise ValueError('BUILD_COMPAT: invalid platform candidate registry')
 matches=[e for e in registry['candidates'] if e.get('source_sha')==sha]
 if len(matches)!=1:raise ValueError('BUILD_COMPAT: unreviewed exact official Linux source')
 row=matches[0]
 v=re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',(Path(tree)/'Cargo.toml').read_text(),re.M)
 expected={'x86_64':'ubuntu-22.04','aarch64':'ubuntu-22.04-arm'}
 if (not v or row.get('upstream_version')!=v.group(1)
     or row.get('ci_only') is not True or row.get('stable_allowed') is not False
     or row.get('platform')!='linux' or row.get('signature')!=p['signature']
     or not re.fullmatch('[0-9a-f]{64}',row.get('signature',''))
     or row.get('architectures')!=['x86_64','aarch64']
     or row.get('runners')!=expected or p['runner']!=expected[arch]
     or not re.fullmatch('[A-Za-z0-9_-]+',row.get('id',''))):
  raise ValueError('BUILD_COMPAT: source-specific Linux platform candidate drift')
 p.update(ci_candidate_only=True,stable_allowed=False,candidate_source_sha=sha,
          platform_review_status='CI_CANDIDATE_NOT_RELEASE_APPROVED')
 return p


def check(tree,platform,arch,channel=None):
 channel=channel or os.environ.get('BUILD_CHANNEL','stable')
 if channel not in ('ci','stable','nightly'):raise ValueError('BUILD_COMPAT: invalid platform channel')
 if platform=='macos' and arch=='aarch64' and (Path(tree)/'macos-arm64-transform.json').exists():
  from scripts.build.macos_arm64 import verified
  return verified(tree)
 p,j=inspect(tree,platform,arch);known=json.loads((ROOT/'metadata/platform/adapter-profiles.json').read_text())
 if p['official_disabled']:raise ValueError('BUILD_COMPAT: official job is disabled')
 if p['signature'] not in known['approved'].get(platform,[]):
  if channel!='ci':
   raise ValueError('BUILD_COMPAT: unreviewed official '+platform+' build interface; observed signature='+p['signature'])
  p=_ci_linux_candidate(tree,p,platform,arch)
 else:p['ci_candidate_only']=False
 if platform=='macos' and arch=='aarch64' and p['tools'].get('FLUTTER_MACOS_ARM_VERSION'):
  from scripts.build.macos_arm64 import check_profile
  p=check_profile(tree,p)
 return p,j

def render(text,profile):
 row=profile['official_matrix'];env=dict(profile['tools'],RUST_TOOLCHAIN_VERSION=profile['rust']+'.0' if profile['rust'].count('.')==1 else profile['rust'])
 def replace(m):
  key=m.group(1).strip()
  if key.startswith('matrix.job.'):
   v=row.get(key[11:])
  elif key.startswith('env.'):v=env.get(key[4:])
  elif key=='github.workspace':v='/workspace'
  # Custom recipes never inherit upstream artifact publication. Keep its
  # credential-free CI test branch active on x86_64, including Wayland builds.
  elif key=='inputs.upload-artifact' and profile.get('platform')=='linux':v='false'
  else:raise ValueError('BUILD_COMPAT: unhandled official expression '+key)
  if v is None:raise ValueError('BUILD_COMPAT: missing official expression '+key)
  return str(v)
 s=re.sub(r'\$\{\{\s*(.*?)\s*\}\}',replace,text)
 if '${{' in s:raise ValueError('BUILD_COMPAT: unresolved recipe expression')
 return s


# Only these precisely inspected official source revisions have the default-on
# DRM packaging interface. This is a CI recipe adaptation, NOT build approval.
STOCK_DRM_OPT_OUT_SHAS = frozenset({
    '9724512429b053be04cdb843345e99ddcccdb80e',
    '51f94394ce61e1f3d26229565c326b2862cbdd1f',
})


def adapt_stock_linux_recipe(tree, script):
    """Return an explicit no-DRM recipe for ordinary Linux artifacts.

    Never change the upstream source or the separate unattended-wayland recipe.
    An unknown or altered upstream recipe fails closed instead of being patched
    heuristically. The platform's own signature review remains mandatory.
    """
    from subprocess import check_output

    tree = Path(tree)
    build_script = (tree / 'build.py').read_text()
    if "'--no-drm'" not in build_script:
        guard_stock_linux_drm_recipe(tree, script)
        return script  # Historical default-off upstream; leave untouched.

    upstream_sha = check_output(
        ['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip()
    if upstream_sha not in STOCK_DRM_OPT_OUT_SHAS:
        raise ValueError('BUILD_COMPAT: unreviewed source cannot transform Linux DRM defaults')
    native = 'cargo build --locked --lib $JOBS --features hwcodec,flutter,unix-file-copy-paste,drm,drm-wake --release'
    native_stock = 'cargo build --locked --lib $JOBS --features hwcodec,flutter,unix-file-copy-paste --release'
    packaging = 'python3 ./build.py --flutter --skip-cargo'
    commands = [line.strip() for line in script.splitlines()]
    if (commands.count(native) != 1 or commands.count(packaging) != 1
            or script.count('check_rpm_drm "$name"') != 2
            or script.count('check_rpm_drm() {') != 1):
        raise ValueError('BUILD_COMPAT: default-on DRM Linux recipe no longer matches reviewed commands')

    # The official RPM-specific DRM assertion is intentionally removed for
    # ordinary packages, not disabled globally. The RPM payload is checked
    # independently by platform_package.validate().
    pattern = r'(?m)^check_rpm_drm\(\) \{\n(?:.*\n)*?^\}\n'
    patched, replacements = re.subn(pattern, '', script)
    if replacements != 1:
        raise ValueError('BUILD_COMPAT: unreviewed RPM DRM test body')
    patched = patched.replace('check_rpm_drm "$name"',
                              ': # stock RPM validated after extraction')
    patched = patched.replace(native, native_stock).replace(
        packaging, packaging + ' --hwcodec --unix-file-copy-paste --no-drm')
    # Fail if stale prebuilts might still be picked up by RPM specs. The
    # stock recipe must not build or package the pinned DRM capture library.
    checked = """if compgen -G '/workspace/third_party/libdrmtap/build-pkg/libdrmtap.so.0.*' > /dev/null; then
  echo 'BUILD_COMPAT: stock Linux source contains prebuilt libdrmtap' >&2
  exit 1
fi
"""
    features_preflight = """# Keep the actual upstream flag resolver aligned with the separately compiled native library.
STOCK_FEATURES=$(python3 ./build.py --flutter --hwcodec --unix-file-copy-paste --no-drm --print-features)
if [[ "$STOCK_FEATURES" != 'hwcodec,flutter,unix-file-copy-paste' ]]; then
  echo 'BUILD_COMPAT: upstream stock feature list changed or DRM is enabled' >&2
  exit 1
fi
"""
    patched = patched.replace(native_stock, checked + features_preflight + native_stock)
    guard_stock_linux_drm_recipe(tree, patched)
    if 'check_rpm_drm "$name"' in patched or '--features hwcodec,flutter,unix-file-copy-paste,drm' in patched:
        raise ValueError('BUILD_COMPAT: partial DRM transformation')
    return patched



def guard_stock_linux_drm_recipe(tree, recipe):
    """Reject silent DRM capture in ordinary Linux packages.

    The unattended Wayland flavor is separately built and provenance-gated.
    """
    source = (Path(tree) / 'build.py').read_text()
    commands = [line.strip() for line in recipe.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    for command in commands:
        if (re.search(r'\bcargo\s+build\b', command)
                and re.search(r'--features(?:=|\s+)[^\n]*(?<![\w-])drm(?:-wake)?(?![\w-])',
                              command)):
            raise ValueError('BUILD_COMPAT: stock Linux recipe enables DRM; separate unattended flavor review required')
        if re.search(r'(?:python3\s+)?\.?/?build\.py\s+--flutter\b', command):
            if '--drm' in command:
                raise ValueError('BUILD_COMPAT: stock Linux recipe explicitly requests DRM')
            if "'--no-drm'" in source and '--no-drm' not in command:
                raise ValueError('BUILD_COMPAT: new upstream defaults DRM on; stock Linux requires explicit --no-drm')
    return True


def linux_scripts(tree, arch, out, channel=None):
    p, job = check(tree, 'linux', arch, channel=channel)
    step = next(s for s in job['steps'] if s.get('name') == 'Build rustdesk' and 'with' in s)
    run = adapt_stock_linux_recipe(tree, render(step['with']['run'], p))
    guard_stock_linux_drm_recipe(tree, run)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'install.sh').write_text('set -euo pipefail\n' + render(step['with']['install'], p))
    (out / 'build.sh').write_text('set -euo pipefail\ncd /workspace\n' + run + '\n')
    return p


def parse_args(argv=None):
 a=argparse.ArgumentParser();a.add_argument('tree',type=Path);a.add_argument('--platform',required=True,choices=JOBS);a.add_argument('--arch',required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--linux-scripts',type=Path);a.add_argument('--channel',choices=('ci','stable','nightly'))
 return a.parse_args(argv)

if __name__=='__main__':
 a=parse_args()
 p,j=check(a.tree,a.platform,a.arch,channel=a.channel)
 if a.linux_scripts:linux_scripts(a.tree,a.arch,a.linux_scripts,channel=a.channel)
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(p,indent=2)+'\n')
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:
   for k in ['runner','rust','flutter','vcpkg','target','triplet','ndk','cargo_ndk','cmake','macos_flutter344']:f.write(k+'='+(str(p.get(k) or '').lower() if k=='macos_flutter344' else str(p.get(k) or ''))+'\n')
 print('Reviewed platform build interface: PASS')
