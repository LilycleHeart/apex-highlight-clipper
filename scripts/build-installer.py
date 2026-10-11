"""Wrap a verified portable release in an offline Windows EXE installer.

Uses only the portable file manifest and the pinned FFmpeg distribution.
Generated payload lists, compiler inputs and installers stay under publish/.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FFMPEG_SHA256 = '60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(args):
    bundle = Path(args.bundle).resolve()
    output = bundle.parent
    if not output.is_relative_to(ROOT / 'publish'):
        raise ValueError('Installer output must remain under publish/')
    report = json.loads((output / 'validation-report.json').read_text('utf-8'))
    archive = output / (bundle.name + '.zip')
    if report.get('status') != 'pass' or digest(archive) != report.get('sha256'):
        raise ValueError('Portable archive does not match its validation report')
    inventory = json.loads((bundle / 'FILES.sha256.json').read_text('utf-8'))
    sources = {}
    for name, expected in inventory.items():
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle) or digest(path) != expected:
            raise ValueError('Portable payload changed: ' + name)
        sources[name] = path
    sources['FILES.sha256.json'] = bundle / 'FILES.sha256.json'
    ffmpeg = Path(args.ffmpeg).resolve()
    if digest(ffmpeg) != FFMPEG_SHA256:
        raise ValueError('FFmpeg distribution checksum mismatch')
    temporary = output / '.installer-build'
    temporary.mkdir(exist_ok=True)
    with zipfile.ZipFile(ffmpeg) as z:
        for name in ['bin/ffmpeg.exe', 'bin/ffprobe.exe', 'LICENSE', 'README.txt']:
            target_name = Path(name).name if name.startswith('bin/') else 'FFmpeg-' + name
            local = temporary / target_name
            local.write_bytes(z.read('ffmpeg-9.0.2-essentials_build/' + name))
            sources['tools/' + target_name] = local
    combined = {name: digest(path) for name, path in sources.items()}
    manifest = temporary / 'INSTALLER-FILES.sha256.json'
    manifest.write_text(json.dumps(combined, indent=2), 'utf-8')
    sources[manifest.name] = manifest
    payload = temporary / 'payload.iss'
    lines = ['[Files]']
    for name, source in sorted(sources.items()):
        directory = Path(name).parent.as_posix().replace('/', '\\')
        destination = '{app}' + ('\\' + directory if directory != '.' else '')
        # An explicit allowlist prevents local logs, caches and diagnostics entering the EXE.
        lines.append(f'Source: "{source}"; DestDir: "{destination}"; DestName: "{Path(name).name}"; Flags: ignoreversion')
    payload.write_text('\n'.join(lines), 'utf-8-sig')
    version = json.loads((ROOT / 'electron-ui/package.json').read_text('utf-8'))['version']
    subprocess.run([str(Path(args.iscc).resolve()), '/Qp', '/DProductVersion=' + version,
                    '/DInstallerOutput=' + str(output), '/DPayloadInclude=' + str(payload),
                    str(ROOT / 'scripts/windows-installer.iss')], check=True)
    exe = output / f'Apex-Clipper-{version}-Setup-x64.exe'
    checksum = digest(exe)
    (output / (exe.name + '.sha256')).write_text(checksum + '  ' + exe.name + '\n', 'utf-8')
    (output / 'installer-report.json').write_text(json.dumps({
        'status': 'built', 'installer': exe.name, 'bytes': exe.stat().st_size,
        'sha256': checksum, 'portable_sha256': report['sha256'],
        'ffmpeg_sha256': FFMPEG_SHA256, 'payload_files': len(sources),
        'core_validation': 'reused unchanged portable payload checks',
    }, indent=2), 'utf-8')
    # These inputs are ours and are already embedded in the installer.
    for path in temporary.iterdir():
        if path.is_file() and not path.is_symlink():
            path.unlink()
    temporary.rmdir()
    print(exe)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--iscc', required=True)
    parser.add_argument('--ffmpeg', default=str(ROOT / 'publish/downloads/ffmpeg-9.0.2-essentials_build.zip'))
    build(parser.parse_args())
