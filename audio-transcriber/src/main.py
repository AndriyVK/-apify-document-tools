"""Apify Actor: transcribe audio and video files to text, timestamped segments, SRT and VTT subtitles."""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time

import httpx
from apify import Actor

from .crosscheck import compare
from .download import DownloadError, download
from .transcribe import TranscriptionError, to_srt, to_vtt, transcribe

EVENT_MINUTE = 'audio-minute'


def _sources(inp: dict) -> list[str]:
    urls = []
    for item in inp.get('sources') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _stem(name: str, idx: int) -> str:
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', os.path.splitext(name or '')[0]).strip('-.')[:60]
    return f'{idx:04d}-{stem or "audio"}'


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = _sources(inp)
        if not urls:
            await Actor.fail(status_message='Input "sources" is empty: add at least one audio or video URL.')
            return
        if not os.environ.get('GROQ_API_KEY') and os.environ.get('APIFY_IS_AT_HOME'):
            await Actor.fail(status_message='The Actor is not configured (speech service key missing). '
                                            'Please report this issue to the Actor author.')
            return
        quality = inp.get('quality', 'accurate')
        language = (inp.get('language') or '').strip().lower() or None
        prompt = (inp.get('vocabulary') or '').strip() or None
        want_subs = inp.get('subtitles', True)
        cross_check = bool(inp.get('crossCheck'))

        charging = Actor.get_charging_manager()
        store = await Actor.open_key_value_store()
        ok = failed = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20),
                                     headers={'User-Agent': 'audio-transcriber (Apify Actor)'}) as client:
            for idx, url in enumerate(urls, 1):
                item = {'url': url}
                left = charging.calculate_max_event_charge_count_within_limit(EVENT_MINUTE)
                if left == 0:
                    Actor.log.warning('Maximum charge per run reached, remaining files were skipped.')
                    break
                started = time.monotonic()
                with tempfile.TemporaryDirectory() as tmp:
                    src = os.path.join(tmp, 'input.bin')
                    try:
                        name, _ = await download(client, url, src)
                        res = await asyncio.to_thread(transcribe, src, tmp, quality=quality, language=language,
                                                      prompt=prompt, max_minutes=left)
                    except (DownloadError, TranscriptionError, httpx.HTTPError) as e:
                        failed += 1
                        item['error'] = str(e) or type(e).__name__
                        Actor.log.warning(f'{url}: {item["error"]}')
                        await Actor.push_data(item)
                        continue
                    checked, warnings, minutes = None, [], res['minutes']
                    if cross_check and res['segments']:
                        # the second model on the same audio, charged like the first recognition
                        if left is None or left >= 2 * minutes:
                            try:
                                res2 = await asyncio.to_thread(
                                    transcribe, src, tmp, quality='fast' if quality == 'accurate' else 'accurate',
                                    language=language, prompt=prompt, max_minutes=minutes)
                                checked = {'model': res2['model'], **compare(res['segments'], res2['segments']),
                                           'text': res2['text']}
                                minutes *= 2
                            except Exception as e:  # noqa: BLE001 - the first transcript is still good
                                warnings.append(f'cross-check failed: {e}')
                        else:
                            warnings.append('cross-check skipped: maximum charge per run')
                item.update(fileName=name or None, language=res['language'], durationSeconds=res['duration'],
                            billedMinutes=minutes, model=res['model'], text=res['text'],
                            segments=res['segments'], seconds=round(time.monotonic() - started, 1))
                if checked:
                    item['crossCheck'] = checked
                if res['truncated']:
                    warnings.insert(0, f"only the first {res['minutes']} minutes were transcribed: "
                                       'maximum charge per run reached')
                if warnings:
                    item['warnings'] = warnings
                if want_subs and res['segments']:
                    stem = _stem(name, idx)
                    for ext, body, ctype in (('srt', to_srt(res['segments']), 'application/x-subrip'),
                                             ('vtt', to_vtt(res['segments']), 'text/vtt')):
                        key = f'{stem}.{ext}'
                        await store.set_value(key, body, content_type=f'{ctype}; charset=utf-8')
                        item[f'{ext}Url'] = await store.get_public_url(key)
                await Actor.push_data(item)
                # Charge per started minute of transcribed audio, after the result is saved
                await Actor.charge(EVENT_MINUTE, count=minutes)
                ok += 1
                Actor.log.info(f"{url}: {res['duration']:.0f}s, {res['language']}, {len(res['segments'])} segments")
        await Actor.set_status_message(f'Transcribed {ok} file(s), failed {failed}.')
