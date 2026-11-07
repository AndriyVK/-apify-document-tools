"""Speech Whisper skipped: audio-transcriber run UA8lX45Jd7XfYuNBY (7.11.2026) wrote "The" for 0:18.8-0:25.4."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src import transcribe as tr  # noqa: E402


def _audio(path):
    # 0-4 s tone, 4-12 s silence, 12-20 s tone, 20-30 s silence
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=4',
                    '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono:d=8', '-f', 'lavfi', '-i', 'sine=frequency=300:duration=8',
                    '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono:d=10',
                    '-filter_complex', '[0][1][2][3]concat=n=4:v=0:a=1', '-ac', '1', '-ar', '16000', path], check=True)


class Gaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.path = os.path.join(cls.tmp, 'a.mp3')
        _audio(cls.path)

    def test_sound_seconds(self):
        self.assertLess(tr._sound_seconds(self.path, 4, 8), 1)
        self.assertGreater(tr._sound_seconds(self.path, 12, 8), 7)

    def test_candidates(self):
        segs = [{'start': 0, 'end': 4, 'text': 'The warehouse in Lviv received pallets'},
                {'start': 12, 'end': 19, 'text': 'The'}]
        self.assertEqual(tr._candidates(segs, 30), [(4, 12, None), (12, 19, 1), (19, 30, None)])
        self.assertEqual(tr._candidates([{'start': 0, 'end': 6, 'text': 'x' * 80}], 6), [])

    def test_fill(self):
        segs = [{'start': 0, 'end': 4, 'text': 'The warehouse in Lviv received pallets'},
                {'start': 12, 'end': 19, 'text': 'The'}]
        heard = {'segments': [{'start': 0.3, 'end': 7.0, 'text': 'next shipment of cement and steel rods is planned.',
                               'no_speech_prob': 0.01, 'avg_logprob': -0.2}]}
        with mock.patch.object(tr, 'transcribe_chunk', return_value=heard) as call:
            out, gaps = tr._fill_gaps(None, self.path, self.tmp, segs, 30, model='m', language='en')
        self.assertEqual(call.call_count, 1)            # the silent stretches are not sent again
        self.assertEqual([g['status'] for g in gaps], ['filled'])
        self.assertEqual([s['text'] for s in out], ['The warehouse in Lviv received pallets',
                                                    'next shipment of cement and steel rods is planned.'])
        self.assertEqual(out[1]['start'], 12.3)

    def test_unclear(self):
        segs = [{'start': 12, 'end': 19, 'text': 'The'}]
        with mock.patch.object(tr, 'transcribe_chunk', return_value={'segments': []}):
            out, gaps = tr._fill_gaps(None, self.path, self.tmp, segs, 20, model='m', language='en')
        self.assertEqual(out, segs)
        self.assertEqual(gaps, [{'start': 0.0, 'end': 12, 'status': 'unclear', 'text': ''},   # 0-4 s of sound
                                {'start': 12, 'end': 19, 'status': 'unclear', 'text': 'The'}])


if __name__ == '__main__':
    unittest.main()
