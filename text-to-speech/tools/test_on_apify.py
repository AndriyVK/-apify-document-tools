"""Runs the deployed Actor and checks the audio; measures the platform cost per audio minute.

Usage: python tools/test_on_apify.py [--charges]
The audio of one run is transcribed back with Groq Whisper (GROQ_API_KEY or a proxy that adds it).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import API, call  # noqa: E402

ACTOR = 'text-to-speech'
STORE = 'FloomuI2DrQCJazY8'
UK = 'Склад у Львові отримав 1240 палет будівельних матеріалів'
LONG = ('The warehouse in Lviv received 1,240 pallets of building materials during the third quarter. '
        'Delivery times improved by twelve percent after the new routing schedule was introduced. ') * 40


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(30)
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def transcribe(url, lang):
    with tempfile.NamedTemporaryFile(suffix='.mp3') as f:
        f.write(urllib.request.urlopen(url, timeout=120).read())
        f.flush()
        cmd = ['curl', '-sS', '-m', '120', 'https://api.groq.com/openai/v1/audio/transcriptions',
               '-F', 'model=whisper-large-v3', '-F', f'language={lang}', '-F', f'file=@{f.name}']
        if os.environ.get('GROQ_API_KEY'):
            cmd[3:3] = ['-H', 'Authorization: Bearer ' + os.environ['GROQ_API_KEY']]
        return json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout).get('text', '')


def main():
    charges = '--charges' in sys.argv
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    bad = 0

    def check(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name}")

    r, items = run(act['id'], {})
    it = items[0] if items else {}
    check(f"default input: {r['status']}, {it.get('durationSeconds')} s", r['status'] == 'SUCCEEDED'
          and 3 < (it.get('durationSeconds') or 0) < 20 and 'neural voice' in transcribe(it['audioUrl'], 'en'))
    src = [{'url': f'{API}/key-value-stores/{STORE}/records/{k}'} for k in ('doc-uk.docx', 'page-uk.html',
                                                                              'broken-file.pdf')]
    r, items = run(act['id'], {'text': '', 'sources': src, 'voice': 'uk_UA-mykyta-high', 'format': 'mp3'})
    by = {i['url'].rsplit('/', 1)[-1]: i for i in items}
    heard = transcribe(by.get('doc-uk.docx', {}).get('audioUrl', ''), 'uk') if by.get('doc-uk.docx') else ''
    check(f'DOCX read by a downloaded voice (mykyta): {heard[:60]}', 'Львов' in heard)
    check('HTML read', (by.get('page-uk.html') or {}).get('durationSeconds', 0) > 3)
    check('broken file -> error', 'error' in (by.get('broken-file.pdf') or {}))
    srt = urllib.request.urlopen(by['doc-uk.docx']['srtUrl'], timeout=60).read().decode()
    check('SRT downloads', srt.startswith('1\n00:00:00,000 -->'))
    r, items = run(act['id'], {'text': LONG, 'voice': 'en_US-john-medium', 'format': 'mp3', 'subtitles': False})
    it = items[0]
    mins = it['durationSeconds'] / 60
    print(f"  long text: {it['characters']} chars -> {mins:.1f} min audio in {r['stats']['runTimeSecs']:.0f}s, "
          f"{r['stats']['computeUnits']:.4f} CU = {r['stats']['computeUnits'] / mins:.4f} CU per audio minute")
    check('long text', mins > 5)
    if charges:
        got = (r.get('chargedEventCounts') or {}).get('audio-minute')
        check(f'charged audio-minute={int(mins) + 1} (got {got})', got == int(mins) + 1)
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
