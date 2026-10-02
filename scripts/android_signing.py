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

from platform_package import sha, checksums, validate, architecture
from production_config import scan_bytes

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('ANDROID_SIGNING_KEY', 'ANDROID_KEY_STORE_PASSWORD',
         'ANDROID_KEY_PASSWORD', 'ANDROID_ALIAS')
ABIS = {'aarch64': 'arm64-v8a', 'armv7': 'armeabi-v7a', 'x86_64': 'x86_64'}
FORBIDDEN_SUFFIXES = {'.jks', '.keystore', '.p12', '.pfx', '.pem', '.key'}

def preflight():
    missing = []
    for name in NAMES:
        present = bool(os.environ.get(name))
        print(name + ': ' + ('present' if present else 'missing'))
        if not present:
            missing.append(name)
    if missing:
        raise ValueError('BLOCKED: LEGACY SIGNING SECRETS NOT AVAILABLE')

def expected():
    data = json.loads((ROOT / 'metadata/android-signing-identity.json').read_text())
    if data['source'] != 'legacy-production-apk' or data['private_key_stored'] is not False:
        raise ValueError('SIGNING: untrusted identity metadata')
    if not re.fullmatch('[0-9a-f]{64}', data['certificate_sha256']):
        raise ValueError('SIGNING: missing canonical expected certificate')
    if not re.fullmatch('[A-Za-z0-9_.]+', data['package_name']):
        raise ValueError('SIGNING: missing expected package')
    return data

def yubikey_expected():
    data = json.loads((ROOT / 'metadata/yubikey-android-signing-identity.json').read_text())
    if data.get('identity_kind') != 'new-yubikey-hardware-signing-identity':
        raise ValueError('SIGNING: unexpected YubiKey identity metadata')
    if data.get('legacy_android_signing_identity') != 'NOT RECOVERED / NOT VALIDATED':
        raise ValueError('SIGNING: legacy identity status must remain unvalidated')
    if not re.fullmatch('[0-9a-f]{64}', data.get('certificate_sha256', '')):
        raise ValueError('SIGNING: missing YubiKey certificate fingerprint')
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

def leakage_scan(folder, secrets=False):
    needles = []
    if secrets:
        preflight()
        for name in NAMES[:-1]:
            value = os.environ[name].encode()
            needles.extend((value, value.decode().encode('utf-16-le')))
        try:
            # The legacy secret is a base64 keystore; never write the decoded data here.
            decoded = base64.b64decode(''.join(os.environ[NAMES[0]].split()), validate=True)
        except Exception:
            raise ValueError('SIGNING: invalid base64 signing material') from None
        if not decoded:
            raise ValueError('SIGNING: empty signing material')
        needles.append(decoded)
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
            if data.startswith(b'\xfe\xed\xfe\xed') or re.search(rb'/u3\+7Q[A-Za-z0-9+/=\r\n]{80,}', data):
                raise ValueError('SIGNING: unexpected keystore material')
            if any(n in data for n in needles):
                raise ValueError('SIGNING: credential leakage detected (value withheld)')
    print('Android credential leakage scan: PASS')

def stage(folder, destination):
    info = validate(folder)
    if (info['platform'], info['variant']) != ('android', 'standard'):
        raise ValueError('SIGNING: Android Standard only')
    apks = list((folder / 'packages').glob('*.apk'))
    if len(apks) != 1:
        raise ValueError('SIGNING: one split APK expected')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    destination.chmod(0o700)
    shutil.copy2(apks[0], destination / 'input.apk')
    # Legacy Action writes this existing file without changing its restrictive mode.
    key = destination / 'signingKey.jks'
    key.touch(mode=0o600)
    key.chmod(0o600)

