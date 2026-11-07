"""audio(): a format choice left in the info() result must not be downloaded instead of ours."""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src import fetch  # noqa: E402


def _make(path, args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args, path], check=True)


class AudioTest(unittest.TestCase):
    def test_old_requested_formats_are_ignored(self):
        src = tempfile.mkdtemp()
        with_sound = os.path.join(src, 'with_sound.mp4')
        no_sound = os.path.join(src, 'no_sound.mp4')
        _make(with_sound, ['-f', 'lavfi', '-i', 'testsrc=size=64x64:duration=2', '-f', 'lavfi', '-i',
                           'sine=duration=2', '-shortest', '-c:v', 'libx264', '-c:a', 'aac'])
        _make(no_sound, ['-f', 'lavfi', '-i', 'testsrc=size=64x64:duration=2', '-c:v', 'libx264', '-an'])
        fmts = [{'format_id': 'h264_540p-0', 'url': 'file://' + with_sound, 'ext': 'mp4', 'acodec': 'aac',
                 'vcodec': 'h264', 'filesize': os.path.getsize(with_sound)},
                {'format_id': 'bytevc1_720p-1', 'url': 'file://' + no_sound, 'ext': 'mp4', 'acodec': 'none',
                 'vcodec': 'h265', 'filesize': os.path.getsize(no_sound)}]
        data = {'id': 'x', 'title': 'x', 'extractor': 'generic', 'extractor_key': 'Generic',
                'webpage_url': 'file://' + with_sound, 'formats': fmts,
                'requested_formats': [dict(fmts[1]), dict(fmts[1])], 'format_id': 'bytevc1_720p-1+bytevc1_720p-1'}
        orig = fetch._opts
        fetch._opts = lambda proxy, workdir=None: {**orig(proxy, workdir), 'enable_file_urls': True}
        try:
            work = tempfile.mkdtemp()
            path = fetch.audio(data, work, None)
        finally:
            fetch._opts = orig
        self.assertTrue(fetch._has_audio(path))


if __name__ == '__main__':
    unittest.main()
