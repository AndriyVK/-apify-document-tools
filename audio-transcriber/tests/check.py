"""Local checks for audio-transcriber (calls the real Groq API: needs GROQ_API_KEY or a proxy that adds it).

Usage: python -m tests.check <media_dir>
<media_dir> must contain speech-en.mp3, speech-uk.mp3 (speech with the sentences below), video-en.mp4 (same English
speech in a video), long-en.mp3 (> 20 minutes, e.g. speech-en concatenated 30 times) and noaudio.png (any image).
"""
import os
import re
import sys
import tempfile

from src.transcribe import TranscriptionError, to_srt, to_vtt, transcribe

EN = ['warehouse', 'pallets', 'building', 'materials', 'third', 'quarter', 'delivery', 'routing', 'schedule', 'cement']
UK = ['отримав', 'будівельних', 'матеріалів', 'протягом', 'третього', 'кварталу', 'доставки', 'скоротилися', 'графіка']


def words_found(text, words):
    t = text.lower()
    return sum(w in t for w in words) / len(words)


def main():
    d = sys.argv[1]
    r, results = None, []

    def run(name, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            return transcribe(os.path.join(d, name), tmp, **kw)

    r = run('speech-en.mp3')
    results.append((words_found(r['text'], EN) >= 0.9 and r['minutes'] == 1, f"English MP3: {words_found(r['text'], EN):.2f} of key words"))
    r = run('speech-uk.mp3', language='uk')
    results.append((words_found(r['text'], UK) >= 0.8, f"Ukrainian MP3: {words_found(r['text'], UK):.2f} of key words"))
    r = run('video-en.mp4', quality='fast')
    results.append((words_found(r['text'], EN) >= 0.9, 'English speech from MP4 video'))
    r = run('long-en.mp3', quality='fast')
    starts = [s['start'] for s in r['segments']]
    results.append((r['duration'] > 1200 and all(a <= b for a, b in zip(starts, starts[1:]))
                    and r['segments'][-1]['end'] > r['duration'] - 60, 'long file: chunks stitched with continuous timestamps'))
    srt, vtt = to_srt(r['segments'][:2]), to_vtt(r['segments'][:2])
    results.append((re.match(r'1\n00:00:0\d,\d{3} --> ', srt) is not None and vtt.startswith('WEBVTT'), 'SRT/VTT format'))
    r = run('long-en.mp3', quality='fast', max_minutes=3)
    results.append((r['truncated'] and r['minutes'] == 3 and r['segments'][-1]['start'] < 180, 'charge limit stops at 3 minutes'))
    try:
        run('noaudio.png')
        results.append((False, 'file without audio rejected'))
    except TranscriptionError:
        results.append((True, 'file without audio rejected'))

    for ok, msg in results:
        print(f"{'OK ' if ok else 'BAD'} {msg}")
    bad = sum(not ok for ok, _ in results)
    print(f'\n{len(results) - bad}/{len(results)} passed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