def finalize(folder, signed, output):
    info = validate(folder)
    reference = expected()
    actual = public_identity(signed)
    identity_gate(actual, reference, info['architecture'])
    if info['platform'] != 'android' or info['variant'] != 'standard':
        raise ValueError('SIGNING: forbidden platform or variant')
    # Copy a verified public bundle only; private Action workspace is never traversed.
    shutil.copytree(folder, output)
    shutil.rmtree(output / 'packages')
    (output / 'packages').mkdir()
    apk = output / 'packages' / ('standard-android-' + info['architecture'] + '-signed.apk')
    shutil.copy2(signed, apk)
    receipt = dict(actual, schema=1, expected_certificate_sha256=reference['certificate_sha256'],
                   certificate_match='PASS', package_identity_match='PASS', abi_verification='PASS',
                   legacy_apk_sha256=reference['legacy_apk']['sha256'],
                   legacy_version_code=reference['version_code'],
                   static_upgrade_identity='PASS', runtime_upgrade='NOT TESTED',
                   upgrade_version_semantics='PASS' if actual['version_code'] > reference['version_code'] else 'UPGRADE VERSION SEMANTICS NOT VALIDATED',
                   workflow_run=os.environ['GITHUB_RUN_ID'], custom_repository_sha=os.environ['GITHUB_SHA'])
    info.update(signed=True, signing_identity_verified=True,
                certificate_sha256=actual['certificate_sha256'], package_name=actual['package_name'],
                version_code=actual['version_code'], version_name=actual['version_name'],
                signing_schemes=actual['signing_schemes'],
                signed_status='PRODUCTION SIGNED / IDENTITY VERIFIED', package_type='production-signed-apk',
                signing_run=os.environ['GITHUB_RUN_ID'], credential_scan='PASS')
    (output / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    (output / 'android-signing-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    checksums(output)
    leakage_scan(output, secrets=True)
    validate(output)
    print('Signer certificate SHA-256 digest: ' + actual['certificate_sha256'])
    print('Android signature/certificate/package/ABI/checksum/provenance: PASS')

def verify_signed(folder, info):
    if info.get('signing_method') == 'yubikey-piv-9c-pkcs11':
        verify_yubikey_signed(folder, info)
        return
    reference = expected()
    if info.get('signed') is not True or info.get('signing_identity_verified') is not True:
        raise ValueError('SIGNING: production signing receipt absent')
    if str(info.get('signing_run')) != str(info['build_run']):
        raise ValueError('SIGNING: signing/build run mismatch')
    packages = list((folder / 'packages').glob('*.apk'))
    if len(packages) != 1:
        raise ValueError('SIGNING: invalid production APK inventory')
    actual = public_identity(packages[0])
    identity_gate(actual, reference, info['architecture'])
    for key in ('certificate_sha256', 'package_name', 'version_code', 'version_name', 'signing_schemes'):
        if info.get(key) != actual[key]:
            raise ValueError('SIGNING: APK/build-info mismatch: ' + key)
    receipt = json.loads((folder / 'android-signing-verification.json').read_text())
    for key in actual:
        if receipt.get(key) != actual[key]:
            raise ValueError('SIGNING: public receipt mismatch: ' + key)
    for key in ('certificate_match', 'package_identity_match', 'abi_verification'):
        if receipt.get(key) != 'PASS':
            raise ValueError('SIGNING: identity receipt gate missing')
    if receipt.get('custom_repository_sha') != info['custom_repository_sha'] or str(receipt.get('workflow_run')) != str(info['build_run']):
        raise ValueError('SIGNING: receipt provenance mismatch')
    leakage_scan(folder)

def verify_yubikey_signed(folder, info):
    reference = yubikey_expected()
    if info.get('legacy_android_signing_identity') != 'NOT RECOVERED / NOT VALIDATED':
        raise ValueError('SIGNING: legacy Android identity must remain unvalidated')
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
    s = p.add_subparsers(dest='mode', required=True)
    s.add_parser('preflight')
    s.add_parser('expected')
    a = s.add_parser('inspect'); a.add_argument('apk', type=Path)
    a = s.add_parser('stage'); a.add_argument('folder', type=Path); a.add_argument('destination', type=Path)
    a = s.add_parser('finalize'); a.add_argument('folder', type=Path); a.add_argument('signed', type=Path); a.add_argument('output', type=Path)
    a = s.add_parser('scan'); a.add_argument('folder', type=Path); a.add_argument('--secrets', action='store_true')
    args = p.parse_args()
    if args.mode == 'preflight': preflight()
    elif args.mode == 'expected': expected(); print('Legacy public identity metadata: PASS')
    elif args.mode == 'inspect': print(json.dumps(public_identity(args.apk), indent=2))
    elif args.mode == 'stage': stage(args.folder, args.destination)
    elif args.mode == 'finalize': finalize(args.folder, args.signed, args.output)
    else: leakage_scan(args.folder, args.secrets)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not surface subprocess arguments or values from secret-bearing failures.
        if isinstance(error, ValueError): print(str(error), file=sys.stderr)
        else: print('SIGNING: gate failed (details withheld)', file=sys.stderr)
        sys.exit(1)
