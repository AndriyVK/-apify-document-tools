"""Audio/video -> text with Groq's Whisper API: ffmpeg prepares speech-quality chunks, Groq transcribes them."""
from __future__ import annotations

import difflib
import json
import math
import os
import re
import subprocess
import time

import httpx

GROQ_URL = 'https://api.groq.com/openai/v1/audio/transcriptions'
MODELS = {'accurate': 'whisper-large-v3', 'fast': 'whisper-large-v3-turbo'}
CHUNK_SECONDS = 600          # 10-minute chunks: ~2.4 MB each at 32 kbit/s, far below the 25 MB API limit
MAX_RETRIES = 6


class TranscriptionError(Exception):
    pass


def probe_duration(path: str) -> float:
    """Duration of the first audio stream in seconds; raises if the file has no audio."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=duration:format=duration',
                          '-of', 'json', path], capture_output=True, text=True, timeout=120)
    try:
        info = json.loads(out.stdout or '{}')
    except json.JSONDecodeError:
        info = {}
    if not info.get('streams'):
        raise TranscriptionError('no audio track found (not an audio/video file, damaged or unsupported)')
    for value in (info['streams'][0].get('duration'), info.get('format', {}).get('duration')):
        try:
            if value and float(value) > 0:
                return float(value)
        except ValueError:
            pass
    raise TranscriptionError('cannot read the audio duration')


def make_chunks(path: str, outdir: str, duration: float) -> list[tuple[str, float]]:
    """Speech-quality mono MP3 chunks (16 kHz, 32 kbit/s). Returns (chunk path, start offset)."""
    chunks = []
    for i in range(math.ceil(duration / CHUNK_SECONDS)):
        start = i * CHUNK_SECONDS
        dest = os.path.join(outdir, f'chunk-{i:04d}.mp3')
        length = min(CHUNK_SECONDS, duration - start)  # never decode (and pay for) audio past the limit
        res = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(start), '-t', f'{length:.3f}', '-i', path,
                              '-vn', '-ac', '1', '-ar', '16000', '-b:a', '32k', dest],
                             capture_output=True, text=True, timeout=900)
        if res.returncode != 0 or not os.path.exists(dest):
            raise TranscriptionError(f'cannot decode the audio: {res.stderr.strip()[:200]}')
        if os.path.getsize(dest) > 1000:  # skip an empty tail
            chunks.append((dest, float(start)))
    if not chunks:
        raise TranscriptionError('the audio track is empty')
    return chunks


def transcribe_chunk(client: httpx.Client, path: str, *, model: str, language: str | None, prompt: str | None) -> dict:
    data = {'model': model, 'response_format': 'verbose_json', 'temperature': '0'}
    if language:
        data['language'] = language
    if prompt:
        data['prompt'] = prompt[:1200]   # user vocabulary (400) + place names (~350) + the previous chunk's end (200)
    headers = {}
    if os.environ.get('GROQ_API_KEY'):  # on Apify; locally a proxy may add the header instead
        headers['Authorization'] = 'Bearer ' + os.environ['GROQ_API_KEY']
    for attempt in range(MAX_RETRIES):
        with open(path, 'rb') as f:
            r = client.post(GROQ_URL, data=data, files={'file': (os.path.basename(path), f, 'audio/mpeg')},
                            headers=headers)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
            wait = _retry_after(r.headers) or min(60, 5 * 2 ** attempt)
            if wait > 300:
                raise TranscriptionError('the speech service is at its usage limit right now; try again later')
            time.sleep(wait)
            continue
        if r.status_code in (401, 403):
            raise TranscriptionError('speech service authorisation failed (Actor configuration problem)')
        raise TranscriptionError(f'speech service error HTTP {r.status_code}: {r.text[:200]}')
    raise TranscriptionError('the speech service did not respond, try again later')


def _retry_after(headers) -> float | None:
    value = headers.get('retry-after')
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _silence(seg: dict) -> bool:
    """Whisper's own rule for music or silence it filled with made-up words ("Thank you", "We'll be right back")."""
    return float(seg.get('no_speech_prob') or 0) > 0.6 and float(seg.get('avg_logprob') or 0) < -1


