"""Local checks of src.tts. Usage (from the Actor folder): python -m tests.check <corpus_dir> <voice_cache_dir>

Speech is verified by transcribing it back with Groq Whisper (needs GROQ_API_KEY or a proxy that adds it).
"""
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from src.tts import encode, extract_text, load_voice, split_text, synthesize, to_srt

UK = ('Склад у Львові отримав 1240 палет будівельних матеріалів протягом третього кварталу. '
      'Терміни доставки скоротилися на дванадцять відсотків після запровадження нового графіка.')
EN = ('The warehouse in Lviv received 1,240 pallets of building materials during the third quarter.\n\n'
      'Delivery times improved by twelve percent after the new routing schedule was introduced.')


def transcribe(path, lang):
    cmd = ['curl', '-sS', '-m', '120', 'https://api.groq.com/openai/v1/audio/transcriptions',
           '-F', 'model=whisper-large-v3', '-F', f'language={lang}', '-F', f'file=@{path}']
    if os.environ.get('GROQ_API_KEY'):
        cmd[3:3] = ['-H', 'Authorization: Bearer ' + os.environ['GROQ_API_KEY']]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return json.loads(out).get('text', out)


def similarity(a, b):
    n = lambda s: re.sub(r'[^\w ]+', '', re.sub(r'\s+', ' ', s.lower())).strip()  # noqa: E731
    return difflib.SequenceMatcher(None, n(a), n(b)).ratio()


def main():
    d, cache = sys.argv[1], sys.argv[2]
    bad = 0

    def check(name, cond, info=''):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name} {info}")

    t = extract_text(f'{d}/text-en.pdf', 'text-en.pdf', 'application/pdf')
    check('PDF text', 'warehouse in Lviv received' in re.sub(r'\s+', ' ', t), t[:60].replace('\n', ' '))
    t = extract_text(f'{d}/doc-uk.docx', 'doc-uk.docx', '')
    check('DOCX text', 'Склад у Львові' in t, t[:60].replace('\n', ' '))
    t = extract_text(f'{d}/page-uk.html', 'page-uk.html', 'text/html')
    check('HTML text', 'Склад у Львові' in t and '<' not in t, t[:60].replace('\n', ' '))
    with tempfile.TemporaryDirectory() as tmp:
        md = os.path.join(tmp, 'a.md')
        open(md, 'w').write('# Title\n\n- item **bold** [link](http://x)\n\n![img](a.png)\n')
        t = extract_text(md, 'a.md', '')
        check('Markdown cleaned', 'Title' in t and 'item bold link' in t and '](' not in t and '#' not in t, repr(t))
        paras, used, trunc = split_text(EN, 100)
        check('truncation at maxCharacters', trunc and used <= 100 and len(paras) == 1, f'{used} chars')
        paras, used, trunc = split_text('A' * 1000 + '. Next.', 10000)
        check('long sentence split', max(len(s) for p in paras for s in p) <= 401, str([len(s) for s in paras[0]]))

        for vid, text, lang in (('uk_UA-tetiana-high', UK, 'uk'), ('en_US-ljspeech-high', EN, 'en')):
            t0 = time.time()
            voice = load_voice(vid, cache)
            paras, used, _ = split_text(text, 100000)
            pcm, rate, cues = synthesize(voice, paras, 1.0)
            dur = len(pcm) / 2 / rate
            secs = time.time() - t0
            mp3 = os.path.join(tmp, vid + '.mp3')
            encode(pcm, rate, 'mp3', mp3)
            heard = transcribe(mp3, lang)
            sim = similarity(text, heard)
            check(f'{vid}: speech recognisable', sim >= 0.85, f'similarity {sim:.2f}, {dur:.1f}s audio in {secs:.1f}s; '
                  f'heard: {heard[:70]}')
            check(f'{vid}: cues', len(cues) == 2 and cues[0][0] == 0 and cues[1][0] > cues[0][1]
                  and abs(cues[-1][1] - dur) < 0.05, str([(a, b) for a, b, _ in cues]))
        from src.uk_stress import phonemize_uk
        uk = load_voice('uk_UA-mykyta-high', cache)
        _, fixes = phonemize_uk(uk, 'Король і королева повернулися до Парижа, телефон дзвонив.')
        check('Ukrainian stress from the dictionary', fixes >= 3, f'{fixes} words re-stressed')
        pcm, rate, _ = synthesize(uk, [['Він сказав: «Привіт, друзі!»']], 1.0, ukrainian=True)
        q = os.path.join(tmp, 'quotes.mp3')
        encode(pcm, rate, 'mp3', q)
        heard = transcribe(q, 'uk')
        check('quotation marks are not read aloud', 'лапк' not in heard.lower() and 'друз' in heard.lower(), heard)
        voice = load_voice('en_US-ljspeech-high', cache)
        p1, _, c1 = synthesize(voice, split_text(EN, 1000)[0], 1.0)
        p2, _, c2 = synthesize(voice, split_text(EN, 1000)[0], 1.5)
        check('speed 1.5 is clearly shorter', len(p2) < len(p1) * 0.85, f'{len(p2) / len(p1):.2f}')
        srt = to_srt(c1)
        check('SRT format', srt.startswith('1\n00:00:00,000 --> 00:00:0') and '\n2\n' in srt, srt[:60])
        for fmt in ('wav', 'ogg'):
            dest = os.path.join(tmp, 'x.' + fmt)
            encode(p1, 22050, fmt, dest)
            head = open(dest, 'rb').read(4)
            check(f'{fmt} encoded', head == (b'RIFF' if fmt == 'wav' else b'OggS'))
        try:
            extract_text(f'{d}/broken-file.pdf', 'broken-file.pdf', '')
            check('broken file rejected', False)
        except Exception as e:  # noqa: BLE001
            check('broken file rejected', 'TtsError' in type(e).__name__, str(e))
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
