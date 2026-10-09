#!/usr/bin/env python3
"""Public APK identity gates and isolated legacy-compatible signing staging."""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.platform.platform_package import sha, checksums, validate, architecture
from scripts.signing.production_config import scan_bytes

ROOT = Path(__file__).resolve().parents[2]
ABIS = {'aarch64': 'arm64-v8a', 'armv7': 'armeabi-v7a', 'x86_64': 'x86_64'}
FORBIDDEN_SUFFIXES = {'.jks', '.keystore', '.p12', '.pfx', '.pem', '.key'}

def yubikey_expected():
    metadata = json.loads((ROOT / 'metadata/signing/android-standard.json').read_text())
    data = dict(metadata['production'])
    data['package_name'] = metadata['package_name']
    if data.get('identity_kind') != 'new-yubikey-hardware-signing-identity':
        raise ValueError('SIGNING: unexpected YubiKey identity metadata')
    if not re.fullmatch('[0-9a-f]{64}', data.get('certificate_sha256', '')):
        raise ValueError('SIGNING: missing YubiKey certificate fingerprint')
    if not re.fullmatch('[A-Za-z0-9_.]+', data.get('package_name', '')):
        raise ValueError('SIGNING: missing YubiKey package identity')
    return data

def tool(name):
    return os.environ.get(name.upper(), name)

