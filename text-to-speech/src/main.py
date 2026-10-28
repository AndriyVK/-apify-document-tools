"""Apify Actor: text, Markdown, HTML, PDF or DOCX to natural speech (Piper) with SRT/VTT subtitles."""
from __future__ import annotations

import asyncio
import math
import os
import re
import tempfile
import urllib.parse

import httpx
from apify import Actor

from .download import DownloadError, download
from .tts import VOICES, TtsError, encode, extract_text, load_voice, split_text, synthesize, to_srt, to_vtt

EVENT_MINUTE = 'audio-minute'
EVENT_HQ_MINUTE = 'hq-audio-minute'  # high-quality voices need ~7x more CPU per minute
CHARS_PER_MINUTE = 750  # conservative estimate used to stay within the user's maximum charge
VOICE_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'voices')
MIME = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg'}


def _sources(inp: dict) -> list[dict]:
    out = []
    text = inp.get('text')
    if isinstance(text, str) and text.strip():
        out.append({'text': text})
    for item in inp.get('sources') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            out.append({'url': url.strip()})
    return out


def _stem(src: dict, idx: int) -> str:
    if 'text' in src:
        return f'{idx:04d}-text'
    path = urllib.parse.urlparse(src['url']).path
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', os.path.splitext(os.path.basename(path))[0]).strip('-.')[:50]
    return f'{idx:04d}-{stem or "document"}'


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        sources = _sources(inp)
        if not sources:
            await Actor.fail(status_message='Add text in "text" or document URLs in "sources".')
            return
        voice_id = str(inp.get('voice') or 'en_US-john-medium')
        fmt = str(inp.get('format') or 'mp3')
        if voice_id not in VOICES or fmt not in MIME:
            await Actor.fail(status_message=f'Unknown voice "{voice_id}" or format "{fmt}".')
            return
        speed = min(max(float(inp.get('speed') or 1.0), 0.5), 2.0)
        speaker = inp.get('speakerId')
        subtitles = bool(inp.get('subtitles', True))
        max_chars = min(max(int(inp.get('maxCharactersPerItem') or 200000), 100), 1000000)

        try:
            voice = await asyncio.to_thread(load_voice, voice_id, VOICE_CACHE)
        except TtsError as e:
            await Actor.fail(status_message=str(e))
            return
        if speaker is not None and voice.config.num_speakers <= 1:
            speaker = None
        event = EVENT_HQ_MINUTE if voice_id.endswith('-high') else EVENT_MINUTE

        charging = Actor.get_charging_manager()
        store = await Actor.open_key_value_store()
        ok = failed = 0
        with tempfile.TemporaryDirectory() as tmp:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20),
                                         headers={'User-Agent': 'text-to-speech (Apify Actor)'}) as client:
                for idx, src in enumerate(sources, 1):
                    left = charging.calculate_max_event_charge_count_within_limit(event)
                    if left == 0:
                        Actor.log.warning('Maximum charge per run reached, remaining items were skipped.')
                        break
                    limit = max_chars if left is None else min(max_chars, left * CHARS_PER_MINUTE)
                    label = src.get('url', 'text')
                    try:
                        if 'text' in src:
                            text = src['text']
                        else:
                            path = os.path.join(tmp, f'in-{idx:04d}')
                            name, ctype = await download(client, src['url'], path)
                            text = await asyncio.to_thread(extract_text, path, name, ctype)
                        paras, chars, truncated = split_text(text, limit)
                        if not paras:
                            raise TtsError('no text to read')
                        pcm, rate, cues = await asyncio.to_thread(synthesize, voice, paras, speed, speaker,
                                                                    VOICES[voice_id][0] == 'Ukrainian')
                        if not pcm:
                            raise TtsError('the voice produced no audio for this text')
                        stem = _stem(src, idx)
                        dest = os.path.join(tmp, f'{stem}.{fmt}')
                        await asyncio.to_thread(encode, pcm, rate, fmt, dest)
                    except (DownloadError, TtsError, httpx.HTTPError) as e:
                        failed += 1
                        await Actor.push_data({'url': label, 'error': str(e) or type(e).__name__})
                        continue
                    duration = len(pcm) / 2 / rate
                    item = {'url': label, 'voice': voice_id, 'language': VOICES[voice_id][0], 'format': fmt,
                            'characters': chars, 'truncated': truncated, 'durationSeconds': round(duration, 2),
                            'sentences': len(cues)}
                    with open(dest, 'rb') as f:
                        await store.set_value(f'{stem}.{fmt}', f.read(), content_type=MIME[fmt])
                    item['audioUrl'] = await store.get_public_url(f'{stem}.{fmt}')
                    if subtitles:
                        await store.set_value(f'{stem}.srt', to_srt(cues), content_type='application/x-subrip')
                        await store.set_value(f'{stem}.vtt', to_vtt(cues), content_type='text/vtt')
                        item['srtUrl'] = await store.get_public_url(f'{stem}.srt')
                        item['vttUrl'] = await store.get_public_url(f'{stem}.vtt')
                    await Actor.push_data(item)
                    # One event per started minute of generated audio, after the files are saved
                    minutes = max(1, math.ceil(duration / 60))
                    await Actor.charge(event, count=minutes if left is None else min(minutes, left))
                    ok += 1
        await Actor.set_status_message(f'Generated {ok} audio file(s), failed {failed}.')