# Phrases Whisper makes up over music, noise or silence (from its training on subtitled videos). A segment made only of
# them is dropped when the audio gives other signs that nobody speaks there (see _made_up).
_STOCK = [
    "thank you", "thanks for watching", "thank you for watching", "we'll be right back", "we will be right back",
    "please subscribe", "subscribe to my channel", "like and subscribe", "see you next time", "see you in the next video",
    "bye", "you", "music", "applause", "subtitles by the amara.org community", "transcribed by", "subtitles by",
    "дякую за перегляд", "дякую", "підписуйтесь на канал", "продовження буде", "субтитри", "редактор субтитрів",
    "спасибо", "спасибо за просмотр", "продолжение следует", "подписывайтесь на канал", "субтитры", "редактор субтитров",
    "untertitel", "untertitel im auftrag des zdf", "sous-titres", "sous-titrage", "merci", "gracias", "subtítulos",
]
_STOCK_RE = re.compile(r'^(?:(?:' + '|'.join(re.escape(p) for p in sorted(_STOCK, key=len, reverse=True))
                       + r')[\s.,!?…]*)+$', re.IGNORECASE)


def _made_up(seg: dict, text: str) -> bool:
    """A stock phrase where the audio shows no clear speech, or one stretched over a long stretch of audio."""
    plain = re.sub(r'[\[\]()♪*#~-]', ' ', text).strip()
    if not plain:
        return True                                   # "(music)", "♪♪"
    length = float(seg.get('end') or 0) - float(seg.get('start') or 0)
    if length > 20 and len(plain) < length:          # under 1 character a second for 20+ s: speech runs 10-15 a second
        return True
    if not _STOCK_RE.match(plain):
        return False
    return (float(seg.get('no_speech_prob') or 0) > 0.3 or float(seg.get('avg_logprob') or 0) < -0.7
            or length > 3 + len(plain) / 4)            # a few words over many seconds: nobody is saying them


# Ukrainian place names Whisper often mishears ("Lviv" -> "Elvive"). Passed as part of the prompt, spelled the way the
# output language writes them; with no language set, English and Ukrainian spellings both.
GLOSSARY = {
    'en': 'Kyiv, Lviv, Kharkiv, Odesa, Dnipro, Zaporizhzhia, Vinnytsia, Mykolaiv, Kherson, Chernihiv, Poltava, '
          'Ivano-Frankivsk, Ternopil, Lutsk, Rivne, Uzhhorod, Chernivtsi, Zhytomyr, Sumy, Cherkasy, Kryvyi Rih, Mariupol.',
    'uk': 'Київ, Львів, Харків, Одеса, Дніпро, Запоріжжя, Вінниця, Миколаїв, Херсон, Чернігів, Полтава, '
          'Івано-Франківськ, Тернопіль, Луцьк, Рівне, Ужгород, Чернівці, Житомир, Суми, Черкаси, Кривий Ріг, Маріуполь.',
    'ru': 'Киев, Львов, Харьков, Одесса, Днепр, Запорожье, Винница, Николаев, Херсон, Чернигов, Полтава, '
          'Ивано-Франковск, Тернополь, Луцк, Ровно, Ужгород, Черновцы, Житомир, Сумы, Черкассы, Кривой Рог, Мариуполь.',
}


def _prompt(vocabulary: str | None, language: str | None) -> str:
    """The user's own vocabulary first, then the place names for the spoken language."""
    if language is None:
        names = GLOSSARY['en'] + ' ' + GLOSSARY['uk']
    else:
        names = GLOSSARY.get(language, '')
    return ' '.join(p for p in ((vocabulary or '').strip()[:400], names) if p)


def _prompt_words(prompt: str) -> set[str]:
    return {w for w in re.findall(r'\w+', prompt.lower()) if len(w) >= 3}


_LATIN_SCRIPT = {'english', 'german', 'french', 'spanish', 'portuguese', 'italian', 'polish', 'dutch', 'turkish', 'czech',
                 'romanian', 'swedish', 'indonesian', 'vietnamese', 'danish', 'norwegian', 'finnish', 'hungarian',
                 'slovak', 'croatian', 'lithuanian', 'latvian', 'estonian', 'malay', 'tagalog', 'swahili'}