def public_identity(apk):
    # Capture output: only the canonical public digest is printed by our caller.
    result = subprocess.run([tool('apksigner'), 'verify', '--verbose', '--print-certs', str(apk)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise ValueError('SIGNING: apksigner verification failed (details withheld)')
    certs = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$', result.stdout, re.M)
    if len(certs) != 1:
        raise ValueError('SIGNING: exactly one APK signer required')
    result2 = subprocess.run([tool('aapt'), 'dump', 'badging', str(apk)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result2.returncode:
        raise ValueError('PACKAGE: aapt inspection failed')
    match = re.search(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'", result2.stdout, re.M)
    if not match:
        raise ValueError('PACKAGE: Android manifest identity absent')
    with zipfile.ZipFile(apk) as z:
        abis = sorted({n.split('/')[1] for n in z.namelist() if n.startswith('lib/') and len(n.split('/')) == 3})
        for arch, abi in ABIS.items():
            if abi in abis:
                architecture(z.read('lib/' + abi + '/librustdesk.so'), 'android', arch)
    return dict(certificate_sha256=certs[0].lower(), package_name=match[1],
                version_code=int(match[2]), version_name=match[3], abis=abis,
                apk_sha256=sha(apk), signature_verification='PASS',
                signing_schemes=[int(n) for n in re.findall(r'^Verified using v([123]) scheme.*: true$', result.stdout, re.M)])

def identity_gate(actual, reference, arch):
    if actual['certificate_sha256'] != reference['certificate_sha256']:
        print('Expected certificate SHA-256: ' + reference['certificate_sha256'])
        print('Actual certificate SHA-256: ' + actual['certificate_sha256'])
        raise ValueError('CERTIFICATE IDENTITY MISMATCH')
    if actual['package_name'] != reference['package_name']:
        raise ValueError('PACKAGE IDENTITY MISMATCH')
    if actual['abis'] != [ABIS[arch]]:
        raise ValueError('ARCH: split APK ABI mismatch')

def leakage_scan(folder):
    for p in Path(folder).rglob('*'):
        if p.is_symlink():
            raise ValueError('SIGNING: symlink in artifact staging')
        if not p.is_file():
            continue
        if p.suffix.lower() in FORBIDDEN_SUFFIXES or p.name == 'key.properties':
            raise ValueError('SIGNING: forbidden signing material filename')
        chunks = [p.read_bytes()]
        if p.suffix == '.apk':
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if Path(n).suffix.lower() in FORBIDDEN_SUFFIXES or Path(n).name == 'key.properties':
                        raise ValueError('SIGNING: signing material in APK')
                    if not n.endswith('/'):
                        chunks.append(z.read(n))
        for data in chunks:
            scan_bytes(data)
            if data.startswith(b'\\xfe\\xed\\xfe\\xed') or re.search(rb'/u3\\+7Q[A-Za-z0-9+/=\\r\\n]{80,}', data):
                raise ValueError('SIGNING: unexpected keystore material')
    print('Android credential leakage scan: PASS')

def locate_yubikey_bundle(folder):
    root = Path(folder)
    if root.is_symlink():
        raise ValueError('SIGNING: artifact root is a symlink')
    root = root.resolve()
    paths = list(root.rglob('*'))
    if any(path.is_symlink() for path in paths):
        raise ValueError('SIGNING: symlink in downloaded artifact')
    manifests = [path for path in paths if path.name == 'build-info.json' and path.is_file()]
    if len(manifests) != 1:
        raise ValueError('SIGNING: expected exactly one build manifest')
    bundle = manifests[0].parent.resolve()
    if not bundle.is_relative_to(root):
        raise ValueError('SIGNING: build manifest escaped artifact root')
    return bundle

def validate_yubikey_input(folder, arch):
    folder = locate_yubikey_bundle(folder)
    info = validate(folder)
    expected_arches = ABIS
    if arch not in expected_arches:
        raise ValueError('SIGNING: unsupported Android architecture')
    if (info.get('platform'), info.get('variant'), info.get('architecture')) != ('android', 'standard', arch):
        raise ValueError('SIGNING: unexpected Android build target')
    if info.get('package_type') != 'debug-signed-apk' or info.get('signed_status') != 'TEST SIGNED / NOT PRODUCTION SIGNED':
        raise ValueError('SIGNING: expected the original test-signed Android input')
    expected = {
        'channel': os.environ.get('SIGNING_CHANNEL', 'stable'),
        'custom_repository': os.environ['GITHUB_REPOSITORY'],
        'custom_repository_sha': os.environ['GITHUB_SHA'],
        'upstream_sha': os.environ['UPSTREAM_EXPECTED_SHA'],
        'upstream_version': os.environ['UPSTREAM_VERSION'],
        'patchset': os.environ['PATCHSET'],
        'build_run': os.environ['GITHUB_RUN_ID'],
        'workflow_run': os.environ['GITHUB_RUN_ID'],
    }
    for key, value in expected.items():
        if str(info.get(key)) != str(value):
            raise ValueError('SIGNING: build artifact provenance mismatch: ' + key)
    manifest = json.loads((folder / 'source-manifest.json').read_text())
    for key in ('upstream_sha', 'upstream_version', 'patchset', 'custom_repository_sha', 'variant'):
        if manifest.get(key) != info.get(key):
            raise ValueError('SIGNING: prepared source provenance mismatch: ' + key)
    if sha(folder / 'source-manifest.json') != info.get('prepared_source_identity'):
        raise ValueError('SIGNING: prepared source identity checksum mismatch')
    if str(manifest.get('prepare_workflow_run')) != str(info.get('prepare_run')) or str(info.get('prepare_run')) != str(info.get('build_run')):
        raise ValueError('SIGNING: build and prepare run mismatch')
    packages = list((folder / 'packages').glob('*.apk'))
    if len(packages) != 1 or packages[0].is_symlink() or not packages[0].resolve().is_relative_to(folder):
        raise ValueError('SIGNING: expected exactly one safe input APK')
    apk = packages[0].resolve()
    verify = subprocess.run([tool('apksigner'), 'verify', '--verbose', str(apk)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if verify.returncode:
        raise ValueError('SIGNING: input APK signature verification failed')
    badging = subprocess.run([tool('aapt'), 'dump', 'badging', str(apk)],
                             check=True, capture_output=True, text=True).stdout
    match = re.search(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'", badging, re.M)
    if not match or match.group(1) != yubikey_expected()['package_name']:
        raise ValueError('SIGNING: unexpected Android package identity')
    with zipfile.ZipFile(apk) as archive:
        native = 'lib/' + expected_arches[arch] + '/librustdesk.so'
        validation = folder / 'validation' / 'librustdesk.so'
        if native not in archive.namelist() or archive.read(native) != validation.read_bytes():
            raise ValueError('SIGNING: APK ABI does not match validated build output')
    digest = sha(apk)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('bundle=' + str(folder) + '\n')
            output.write('apk=' + str(apk) + '\n')
            output.write('unsigned_apk_sha256=' + digest + '\n')
    print('Same-run artifact, source, package, ABI and checksum gates: PASS')
    return folder, apk, digest

def finalize_yubikey(folder, signed, output, arch):
    folder = Path(folder).resolve()
    signed = Path(signed)
    output = Path(output)
    if signed.is_symlink() or output.is_symlink():
        raise ValueError('SIGNING: symlink in signing path')
    signed = signed.resolve()
    output = output.resolve()
    info = validate(folder)
    reference = yubikey_expected()
    if (info.get('platform'), info.get('variant'), info.get('architecture')) != ('android', 'standard', arch):
        raise ValueError('SIGNING: unexpected Android build target')
    if signed.is_symlink() or not signed.is_file():
        raise ValueError('SIGNING: signed APK missing or unsafe')
    packages = list((folder / 'packages').glob('*.apk'))
    if len(packages) != 1 or packages[0].is_symlink():
        raise ValueError('SIGNING: invalid unsigned APK inventory')
    original = public_identity(packages[0])
    actual = public_identity(signed)
    identity_gate(actual, reference, arch)
    for key in ('package_name', 'version_code', 'version_name', 'abis'):
        if actual[key] != original[key]:
            raise ValueError('SIGNING: APK identity changed during signing: ' + key)
    if not any(scheme in (2, 3) for scheme in actual['signing_schemes']):
        raise ValueError('SIGNING: APK lacks a verified v2 or v3 signature')
    with zipfile.ZipFile(signed) as archive:
        native = 'lib/' + ABIS[arch] + '/librustdesk.so'
        validation = folder / 'validation' / 'librustdesk.so'
        if native not in archive.namelist() or archive.read(native) != validation.read_bytes():
            raise ValueError('SIGNING: signed APK ABI differs from validated build output')
    if output.exists() or signed == output or output.is_relative_to(folder):
        raise ValueError('SIGNING: unsafe or pre-existing output path')
    unsigned_digest = sha(packages[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, output)
    shutil.rmtree(output / 'packages')
    (output / 'packages').mkdir()
    shutil.copy2(signed, output / 'packages' / ('standard-android-' + arch + '-signed.apk'))
    receipt = dict(actual,
        expected_certificate_sha256=reference['certificate_sha256'],
        certificate_match='PASS',
        signing_method='yubikey-piv-9c-pkcs11',
        piv_slot=reference['piv_slot'],
        pkcs11_id=reference['pkcs11_id'],
        key_algorithm=reference['key_algorithm'],
        curve=reference['curve'],
        unsigned_apk_sha256=unsigned_digest,
        workflow_run=os.environ['GITHUB_RUN_ID'],
        custom_repository_sha=os.environ['GITHUB_SHA'])
    (output / 'android-signing-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    info.update(signed=True, signing_identity_verified=True,
        certificate_sha256=actual['certificate_sha256'],
        package_name=actual['package_name'], version_code=actual['version_code'],
        version_name=actual['version_name'], signing_schemes=actual['signing_schemes'],
        signed_status='PRODUCTION SIGNED / IDENTITY VERIFIED',
        package_type='production-signed-apk', signing_method='yubikey-piv-9c-pkcs11',
        signing_run=os.environ['GITHUB_RUN_ID'])
    (output / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    checksums(output)
    leakage_scan(output)
    validate(output)
    print('Signer certificate SHA-256: ' + actual['certificate_sha256'])
    print('APK signature, fingerprint, package, ABI and provenance gates: PASS')

def verify_signed(folder, info):
    # The canonical YubiKey PIV identity is the only supported production identity.
    verify_yubikey_signed(folder, info)

def verify_yubikey_signed(folder, info):
    reference = yubikey_expected()
    if info.get('signed') is not True or info.get('signing_identity_verified') is not True:
        raise ValueError('SIGNING: YubiKey production signing receipt absent')
    if info.get('signing_method') != 'yubikey-piv-9c-pkcs11':
        raise ValueError('SIGNING: wrong hardware signing method')
    if str(info.get('signing_run')) != str(info.get('build_run')):
        raise ValueError('SIGNING: signing/build run mismatch')
    packages = list((folder / 'packages').glob('*.apk'))
    if len(packages) != 1:
        raise ValueError('SIGNING: invalid production APK inventory')
    actual = public_identity(packages[0])
    identity_gate(actual, reference, info['architecture'])
    if not any(scheme in (2, 3) for scheme in actual['signing_schemes']):
        raise ValueError('SIGNING: APK lacks a verified v2 or v3 signature')
    for key in ('certificate_sha256', 'package_name', 'version_code', 'version_name', 'signing_schemes'):
        if info.get(key) != actual[key]:
            raise ValueError('SIGNING: APK/build-info mismatch: ' + key)
    receipt = json.loads((folder / 'android-signing-verification.json').read_text())
    for key in actual:
        if receipt.get(key) != actual[key]:
            raise ValueError('SIGNING: YubiKey receipt mismatch: ' + key)
    if receipt.get('expected_certificate_sha256') != reference['certificate_sha256']:
        raise ValueError('SIGNING: YubiKey expected fingerprint receipt mismatch')
    if receipt.get('signing_method') != 'yubikey-piv-9c-pkcs11':
        raise ValueError('SIGNING: receipt does not identify YubiKey PIV signing')
    if receipt.get('piv_slot') != '9C' or receipt.get('pkcs11_id') != '02':
        raise ValueError('SIGNING: receipt key slot or object ID mismatch')
    if receipt.get('custom_repository_sha') != info.get('custom_repository_sha'):
        raise ValueError('SIGNING: custom repository provenance mismatch')
    if str(receipt.get('workflow_run')) != str(info.get('build_run')):
        raise ValueError('SIGNING: signing workflow provenance mismatch')
    leakage_scan(folder)

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='mode', required=True)
    a = sub.add_parser('inspect')
    a.add_argument('apk', type=Path)
    a = sub.add_parser('validate-yubikey-input')
    a.add_argument('folder', type=Path)
    a.add_argument('--arch', required=True)
    a = sub.add_parser('finalize-yubikey')
    a.add_argument('folder', type=Path)
    a.add_argument('signed', type=Path)
    a.add_argument('output', type=Path)
    a.add_argument('--arch', required=True)
    a = sub.add_parser('scan')
    a.add_argument('folder', type=Path)
    args = p.parse_args()
    if args.mode == 'inspect':
        print(json.dumps(public_identity(args.apk), indent=2))
    elif args.mode == 'validate-yubikey-input':
        validate_yubikey_input(args.folder, args.arch)
    elif args.mode == 'finalize-yubikey':
        finalize_yubikey(args.folder, args.signed, args.output, args.arch)
    else:
        leakage_scan(args.folder)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not surface subprocess arguments or values from secret-bearing failures.
        if isinstance(error, ValueError): print(str(error), file=sys.stderr)
        else: print('SIGNING: gate failed (details withheld)', file=sys.stderr)
        sys.exit(1)
