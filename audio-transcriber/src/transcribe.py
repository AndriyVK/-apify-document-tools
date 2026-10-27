"""Audio/video -> text with Groq's Whisper API: ffmpeg prepares speech-quality chunks, Groq transcribes them."""
from __future__ import annotations

import json
import math
import os
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
        data['prompt'] = prompt[:800]
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


def transcribe(path: str, workdir: str, *, quality: str = 'accurate', language: str | None = None,
               prompt: str | None = None, max_minutes: int | None = None) -> dict:
    """Returns {'text', 'segments', 'language', 'duration', 'minutes', 'truncated'}."""
    duration = probe_duration(path)
    truncated = False
    if max_minutes is not None and duration > max_minutes * 60:
        duration, truncated = max_minutes * 60.0, True
    model = MODELS.get(quality, MODELS['accurate'])
    segments, texts, detected = [], [], None
    with httpx.Client(timeout=httpx.Timeout(300, connect=30)) as client:
        for chunk, offset in make_chunks(path, workdir, duration):
            res = transcribe_chunk(client, chunk, model=model, language=language,
                                   prompt=prompt if not texts else (prompt or '') + ' ' + texts[-1][-400:])
            detected = detected or res.get('language')
            texts.append((res.get('text') or '').strip())
            for s in res.get('segments') or []:
                text = (s.get('text') or '').strip()
                if text and offset + float(s['start']) < duration:
                    segments.append({'start': round(offset + float(s['start']), 2),
                                     'end': round(min(offset + float(s['end']), duration), 2), 'text': text})
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