def _echoed(res: dict, words: set[str]) -> bool:
    """Whisper sometimes writes out its prompt instead of the speech ("Київ, Львів, Харків..." over an English
    recording, with the names misspelled). Signs: a segment or most of the chunk made of prompt words, or text in
    Cyrillic where Whisper itself detected a Latin-script language."""
    if not words:
        return False
    text = ' '.join(s.get('text') or '' for s in res.get('segments') or [])
    letters = re.findall(r'[^\W\d_]', text)
    cyrillic = sum(1 for c in letters if '\u0400' <= c <= '\u04ff')
    if (res.get('language') or '').lower() in _LATIN_SCRIPT and letters and cyrillic > 0.5 * len(letters):
        return True

    def hits(part):
        found = re.findall(r'\w+', part.lower())
        return len(found), sum(1 for w in found if w in words or difflib.get_close_matches(w, words, 1, 0.7))
    total = hit = 0
    for s in res.get('segments') or []:
        n, h = hits(s.get('text') or '')
        if n >= 4 and h >= 0.5 * n:
            return True
        items = [p.strip() for p in re.split(r'[,.;]', s.get('text') or '') if p.strip()]
        if (len(items) >= 6 and all(len(p.split()) <= 2 and p[0].isupper() for p in items)
                and h >= 0.3 * n):            # "Кијов, Львів, Карків, Суми, ...": a list of names, not speech
            return True
        total, hit = total + n, hit + h
    return total >= 3 and hit >= 0.5 * total


def transcribe(path: str, workdir: str, *, quality: str = 'accurate', language: str | None = None,
               prompt: str | None = None, max_minutes: int | None = None, media_seconds: float | None = None) -> dict:
    """Returns {'text', 'segments', 'language', 'duration', 'minutes', 'truncated'}. media_seconds: the video's own
    length from the site; audio past it (a longer music track) is not transcribed."""
    duration = probe_duration(path)
    if media_seconds and media_seconds > 0:
        duration = min(duration, media_seconds + 1)
    truncated = False
    if max_minutes is not None and duration > max_minutes * 60:
        duration, truncated = max_minutes * 60.0, True
    model = MODELS.get(quality, MODELS['accurate'])
    segments, texts, detected = [], [], None
    prompt = _prompt(prompt, language)
    words = _prompt_words(prompt)
    with httpx.Client(timeout=httpx.Timeout(300, connect=30)) as client:
        for chunk, offset in make_chunks(path, workdir, duration):
            tail = texts[-1][-200:] if texts else ''
            res = transcribe_chunk(client, chunk, model=model, language=language,
                                   prompt=(prompt + ' ' + tail).strip())
            if _echoed(res, words):          # the prompt came back instead of the speech: again without it
                res = transcribe_chunk(client, chunk, model=model, language=language, prompt=tail or None)
            detected = detected or res.get('language')
            texts.append((res.get('text') or '').strip())
            for s in res.get('segments') or []:
                text = (s.get('text') or '').strip()
                if _silence(s) or _made_up(s, text):
                    continue
                if segments and segments[-1]['text'] == text and offset + float(s['start']) - segments[-1]['end'] < 2:
                    continue                          # Whisper's repetition loop: the same line again and again
                if text and offset + float(s['start']) < duration:
                    segments.append({'start': round(offset + float(s['start']), 2),
                                     'end': round(min(offset + float(s['end']), duration), 2), 'text': text})
    # the full text is rebuilt from the kept segments, so dropped made-up lines do not come back through it
    texts = [' '.join(s['text'] for s in segments)] if segments else []
    return {'text': '\n'.join(t for t in texts if t), 'segments': segments, 'language': detected,
            'duration': round(duration, 2), 'minutes': max(1, math.ceil(duration / 60)), 'truncated': truncated,
            'model': model}


def _ts(seconds: float, sep: str) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}'


def to_srt(segments: list[dict]) -> str:
    return '\n'.join(f"{i}\n{_ts(s['start'], ',')} --> {_ts(s['end'], ',')}\n{s['text']}\n"
                     for i, s in enumerate(segments, 1))


def to_vtt(segments: list[dict]) -> str:
    return 'WEBVTT\n\n' + '\n'.join(f"{_ts(s['start'], '.')} --> {_ts(s['end'], '.')}\n{s['text']}\n" for s in segments)
