"""Public branding defaults, escaping, identity isolation and real DEB regressions."""
import hashlib
import io
import json
import plistlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import yaml
from scripts.source import branding as b
from scripts.validation.cm_window_contract import new_file

ROOT=Path(__file__).resolve().parents[2]
PATCH='common/0006-public-branding.patch'


def source_contract(tree):
    expected=new_file((ROOT/'patchsets/v2'/PATCH).read_text(encoding='utf-8'),'flutter/lib/common/branding.dart')
    if (tree/'flutter/lib/common/branding.dart').read_text(encoding='utf-8')!=expected:
        raise ValueError('Branding helper differs from reviewed patch')

    for file in ('flutter/lib/desktop/pages/desktop_setting_page.dart',
                 'flutter/lib/mobile/pages/settings_page.dart'):
        if 'brandingVersion(version)' not in (tree/file).read_text(encoding='utf-8'):
            raise ValueError('About page is missing custom display version: '+file)


class BrandingTests(unittest.TestCase):
    def test_variable_count_and_workflow_empty_fallbacks(self):
        self.assertEqual(len(b.TEXT)+len(b.URLS),20)
        self.assertEqual(len(b.VISUAL),5)
        self.assertEqual(len(b.NAMES),49)
        workflow=yaml.safe_load((ROOT/'.github/workflows/prepare-source.yml').read_text(encoding='utf-8'))
        step=next(s for s in workflow['jobs']['prepare']['steps'] if s.get('name')=='Freeze public branding variables with defaults')
        self.assertEqual(set(step['env']),set(b.NAMES))
        for key,value in step['env'].items():
            self.assertEqual(value,'${{ vars.'+key+" || '' }}")

    def test_default_brand_is_upstream_and_links_follow_fork(self):
        p=b.resolve({},'fork-owner/client')
        self.assertEqual(set(p['values']),set(b.URLS)-{'CUSTOM_PRIVACY_URL'})
        self.assertEqual(p['values']['CUSTOM_WEBSITE_URL'],'https://github.com/fork-owner/client')
        self.assertEqual(b.resolve({key:'  ' for key in b.NAMES},'fork-owner/client'),p)

    def test_individual_override_precedes_derived_text_and_localization(self):
        values=b.resolve({'CUSTOM_DISPLAY_NAME':'Radar Remote','CUSTOM_ABOUT_TITLE':'Custom about',
            'CUSTOM_DISPLAY_NAME_ZH_CN':'雷达远程','CUSTOM_PUBLISHER':'Bill Radar (houxnan)'},'owner/repo')['values']
        self.assertEqual(values['CUSTOM_ABOUT_TITLE_ZH_CN'],'Custom about')
        self.assertEqual(values['CUSTOM_ANDROID_APP_LABEL_ZH_CN'],'雷达远程')
        self.assertIn('Bill Radar (houxnan)',values['CUSTOM_CUSTOMIZATION_NOTICE_ZH_CN'])
        self.assertEqual(values['CUSTOM_WINDOWS_COMPANY_NAME'],'Bill Radar (houxnan)')

    def test_invalid_values_and_reserved_images_fail_closed(self):
        for values in [dict(CUSTOM_DISPLAY_NAME='bad\nline'),dict(CUSTOM_DISPLAY_NAME='$(var.Product)'),
                       dict(CUSTOM_CONTACT_EMAIL='not email'),dict(CUSTOM_MAINTAINER='No contact'),
                       dict(CUSTOM_WEBSITE_URL='file:///tmp/a'),dict(CUSTOM_WEBSITE_URL='https://u:p@example.com'),
                       dict(CUSTOM_WEBSITE_URL='https://example.com:bad')]:
            with self.subTest(values=values),self.assertRaises(ValueError):b.resolve(values,'owner/repo')
        for key in b.VISUAL:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'reserved image interface'):
                b.resolve({key:'res/my-logo.png'},'owner/repo')

    def test_frozen_snapshot_cannot_change_repository_or_values(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'branding.json';snapshot=b.resolve({'CUSTOM_DISPLAY_NAME':'Radar'},'owner/repo')
            p.write_text(json.dumps(snapshot), encoding='utf-8')
            self.assertEqual(b.load(p,'owner/repo'),snapshot)
            with self.assertRaises(ValueError):b.load(p,'another/repo')
            snapshot['values']['CUSTOM_WEBSITE_URL']='http://unsafe.example'
            p.write_text(json.dumps(snapshot), encoding='utf-8')
            with self.assertRaises(ValueError):b.load(p,'owner/repo')

    def test_dart_literals_escape_interpolation_and_native_metadata_arguments(self):
        literal=b.dart_literal('Radar "$name" \\ text')
        self.assertIn(r'\$name',literal)
        self.assertIn(r'\"',literal)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);snapshot=b.resolve({'CUSTOM_PUBLISHER':'Bill Radar (houxnan)',
                'CUSTOM_CONTACT_EMAIL':'support@example.com','CUSTOM_MAINTAINER':'Bill Radar',
                'CUSTOM_DESCRIPTION':'Remote support'},'fork/client')
            (root/'branding.json').write_text(json.dumps(snapshot), encoding='utf-8')
            args=b.msi_arguments(root);self.assertEqual(args[0],'--custom-arp')
            arp=json.loads(args[1]);self.assertEqual(arp['HelpLink']['v'],'https://github.com/fork/client/issues')
            self.assertNotIn('ARPSYSTEMCOMPONENT',json.dumps(arp))
            self.assertEqual(b.deb_fields(snapshot['values'])['Maintainer'],'Bill Radar <support@example.com>')

    def test_real_deb_repack_preserves_payload_identity_scripts_and_icons(self):
        if not shutil.which('dpkg-deb'):self.skipTest('dpkg-deb unavailable')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);stage=root/'stage';(stage/'DEBIAN').mkdir(parents=True)
            (stage/'DEBIAN/control').write_text('Package: rustdesk\nVersion: 1.5.1\nArchitecture: amd64\nMaintainer: rustdesk <info@rustdesk.com>\nHomepage: https://rustdesk.com\nDescription: Remote desktop\nDepends: libc6\n', encoding='utf-8')
            (stage/'DEBIAN/postinst').write_text('#!/bin/sh\nexit 0\n', encoding='utf-8');(stage/'DEBIAN/postinst').chmod(0o755)
            (stage/'usr/share/icons').mkdir(parents=True);(stage/'usr/share/icons/original.png').write_bytes(b'unchanged-icon')
            package=root/'client.deb'
            subprocess.run(['dpkg-deb','--build','--root-owner-group',str(stage),str(package)],check=True,stdout=subprocess.DEVNULL)
            snapshot=b.resolve({'CUSTOM_DESCRIPTION':'Radar support'},'fork/client')
            (root/'branding.json').write_text(json.dumps(snapshot), encoding='utf-8');b.rebrand_deb(package,root)
            extracted=root/'out';subprocess.run(['dpkg-deb','--raw-extract',str(package),str(extracted)],check=True)
            self.assertEqual((extracted/'DEBIAN/postinst').read_bytes(),(stage/'DEBIAN/postinst').read_bytes())
            self.assertEqual((extracted/'usr/share/icons/original.png').read_bytes(),b'unchanged-icon')
            control=(extracted/'DEBIAN/control').read_text(encoding='utf-8')
            for value in ['Package: rustdesk','Version: 1.5.1','Depends: libc6','Description: Radar support']:
                self.assertIn(value,control)

    def test_installer_patch_handles_row_and_table_layouts(self):
        file='flutter/lib/desktop/pages/install_page.dart'
        for generation in ('v1','v2'):
            patch_text=(ROOT/'patchsets'/generation/PATCH).read_text(encoding='utf-8')
            header='diff --git a/'+file+' b/'+file+'\n'
            installer=header+patch_text.split(header,1)[1].split('diff --git ',1)[0]
            for layout in ('Row','Table'):
                with self.subTest(generation=generation,layout=layout),tempfile.TemporaryDirectory() as td:
                    root=Path(td);target=root/file;target.parent.mkdir(parents=True)
                    target.write_text("import 'dart:convert';\n"+'\n'*136+
                        "            children: [\n              Text(translate('Installation'),\n"+
                        "                  style: Theme.of(context).textTheme.headlineMedium),\n"+
                        '              '+layout+'(\n',encoding='utf-8')
                    subprocess.run(['git','apply','-'],cwd=root,input=installer,text=True,check=True,capture_output=True)
                    result=target.read_text(encoding='utf-8')
                    self.assertIn('...brandingInstallerHeading(',result)
                    self.assertIn('              '+layout+'(',result)

    def test_both_generations_share_branding_implementation(self):
        for file in ['flutter/lib/common/branding.dart','flutter/lib/common/branding_values.dart']:
            left=new_file((ROOT/'patchsets/v1'/PATCH).read_text(encoding='utf-8'),file)
            right=new_file((ROOT/'patchsets/v2'/PATCH).read_text(encoding='utf-8'),file)
            self.assertEqual(left,right)

    def test_about_variant_helper_patch_applies_and_localizes(self):
        for generation in ('v1', 'v2'):
            text=(ROOT/'patchsets'/generation/PATCH).read_text(encoding='utf-8')
            helper=text.split('diff --git ',2)[1]
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(['git','apply','-'],cwd=td,input='diff --git '+helper,
                               text=True,encoding='utf-8',check=True,capture_output=True)
                source=(Path(td)/'flutter/lib/common/branding.dart').read_text(encoding='utf-8')
                self.assertIn("final suffix = brandingUsesChinese() ? '_ZH_CN' : '_EN';",source)
                self.assertIn("language = bind.mainGetLocalOption(key: 'lang');",source)
                self.assertIn('PlatformDispatcher.instance.locale.toString()',source)
                self.assertIn('brandingVariantLabel(customAboutVariant, customAboutWayland,',source)
                for label in ['标准版','SOS 远程协助版','变体','Variant',' + Wayland unattended']:
                    self.assertIn(label,source)
                dart=shutil.which('dart')
                if dart:
                    fn=source.split('String brandingVariantLabel(',1)[1].split('List<Widget>',1)[0]
                    program="String brandingVariantLabel("+fn+"\nvoid main() {\n"
                    for variant,wayland,chinese,expected in [
                        ('Standard',False,True,'变体: 标准版'),('SOS',False,True,'变体: SOS 远程协助版'),
                        ('Standard',False,False,'Variant: Standard'),('SOS',True,False,'Variant: SOS + Wayland unattended'),
                        ('Standard',True,True,'变体: 标准版 + Wayland 无人值守')]:
                        program += 'if (brandingVariantLabel('+json.dumps(variant)+', '+str(wayland).lower()+', '+str(chinese).lower()+') != '+json.dumps(expected)+') throw StateError("Wrong variant label");\n'
                    program+='}\n'
                    target=Path(td)/'labels.dart';target.write_text(program,encoding='utf-8')
                    subprocess.run([dart,str(target)],check=True,capture_output=True)

    def test_native_escaping_and_internal_identity_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            files={
                'flutter/lib/common/branding_values.dart':'const customBranding = {};\n',
                'flutter/android/app/src/main/AndroidManifest.xml':'<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:label="RustDesk"><service android:label="RustDesk Input"/></application></manifest>',
                'res/rustdesk.desktop':'[Desktop Entry]\nName=RustDesk\nGenericName=Remote Desktop\nComment=Remote Desktop\nExec=rustdesk %u\nIcon=rustdesk\n',
                'flutter/windows/runner/Runner.rc':'VALUE "ProductName", "RustDesk" "\\0"\nVALUE "FileDescription", "Remote Desktop" "\\0"\nVALUE "CompanyName", "Purslane" "\\0"\n',
                'res/msi/Package/Package.wxs':'<Package Name="$(var.Product)" Manufacturer="$(var.Manufacturer)" UpgradeCode="$(var.UpgradeCode)"><SummaryInformation Description="$(var.Description)"/></Package>',
                'res/msi/Package/UI/MyInstallDirDlg.wxs':'<Dialog Title="!(loc.InstallDirDlg_Title)"/>',
                'res/rpm-flutter.spec':'Summary: RPM package\nVendor: rustdesk\nURL: https://rustdesk.com\n',
                'flutter/android/app/build.gradle':'applicationId "com.carriez.flutter_hbb"\n',
                'flutter/macos/Runner/Configs/AppInfo.xcconfig':'PRODUCT_NAME = RustDesk\n',
                'res/rustdesk.service':'ExecStart=/usr/bin/rustdesk --service\n',
                'res/icon.png':'original-image',
            }
            for file,text in files.items():
                p=root/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text, encoding='utf-8')
            plist=root/'flutter/macos/Runner/Info.plist'
            plist.write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.carriez.flutterHbb','CFBundleName':'$(PRODUCT_NAME)'}))
            name='Radar "$name" & Co.'
            snapshot=b.resolve({'CUSTOM_DISPLAY_NAME':name,'CUSTOM_PUBLISHER':'Bill Radar (houxnan)',
                                'CUSTOM_DESCRIPTION':'Remote support'},'fork/client')
            # Reproduce Windows' legacy locale without requiring a Windows host.
            # Source generation and snapshot consumers must remain UTF-8 even
            # when an implicit text open would select cp1252.
            original_open=io.open
            def windows_open(file,mode='r',buffering=-1,encoding=None,errors=None,newline=None,closefd=True,opener=None):
                if 'b' not in mode and encoding is None:encoding='cp1252'
                return original_open(file,mode,buffering,encoding,errors,newline,closefd,opener)
            with patch('io.open',side_effect=windows_open):
                digest=b.apply(root,snapshot)
                self.assertEqual(b.load(root/'branding.json','fork/client'),snapshot)
                self.assertEqual(b.msi_arguments(root)[0],'--custom-arp')
                self.assertIn('基于 RustDesk', (root/'flutter/lib/common/branding_values.dart').read_text(encoding='utf-8'))
            self.assertEqual(digest,hashlib.sha256((root/'branding.json').read_bytes()).hexdigest())
            self.assertEqual(ET.fromstring((root/'res/msi/Package/Package.wxs').read_text(encoding='utf-8')).get('Name'),name)
            self.assertEqual(plistlib.loads(plist.read_bytes())['CFBundleIdentifier'],'com.carriez.flutterHbb')
            for file in ['flutter/android/app/build.gradle','flutter/macos/Runner/Configs/AppInfo.xcconfig',
                         'res/rustdesk.service','res/icon.png']:
                self.assertEqual((root/file).read_text(encoding='utf-8'),files[file])
            self.assertIn(r'\$name',(root/'flutter/lib/common/branding_values.dart').read_text(encoding='utf-8'))
            self.assertIn('Exec=rustdesk %u',(root/'res/rustdesk.desktop').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
