#!/usr/bin/env python3
"""Guard CM startup/IPC wiring and exercise the real pure-Dart visibility policy.

Structural checks are not evidence of native-window or real-session behaviour.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
POLICY = 'flutter/lib/models/cm_window_policy.dart'


def require(condition, reason):
    if not condition:
        raise ValueError('CM window contract: ' + reason)


def new_file(patch, path):
    section = patch.split('diff --git a/' + path + ' b/' + path + '\n', 1)[1]
    section = section.split('\ndiff --git ', 1)[0]
    return '\n'.join(line[1:] for line in section.splitlines()
                     if line.startswith('+') and not line.startswith('+++')) + '\n'


def source_contract(tree):
    read = lambda p: (tree / p).read_text()
    main = read('flutter/lib/main.dart')
    cm = main[main.index('final _cmWindowPolicy'):main.index('void _runApp(')]
    require('minimize()' not in cm, 'CM must hide directly without a minimize transition')
    require('skipTaskbar: true' in cm and 'setSkipTaskbar(true)' in cm,
            'CM must remain excluded from the taskbar')
    require(cm.index('windowManager.hide()') < cm.index('initEnv(kAppTypeConnectionManager)'),
            'CM must be hidden before timers and IPC initialize')
    require('_cmWindowPolicy.initialize()' in cm and "cmGetConfig(name: 'hide_cm')" not in cm,
            'visibility must be initialized independently of authentication/hide preferences')
    require('requestShow(manual: manual)' in cm and '_queueCmWindow' in cm,
            'show/hide operations must be gated and serialized')
    common = read('flutter/lib/common.dart')
    require('if (desktopType == DesktopType.cm) return;' in common,
            'direct focus/show bypass must be blocked for the CM only')
    chat = read('flutter/lib/models/chat_model.dart')
    side = chat.split('toggleCMSidePage() async {', 1)[1].split('changeCurrentKey(', 1)[0]
    require('desktopType == DesktopType.cm && !cmIsVisible' in side and 'windowManager.show()' not in side,
            'incoming chat must not map or resize a hidden CM')
    model = read('flutter/lib/models/server_model.dart')
    require("cmGetConfig(name: 'custom-cm-show')" in model and 'showCmWindow(manual: true)' in model,
            'latched tray request must be polled and manually displayed')
    require('bool hideCm = true;' in model, 'model startup must be conservative')
    require('gFFI.serverModel.hideCm = true;' in cm and 'if (!manual) return;' in cm,
            'saved preferences must never enable automatic window display')
    page = read('flutter/lib/desktop/pages/server_page.dart')
    close = page.split('Future<bool> handleWindowCloseButton() async {', 1)[1].split('\n  }', 1)[0]
    require('hideCmWindow()' in close and 'windowManager.close()' not in close,
            'the CM close control must always hide without ending sessions')
    settings = read('flutter/lib/desktop/pages/desktop_setting_page.dart')
    setting = settings.split('Widget hide_cm(bool enabled) {', 1)[1].split('\n  }', 1)[0]
    require('Open connection manager manually' in setting and 'onChanged: null' in setting,
            'settings must report the enforced manual-only display policy')
    require('Data::CmShow if self.conn_id == 0' in read('src/ui_cm_interface.rs'),
            'only the separate local control stream may request a window')
    ffi = read('src/flutter_ffi.rs')
    require('CM_WINDOW_REQUESTED' in ffi and '.swap(false,' in ffi,
            'manual requests must survive startup and be consumed once')
    defaults = read('src/common.rs')
    require('defaults.entry("approve-mode".to_owned()).or_insert("password".to_owned());' in defaults,
            'approval must default to password without overriding saved consent mode')
    ipc = read('src/ipc.rs')
    branch = ipc.split('name == "hide_cm"', 1)[1].split('} else if', 1)[0]
    require('password_security::hide_cm()' in branch,
            'the upstream hide predicate must remain intact and separate from visibility')
    tray = read('src/tray.rs')
    require('connections_i' in tray and 'send_to_cm(&crate::ipc::Data::CmShow)' in tray,
            'tray must target an existing CM, not start a second manager')
    win = read('flutter/windows/runner/win32_window.cpp')
    require('showOnTaskBar ? 0 : WS_EX_TOOLWINDOW' in win, 'Windows CM must be a tool window at creation')
    linux = read('flutter/linux/my_application.cc')
    require('if (!gIsConnectionManager) {\n    gtk_widget_show(GTK_WIDGET(window));' in linux,
            'Linux CM top level must not be mapped at startup')
    require('if (gl_area != nullptr) gtk_widget_realize(gl_area);' in linux,
            'Linux hidden view must still initialize Flutter')
    mac = read('flutter/macos/Runner/MainFlutterWindow.swift')
    order = mac.split('override public func order(', 1)[1]
    require(order.index('!cmWindowVisible') < order.index('super.order('),
            'macOS must gate order-in before Cocoa displays the window')
    require('setCmWindowVisible' in mac, 'macOS must permit explicit recovery')
    return read(POLICY)


DART_CASES = r'''
void check(bool condition, String message) {
  if (!condition) throw StateError(message);
}
void main() {
  for (var session = 0; session < 3; session++) {
    final p = CmWindowPolicy();
    check(!p.requestShow(), 'startup must stay hidden');
    check(!p.requestShow(manual: true), 'early tray request must wait for readiness');
    check(p.manualRequested, 'early tray request must be retained');
    p.initialize();
    check(p.requestShow(manual: p.manualRequested), 'pending tray request must work');
    p.visible = true;
    for (var event = 0; event < 100; event++) {
      check(!p.requestShow(), 'timer, connection, chat or call stole focus');
    }
    p.hide();
    check(!p.visible && !p.manualRequested, 'hide must clear visible/pending state');
    check(!p.requestShow(), 'automatic event reopened the hidden CM');
    check(p.requestShow(manual: true), 'manual reopen must still work');
    check(!p.requestShow(), 'manual reopen must not enable automatic display');
  }
  print('CM visibility policy sequences: PASS');
}
'''


def dart_contract(policy, dart):
    with tempfile.TemporaryDirectory(prefix='rustdesk-cm-policy-') as folder:
        root = Path(folder)
        (root / 'policy.dart').write_text(policy)
        (root / 'check.dart').write_text("import 'policy.dart';\n" + DART_CASES)
        subprocess.run([dart, 'run', str(root / 'check.dart')], check=True, cwd=root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--dart', help='Dart executable; required when checking policy execution in Flutter CI')
    args = parser.parse_args()
    policies = []
    for gen in ('v1', 'v2'):
        patch = (ROOT / 'patchsets' / gen / 'common/0004-cm-background-window.patch').read_text()
        policies.append(new_file(patch, POLICY))
    require(policies[0] == policies[1], 'policy must be identical across patch generations')
    if args.source:
        require(source_contract(args.source) == policies[0], 'prepared policy differs from reviewed patch')
        print('CM prepared-source wiring: PASS')
    dart = args.dart or shutil.which('dart')
    if dart:
        dart_contract(policies[0], dart)
    else:
        print('CM Dart policy execution: NOT_RUN (Dart not installed)')
    print('CM patch policy parity: PASS; native UI/real remote session: NOT_TESTED')


if __name__ == '__main__':
    main()
