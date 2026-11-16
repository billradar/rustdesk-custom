"""v3-only deployment UI gates; backend/CLI provisioning remains untouched."""
import argparse
from pathlib import Path
import re

FILES = ['flutter/lib/common/deploy_policy.dart', 'flutter/lib/mobile/widgets/deploy_dialog.dart']

def source_contract(tree):
    policy = (tree / FILES[0]).read_text(encoding='utf-8')
    if not re.search(r'const bool kRadarDeployUiEnabled\s*=\s*false;', policy):
        raise ValueError('Deploy UI must default hidden in v3')
    settings = (tree / 'flutter/lib/mobile/pages/settings_page.dart').read_text(encoding='utf-8')
    main = (tree / 'flutter/lib/main.dart').read_text(encoding='utf-8')
    dialog = (tree / FILES[1]).read_text(encoding='utf-8')
    if not re.search(r'if \(kRadarDeployUiEnabled && isAndroid && !bind.isOutgoingOnly\(\)\)\s*SettingsTile\(', settings):
        raise ValueError('Deploy settings entry must be omitted, not replaced by a placeholder')
    if not re.search(r"if \(kRadarDeployUiEnabled && isAndroid\)\s*\{\s*platformFFI.registerEventHandler\(\s*'android_needs_deploy'", main):
        raise ValueError('Automatic deployment prompt is not gated')
    for name in ('showDeployPromptDialog', 'showDeployDialog'):
        if not re.search(r'void ' + name + r'\(\)\s*\{\s*if \(!kRadarDeployUiEnabled\) return;', dialog):
            raise ValueError('Deployment dialog entry must reject direct/stale calls: ' + name)
    for path in (tree / 'flutter/lib').rglob('*.dart'):
        text = path.read_text(encoding='utf-8')
        if re.search(r'\bshowDeploy(?:Prompt)?Dialog\s*\(', text) and path.relative_to(tree).as_posix() not in {
            'flutter/lib/main.dart', 'flutter/lib/mobile/pages/settings_page.dart', FILES[1]
        }:
            raise ValueError('New deployment entry requires a policy audit: ' + str(path.relative_to(tree)))
    for relative in ('src/flutter_ffi.rs', 'src/ui_interface.rs', 'src/core_main.rs'):
        if 'deploy_device' not in (tree / relative).read_text(encoding='utf-8'):
            raise ValueError('Underlying deployment capability must not be removed')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    source_contract(args.source)
    print('Deploy UI policy source contract: PASS (not a runtime UI test)')
