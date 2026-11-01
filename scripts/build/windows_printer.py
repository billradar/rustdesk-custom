"""Stage the reviewed upstream Windows x64 printer payload before EXE/MSI packing."""
import hashlib
from pathlib import Path
import tempfile
from urllib.request import urlopen
import zipfile

BASE = 'https://github.com/rustdesk/hbb_common/releases/download/driver/'
ARCHIVES = {
    'rustdesk_printer_driver_v4-1.4.zip': 'c4cf4d3b48c4d9079b243edc43bb1db03b076282bc259c9f49883e9db20fa8b5',
    'printer_driver_adapter.zip': 'e90e5d52c8807b4c6293c78a52479338715e0bf396b1b34802777b8c452e6781',
}
DRIVER_FILES = (
    'RustDeskPrinterDriver-manifest.ini', 'rustdeskprinterdriver.cat',
    'RustDeskPrinterDriver.gpd', 'RustDeskPrinterDriver.inf',
    'RustDeskPrinterDriverRenderFilter-PipelineConfig.xml',
    'RustDeskPrinterDriverRenderFilter.dll',
)


def validate(release):
    release = Path(release)
    for name in DRIVER_FILES:
        path = release / 'drivers/RustDeskPrinterDriver' / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing printer driver payload: ' + name)
    adapter = release / 'printer_driver_adapter.dll'
    if not adapter.is_file() or not adapter.stat().st_size:
        raise ValueError('Missing printer_driver_adapter.dll')


def stage(release, architecture, cache=None):
    # The official INF declares NTamd64 only. Never relabel its native DLLs as ARM64.
    if architecture == 'aarch64':
        return {'status': 'unsupported', 'reason': 'Official printer driver supports NTamd64 only'}
    if architecture != 'x86_64':
        raise ValueError('Unsupported Windows architecture')
    release = Path(release)
    payload = {}
    with tempfile.TemporaryDirectory(prefix='rustdesk-printer-') as tmp:
        for name, digest in ARCHIVES.items():
            archive = Path(cache) / name if cache is not None else Path(tmp) / name
            if cache is None:
                with urlopen(BASE + name, timeout=120) as response, archive.open('wb') as output:
                    import shutil
                    shutil.copyfileobj(response, output)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
                raise ValueError('Printer archive checksum mismatch: ' + name)
            with zipfile.ZipFile(archive) as source:
                expected = ({'rustdesk_printer_driver_v4-1.4/' + f: 'drivers/RustDeskPrinterDriver/' + f
                             for f in DRIVER_FILES} if name.startswith('rustdesk_')
                            else {'printer_driver_adapter.dll': 'printer_driver_adapter.dll'})
                # Extract only fixed reviewed members; never trust archive paths.
                for member, destination in expected.items():
                    if source.namelist().count(member) != 1:
                        raise ValueError('Missing/duplicate printer archive member: ' + member)
                    data = source.read(member)
                    if not data:
                        raise ValueError('Empty printer payload: ' + member)
                    payload[destination] = data
        for destination, data in payload.items():
            path = release / destination
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    validate(release)
    return {'status': 'bundled', 'archives': dict(ARCHIVES)}
