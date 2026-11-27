"""Non-publishing package smoke evidence; no production qualification."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from scripts.platform.platform_package import architecture
from scripts.build.windows_arm64 import pe

def only(items):
    items=list(items)
    if len(items)!=1:
        raise ValueError('Expected exactly one fixture output')
    return items[0]

def main():
    tree, platform, arch, variant=sys.argv[1:]
    tree=Path(tree).resolve()
    if (os.environ.get('BUILD_CHANNEL')!='ci' or os.environ.get('BUILD_CONFIGURATION')!='TEST ONLY'
            or tree!=Path('.work/native/source').resolve()
            or (platform,arch,variant)!=(os.environ['PLATFORM'],os.environ['PLATFORM_ARCH'],os.environ['VARIANT'])):
        raise ValueError('Not an isolated fixture build')
    formal=None
    if os.environ.get('FORMAL_VALIDATION')=='true':
        from scripts.build.formal_validation import worker_identity
        formal=worker_identity(tree,variant)
    if platform=='android':
        package=only((tree/'signed-apk').glob('*.apk'))
        abi={'aarch64':'arm64-v8a','armv7':'armeabi-v7a','x86_64':'x86_64'}[arch]
        with zipfile.ZipFile(package) as z:
            entry='lib/'+abi+'/librustdesk.so'
            library=z.read(entry)
            if [n for n in z.namelist() if n.endswith('/librustdesk.so')]!=[entry]:
                raise ValueError('Unexpected APK ABI inventory')
            architecture(library,platform,arch)
        tools=sorted(Path(os.environ['ANDROID_HOME'],'build-tools').glob('*/apksigner'))
        if not tools:
            raise ValueError('Missing apksigner')
        subprocess.run([str(tools[-1]),'verify',str(package)],check=True)
        packages=[package]
    elif platform=='macos':
        if arch=='aarch64':
            if formal is not None:
                from scripts.build.macos_arm64 import verified
                verified(tree,post_build=True,formal_validation=True)
                formal['macos_arm64_receipt_sha256']=hashlib.sha256((tree/'macos-arm64-transform.json').read_bytes()).hexdigest()
            else:
                from scripts.build.macos_arm64_ci import verified
                verified(tree,post_build=True)
        package=only(tree.glob('rustdesk*unsigned.dmg'))
        app=tree/'flutter/build/macos/Build/Products/Release/RustDesk.app'
        native=only(app.rglob('liblibrustdesk.dylib'))
        library=native.read_bytes()
        architecture(library,platform,arch)
        architecture((app/'Contents/MacOS/RustDesk').read_bytes(),platform,arch)
        subprocess.run(['hdiutil','verify',str(package)],check=True)
        packages=[package]
    elif platform=='windows':
        folder=only(Path('artifacts').glob('rustdesk-*-'+variant+'-test-windows-x86_64'))
        library=(folder/'rustdesk/librustdesk.dll').read_bytes()
        pe(folder/'rustdesk/librustdesk.dll','x86_64')
        exe=only((folder/'packages').glob('*.exe'))
        pe(exe,'x86_64')
        packages=[exe,only((folder/'packages').glob('*.msi'))]
    else:
        raise ValueError('Unsupported CI platform')
    for key in ('RUSTDESK_ID_SERVER','RUSTDESK_API_SERVER','RUSTDESK_KEY'):
        expected=os.environ[key].encode()
        if not expected or expected not in library:
            raise ValueError('Compiled fixture configuration marker missing: '+key)
    output=Path('.work/native/package-report.json')
    output.write_text(json.dumps({
        'kind':'CI_FIXTURE_PACKAGE_SMOKE','release_eligible':False,
        'platform':platform,'architecture':arch,'variant':variant,
        'upstream_sha':os.environ['UPSTREAM_EXPECTED_SHA'],
        'packages':[{'name':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in packages],
        'native_architecture':'PASS','fixture_configuration_markers':'PASS',
        **({'formal_source_evidence':formal} if formal is not None else {}),
    },indent=2)+'\n')
    print('CI package metadata and native payload verification: PASS (no publication)')

if __name__=='__main__':
    main()
