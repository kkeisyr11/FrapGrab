"""Fetch the pinned Windows media tools, verifying the complete upstream archive."""
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = '9.0.2'
URL = f'https://github.com/GyanD/codexffmpeg/releases/download/{VERSION}/ffmpeg-{VERSION}-full_build.zip'
SHA256 = '759d0a9831c436a0eb331ad36f236c06cb04aaa0005da46571f0e9d3d9206f6b'
ROOT = Path(__file__).resolve().parents[1]


def prepare():
    with tempfile.TemporaryDirectory(prefix='autoclip-media-') as folder:
        archive = Path(folder) / 'ffmpeg.zip'
        print(f'Downloading FFmpeg {VERSION}...')
        urllib.request.urlretrieve(URL, archive)
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != SHA256:
            raise RuntimeError('FFmpeg archive SHA-256 mismatch')
        with zipfile.ZipFile(archive) as bundle:
            prefix = f'ffmpeg-{VERSION}-full_build/'
            for name in ('ffmpeg.exe', 'ffprobe.exe'):
                target = ROOT / 'tools' / name
                with bundle.open(prefix + 'bin/' + name) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out)
            licenses = ROOT / 'licenses'
            licenses.mkdir(exist_ok=True)
            for source, target in [('LICENSE', 'FFmpeg-GPL-3.0.txt'), ('README.txt', 'FFmpeg-build.txt')]:
                (licenses / target).write_bytes(bundle.read(prefix + source))
    print('FFmpeg and FFprobe ready in tools/')


if __name__ == '__main__':
    prepare()
