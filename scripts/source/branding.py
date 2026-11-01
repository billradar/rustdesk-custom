"""Freeze public branding variables and apply display-only source transforms."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr

TEXT = (
    'CUSTOM_DISPLAY_NAME', 'CUSTOM_ABOUT_TITLE', 'CUSTOM_ANDROID_APP_LABEL',
    'CUSTOM_ANDROID_SERVICE_LABEL', 'CUSTOM_LINUX_APP_LABEL', 'CUSTOM_DESCRIPTION',
    'CUSTOM_SLOGAN', 'CUSTOM_INSTALLER_TITLE', 'CUSTOM_INSTALLER_DESCRIPTION',
    'CUSTOM_PUBLISHER', 'CUSTOM_MAINTAINER', 'CUSTOM_CONTACT_EMAIL',
    'CUSTOM_CUSTOMIZATION_NOTICE', 'CUSTOM_WINDOWS_COMPANY_NAME',
    'CUSTOM_LINUX_GENERIC_NAME', 'CUSTOM_LINUX_COMMENT')
URLS = ('CUSTOM_WEBSITE_URL', 'CUSTOM_HELP_URL', 'CUSTOM_SUPPORT_URL', 'CUSTOM_PRIVACY_URL')
VISUAL = ('CUSTOM_LOGO_PATH', 'CUSTOM_LOGO_LIGHT_PATH', 'CUSTOM_LOGO_DARK_PATH',
          'CUSTOM_APP_ICON_PATH', 'CUSTOM_TRAY_ICON_PATH')
LOCALIZED = tuple(k for k in TEXT if k not in ('CUSTOM_PUBLISHER', 'CUSTOM_MAINTAINER',
                                               'CUSTOM_CONTACT_EMAIL', 'CUSTOM_WINDOWS_COMPANY_NAME'))
NAMES = TEXT + URLS + tuple(k + suffix for k in LOCALIZED for suffix in ('_EN', '_ZH_CN')) + VISUAL
SCHEMA = 'public-branding-v1'


def resolve(environ, repository):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}', repository) or repository.rsplit('/',1)[-1] in ('.','..'):
        raise ValueError('Branding requires a valid build repository')
    from scripts.signing.production_config import scan_bytes
    values = {}
    for key in NAMES:
        value = str(environ.get(key, '')).strip()
        if not value:
            continue
        if key in VISUAL:
            raise ValueError(key + ': reserved image interface; leave empty until image processing is implemented')
        if len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(key + ': unsupported text length or control characters')
        if any(marker in value for marker in ('$(', '!(')):
            raise ValueError(key + ': build-preprocessor expressions are not branding text')
        scan_bytes(value.encode())
        if key in URLS:
            url = urlsplit(value)
            if url.scheme != 'https' or not url.hostname or url.username or url.password or any(c.isspace() for c in value):
                raise ValueError(key + ': HTTPS URL without credentials required')
            _ = url.port
        if key.startswith('CUSTOM_CONTACT_EMAIL') and not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', value):
            raise ValueError(key + ': public email address required')
        values[key] = value
    supplied = set(values)
    for suffix in ('', '_EN', '_ZH_CN'):
        name = values.get('CUSTOM_DISPLAY_NAME' + suffix) or values.get('CUSTOM_DISPLAY_NAME')
        if name:
            defaults = {
                'CUSTOM_ABOUT_TITLE': ('关于 ' if suffix == '_ZH_CN' else 'About ') + name,
                'CUSTOM_ANDROID_APP_LABEL': name, 'CUSTOM_LINUX_APP_LABEL': name,
                'CUSTOM_ANDROID_SERVICE_LABEL': name + (' 输入服务' if suffix == '_ZH_CN' else ' Input'),
                'CUSTOM_INSTALLER_TITLE': name + (' 安装程序' if suffix == '_ZH_CN' else ' Installer')}
            for key, value in defaults.items():
                values.setdefault(key + suffix, values[key] if key in supplied else value)
        publisher = values.get('CUSTOM_PUBLISHER')
        if publisher:
            notice = ('基于 RustDesk 定制，由 ' + publisher + ' 构建与发布。' if suffix == '_ZH_CN'
                      else 'Based on RustDesk; customized and published by ' + publisher + '.')
            key='CUSTOM_CUSTOMIZATION_NOTICE'
            values.setdefault(key + suffix, values[key] if key in supplied else notice)
            values.setdefault('CUSTOM_WINDOWS_COMPANY_NAME', publisher)
    if values.get('CUSTOM_DESCRIPTION'):
        values.setdefault('CUSTOM_LINUX_COMMENT', values['CUSTOM_DESCRIPTION'])
        values.setdefault('CUSTOM_INSTALLER_DESCRIPTION', values['CUSTOM_DESCRIPTION'])
    maintainer=values.get('CUSTOM_MAINTAINER','')
    if maintainer and not values.get('CUSTOM_CONTACT_EMAIL') and not re.fullmatch(r'[^<>]+ <[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+>',maintainer):
        raise ValueError('CUSTOM_MAINTAINER requires CUSTOM_CONTACT_EMAIL or a complete Name <email> value')
    homepage = 'https://github.com/' + repository
    for key, default in (('CUSTOM_WEBSITE_URL', homepage), ('CUSTOM_HELP_URL', homepage + '#readme'),
                         ('CUSTOM_SUPPORT_URL', homepage + '/issues')):
        values.setdefault(key, default)
    return dict(schema=SCHEMA, repository=repository, values=values)


def load(path, repository):
    snapshot = json.loads(Path(path).read_text(encoding='utf-8')) if path else resolve({}, repository)
    if snapshot.get('schema') != SCHEMA or snapshot.get('repository') != repository:
        raise ValueError('Branding snapshot belongs to a different build repository')
    if resolve(snapshot['values'], repository) != snapshot:
        raise ValueError('Branding snapshot is invalid or not normalized')
    return snapshot


def replace_once(path, old, new):
    text = path.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise ValueError('Branding source interface changed: ' + path.name)
    path.write_text(text.replace(old, new), encoding='utf-8')


def native(values, key):
    return values.get(key + '_EN') or values.get(key, '')


def dart_literal(value):
    # JSON supplies quotes/backslash/Unicode escaping; Dart additionally interpolates $.
    return json.dumps(value, ensure_ascii=False).replace('$', r'\$')


def deb_fields(values):
    """Public package metadata only; never alter package/dependency/service identity."""
    result={}
    for key,field in (('CUSTOM_DESCRIPTION','Description'),('CUSTOM_WEBSITE_URL','Homepage')):
        if native(values,key):result[field]=native(values,key)
    name=native(values,'CUSTOM_MAINTAINER')
    email=values.get('CUSTOM_CONTACT_EMAIL','')
    if name or email:
        result['Maintainer']=name if '<' in name else (name or values.get('CUSTOM_PUBLISHER') or 'RustDesk')+' <'+email+'>'
    return result


def rebrand_deb(package, tree):
    path=Path(tree)/'branding.json'
    if not path.is_file():return  # Historical/test sources have no branding snapshot.
    snapshot=json.loads(path.read_text(encoding='utf-8'))
    fields=deb_fields(load(path,snapshot['repository'])['values'])
    if not fields:return
    with tempfile.TemporaryDirectory(prefix='rustdesk-public-branding-') as temp:
        root=Path(temp);stage=root/'package'
        subprocess.run(['dpkg-deb','--raw-extract',str(package),str(stage)],check=True)
        control=stage/'DEBIAN/control';text=control.read_text(encoding='utf-8')
        for field,value in fields.items():
            text,count=re.subn(r'^'+field+r':[^\n]*',lambda _:field+': '+value,text,flags=re.M)
            if count!=1:raise ValueError('Missing/duplicate package branding field: '+field)
        control.write_text(text, encoding='utf-8')
        output=root/'branded.deb'
        subprocess.run(['dpkg-deb','-Zxz','--build','--root-owner-group',str(stage),str(output)],
                       check=True,stdout=subprocess.DEVNULL)
        shutil.copy2(output,package)


def msi_arguments(tree):
    path=Path(tree)/'branding.json'
    if not path.is_file():return []
    snapshot=json.loads(path.read_text(encoding='utf-8'))
    values=load(path,snapshot['repository'])['values']
    arp={}
    for name,field,value in (
            ('Contact','ARPCONTACT',values.get('CUSTOM_CONTACT_EMAIL') or values.get('CUSTOM_WEBSITE_URL')),
            ('HelpLink','ARPHELPLINK',values.get('CUSTOM_SUPPORT_URL')),
            ('ReadMe','ARPREADME',values.get('CUSTOM_HELP_URL')),
            ('Comments','ARPCOMMENTS',native(values,'CUSTOM_DESCRIPTION'))):
        if value:arp[name]={'msi':field,'v':value}
    return ['--custom-arp',json.dumps(arp,ensure_ascii=False)] if arp else []


def apply(tree, snapshot):
    tree = Path(tree)
    values = snapshot['values']
    generated = tree / 'flutter/lib/common/branding_values.dart'
    if not generated.is_file():
        raise ValueError('Branding patch must be applied before variable injection')
    generated.write_text('// Generated public build branding; no secrets.\n'
                         'const Map<String, String> customBranding = {\n' +
                         ''.join('  ' + dart_literal(k) + ': ' + dart_literal(v) + ',\n'
                                 for k, v in sorted(values.items())) + '};\n', encoding='utf-8')
    # Do not change APP_NAME, applicationId, bundle ID, service/URI, or payload paths.
    manifest = tree / 'flutter/android/app/src/main/AndroidManifest.xml'
    for key, original, resource in (
            ('CUSTOM_ANDROID_APP_LABEL', 'RustDesk', 'custom_brand_app_label'),
            ('CUSTOM_ANDROID_SERVICE_LABEL', 'RustDesk Input', 'custom_brand_service_label')):
        if native(values, key) or values.get(key + '_ZH_CN'):
            replace_once(manifest, 'android:label="' + original + '"',
                         'android:label="@string/' + resource + '"')
    for suffix, folder in (('', 'values'), ('_EN', 'values-en'), ('_ZH_CN', 'values-zh-rCN')):
        entries = []
        for key, original, resource in (
                ('CUSTOM_ANDROID_APP_LABEL', 'RustDesk', 'custom_brand_app_label'),
                ('CUSTOM_ANDROID_SERVICE_LABEL', 'RustDesk Input', 'custom_brand_service_label')):
            if not (native(values, key) or values.get(key + '_ZH_CN')):
                continue
            value = values.get(key + suffix) or native(values, key) or original
            value = value.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('@', r'\@').replace('?', r'\?')
            entries.append('  <string name="' + resource + '" formatted="false">' + escape(value) + '</string>')
        if entries:
            path = tree / 'flutter/android/app/src/main/res' / folder / 'custom_branding.xml'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('<resources>\n' + '\n'.join(entries) + '\n</resources>\n', encoding='utf-8')
    desktop = tree / 'res/rustdesk.desktop'
    text = desktop.read_text(encoding='utf-8')
    for key, field in (('CUSTOM_LINUX_APP_LABEL', 'Name'), ('CUSTOM_LINUX_GENERIC_NAME', 'GenericName'), ('CUSTOM_LINUX_COMMENT', 'Comment')):
        value = native(values, key)
        localized = values.get(key + '_ZH_CN')
        if value or localized:
            pattern = r'^' + field + r'=([^\n]*)$'
            matches = list(re.finditer(pattern, text, re.M))
            # Name also appears in the desktop action section: alter the main entry only.
            if not matches:
                raise ValueError('Missing desktop display field: ' + field)
            match = matches[0]
            new = field + '=' + (value or match[1]).replace('\\', '\\\\')
            if localized:
                new += '\n' + field + '[zh_CN]=' + localized.replace('\\', '\\\\')
            text = text[:match.start()] + new + text[match.end():]
    desktop.write_text(text, encoding='utf-8')
    rc = tree / 'flutter/windows/runner/Runner.rc'
    for key, field in (('CUSTOM_DISPLAY_NAME', 'ProductName'), ('CUSTOM_DESCRIPTION', 'FileDescription'),
                       ('CUSTOM_WINDOWS_COMPANY_NAME', 'CompanyName')):
        value = native(values, key)
        if value:
            text = rc.read_text(encoding='utf-8')
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            pattern = r'(VALUE "' + field + r'", )"[^\n]*?(" "\\0")'
            text, count = re.subn(pattern, lambda m: m[1] + '"' + escaped + m[2], text)
            if count != 1:
                raise ValueError('Missing Windows display field: ' + field)
            rc.write_text(text, encoding='utf-8')
    name = native(values, 'CUSTOM_DISPLAY_NAME')
    if name:
        path = tree / 'flutter/macos/Runner/Info.plist'
        data = plistlib.loads(path.read_bytes())
        data['CFBundleDisplayName'] = name
        path.write_bytes(plistlib.dumps(data, sort_keys=False))
    package = tree / 'res/msi/Package/Package.wxs'
    if name:
        replace_once(package, 'Name="$(var.Product)"', 'Name=' + quoteattr(name))
    company = native(values, 'CUSTOM_WINDOWS_COMPANY_NAME')
    if company:
        replace_once(package, 'Manufacturer="$(var.Manufacturer)"', 'Manufacturer=' + quoteattr(company))
    description = native(values, 'CUSTOM_INSTALLER_DESCRIPTION')
    if description:
        replace_once(package, 'Description="$(var.Description)"', 'Description=' + quoteattr(description))
    title = native(values, 'CUSTOM_INSTALLER_TITLE')
    if title:
        replace_once(tree / 'res/msi/Package/UI/MyInstallDirDlg.wxs',
                     'Title="!(loc.InstallDirDlg_Title)"', 'Title=' + quoteattr(title))
    for path in (tree / 'res').glob('rpm*.spec'):
        text = path.read_text(encoding='utf-8')
        for field, value in (('Summary', native(values, 'CUSTOM_DESCRIPTION')),
                             ('Vendor', native(values, 'CUSTOM_MAINTAINER') or native(values, 'CUSTOM_PUBLISHER')),
                             ('URL', values.get('CUSTOM_WEBSITE_URL'))):
            if value:
                text = re.sub(r'^' + field + r':[^\n]*', lambda _: field + ': ' + value.replace('%', '%%'), text, flags=re.M)
        path.write_text(text, encoding='utf-8')
    (tree / 'branding.json').write_text(json.dumps(snapshot, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return hashlib.sha256((tree / 'branding.json').read_bytes()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    snapshot = resolve(os.environ, args.repository)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print('Public branding variables validated and frozen (values omitted)')
