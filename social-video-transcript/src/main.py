"""Apify Actor: transcripts, subtitles and translations of YouTube, TikTok, Instagram, Facebook and X videos."""
from __future__ import annotations

import asyncio
import math
import os
import re
import tempfile
import time
import uuid

from apify import Actor

from .fetch import FetchError, audio, captions, info, platform
from .transcribe import TranscriptionError, to_srt, to_vtt, transcribe
from .translate import LANGUAGES, TranslationError, translate

EVENT_VIDEO = 'video'                          # one transcript: captions of any length, or up to 3 minutes of speech
EVENT_MINUTE = 'audio-minute'                  # each started minute of speech after the first 3 (not YouTube)
EVENT_YT_MINUTE = 'youtube-audio-minute'       # YouTube without captions: each started minute (replaces "video")
EVENT_TRANSLATED = 'translated-minute'         # each started minute of translated transcript
INCLUDED_MINUTES = 3
CHEAP_FALLBACK_MINUTES = 10  # non-YouTube videos are retried through residential proxies only when this short


def _urls(inp: dict) -> list[str]:
    out = []
    for item in inp.get('videoUrls') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip().startswith(('http://', 'https://')):
            out.append(url.strip())
    return list(dict.fromkeys(out))


def _stem(data: dict, idx: int) -> str:
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', str(data.get('id') or 'video')).strip('-.')[:40]
    return f'{idx:04d}-{stem or "video"}'


# Whisper names the language ("English"); captions give a code ("en"): the output always has the code
_CODES = {**{v.split(' ')[0].lower(): k for k, v in LANGUAGES.items()}, 'ukrainian': 'uk', 'belarusian': 'be',
          'kazakh': 'kk', 'georgian': 'ka', 'hebrew': 'he', 'greek': 'el', 'hungarian': 'hu', 'finnish': 'fi',
          'danish': 'da', 'norwegian': 'no', 'bulgarian': 'bg', 'serbian': 'sr', 'croatian': 'hr', 'slovak': 'sk',
          'lithuanian': 'lt', 'latvian': 'lv', 'estonian': 'et', 'persian': 'fa', 'thai': 'th', 'malay': 'ms',
          'bengali': 'bn', 'urdu': 'ur', 'tamil': 'ta', 'filipino': 'tl', 'tagalog': 'tl', 'swahili': 'sw'}


def _code(lang: str | None) -> str | None:
    if not lang:
        return None
    lang = lang.strip()
    return _CODES.get(lang.lower(), lang if len(lang) <= 3 or '-' in lang else lang.lower())


def _text(segments: list[dict]) -> str:
    return re.sub(r'\s+', ' ', ' '.join(s['text'] for s in segments)).strip()


def _left(charging, event: str) -> int:
    """How many more events fit under the user's maximum charge (no limit without pay-per-event pricing)."""
    n = charging.calculate_max_event_charge_count_within_limit(event)
    return 10 ** 6 if n is None else n


class Proxies:
    """Residential proxy URLs, a new address per session (YouTube rate-limits a single address)."""

    def __init__(self):
        self.cfg = None

    async def url(self) -> str | None:
        if self.cfg is None:
            self.cfg = await Actor.create_proxy_configuration(groups=['RESIDENTIAL']) or False
        if not self.cfg:
            return None
        return await self.cfg.new_url(session_id=uuid.uuid4().hex[:16])


async def _metadata(url: str, plat: str, proxies: Proxies) -> tuple[dict, str | None]:
    """info() of the video and the proxy that got it. YouTube: residential, 3 addresses; others: direct first."""
    if plat == 'youtube':
        tries = [await proxies.url() for _ in range(3)]
    else:
        tries = [None]
    err = None
    for proxy in tries:
        try:
            return await asyncio.to_thread(info, url, proxy), proxy
        except FetchError as e:
            err = e
    if plat != 'youtube' and 'unsupported URL' not in str(err) and 'playlist' not in str(err):
        proxy = await proxies.url()
        if proxy:  # Instagram and some Facebook pages answer server addresses with a login wall
            data = await asyncio.to_thread(info, url, proxy)
            if (data.get('duration') or 0) > CHEAP_FALLBACK_MINUTES * 60:
                raise FetchError(f'the site blocks server downloads for this video; only videos up to '
                                 f'{CHEAP_FALLBACK_MINUTES} minutes are fetched through a proxy')
            return data, proxy
    raise err


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = _urls(inp)
        if not urls:
            await Actor.fail(status_message='Input "videoUrls" is empty: add at least one video link.')
            return
        target = (inp.get('translateTo') or '').strip().lower() or None
        if target and target not in LANGUAGES:
            await Actor.fail(status_message=f'Unknown "translateTo" language "{target}". '
                                            f'Use one of: {", ".join(LANGUAGES)}.')
            return
        language = (inp.get('language') or '').strip().lower() or None
        use_captions = inp.get('useCaptions', True)
        max_minutes = int(inp.get('maxDurationMinutes') or 60)
        want_subs = inp.get('subtitles', True)
        include_segments = inp.get('includeSegments', True)

        charging = Actor.get_charging_manager()
        store = await Actor.open_key_value_store()
        proxies = Proxies()
        ok = failed = 0
        for idx, url in enumerate(urls, 1):
            if _left(charging, EVENT_VIDEO) == 0:
                Actor.log.warning('Maximum charge per run reached, remaining videos were skipped.')
                break
            plat = platform(url)
            item = {'url': url, 'platform': plat}
            started = time.monotonic()
            charges = {}
            try:
                data, proxy = await _metadata(url, plat, proxies)
                duration = float(data.get('duration') or 0)
                item.update(videoId=data.get('id'), title=data.get('title'),
                            author=data.get('uploader') or data.get('channel') or data.get('creator'),
                            uploadDate=data.get('upload_date'), durationSeconds=duration or None,
                            viewCount=data.get('view_count'))
                cap = None
                if use_captions:
                    try:
                        cap = await asyncio.to_thread(captions, url, data, proxy, language)
                    except FetchError as e:
                        if plat == 'youtube':  # rate-limited captions: one more address
                            proxy = await proxies.url()
                            data = await asyncio.to_thread(info, url, proxy)
                            cap = await asyncio.to_thread(captions, url, data, proxy, language)
                        else:
                            Actor.log.info(f'{url}: captions unavailable ({e}), transcribing the speech')
                if cap:
                    segments, lang, source = cap['segments'], cap['language'], f"{cap['kind']}-captions"
                    charges[EVENT_VIDEO] = 1
                else:
                    if duration > max_minutes * 60:
                        raise FetchError(f'the video is {duration / 60:.0f} min long, over the {max_minutes} min '
                                         'limit set in "maxDurationMinutes"')
                    if plat == 'youtube':
                        left = _left(charging, EVENT_YT_MINUTE)
                    else:
                        left = INCLUDED_MINUTES + _left(charging, EVENT_MINUTE)
                    if left <= 0:
                        raise FetchError('maximum charge per run reached')
                    with tempfile.TemporaryDirectory() as tmp:
                        path = await asyncio.to_thread(audio, data, tmp, proxy)
                        res = await asyncio.to_thread(transcribe, path, tmp, quality=inp.get('quality', 'accurate'),
                                                      language=language, max_minutes=left)
                    segments, lang, source = res['segments'], _code(res['language']), 'speech-recognition'
                    if res['truncated']:
                        item['warnings'] = [f"only the first {res['minutes']} minutes were transcribed: "
                                            'maximum charge per run reached']
                    duration = duration or res['duration']
                    if plat == 'youtube':
                        charges[EVENT_YT_MINUTE] = res['minutes']
                    else:
                        charges[EVENT_VIDEO] = 1
                        if res['minutes'] > INCLUDED_MINUTES:
                            charges[EVENT_MINUTE] = res['minutes'] - INCLUDED_MINUTES
                if not segments:
                    raise TranscriptionError('no speech found in the video')
            except (FetchError, TranscriptionError) as e:
                failed += 1
                item['error'] = str(e) or type(e).__name__
                Actor.log.warning(f'{url}: {item["error"]}')
                await Actor.push_data(item)
                continue

            item.update(language=lang, transcriptSource=source, text=_text(segments))
            if include_segments:
                item['segments'] = segments
            stem = _stem(data, idx)
            files = [('', segments)]
            if target:
                minutes = max(1, math.ceil((duration or segments[-1]['end']) / 60))
                if _left(charging, EVENT_TRANSLATED) < minutes:
                    item['warnings'] = item.get('warnings', []) + ['translation skipped: maximum charge per run']
                elif lang and lang.split('-')[0] == target:
                    item['warnings'] = item.get('warnings', []) + ['the video is already in the target language']
                else:
                    try:
                        tr = await asyncio.to_thread(translate, segments, target)
                        item['translation'] = {'language': target, 'text': _text(tr)}
                        if include_segments:
                            item['translation']['segments'] = tr
                        files.append((f'.{target}', tr))
                        charges[EVENT_TRANSLATED] = minutes
                    except TranslationError as e:
                        item['warnings'] = item.get('warnings', []) + [f'translation failed: {e}']
            if want_subs:
                for suffix, segs in files:
                    holder = item if not suffix else item['translation']
                    for ext, body, ctype in (('srt', to_srt(segs), 'application/x-subrip'),
                                             ('vtt', to_vtt(segs), 'text/vtt')):
                        key = f'{stem}{suffix}.{ext}'
                        await store.set_value(key, body, content_type=f'{ctype}; charset=utf-8')
                        holder[f'{ext}Url'] = await store.get_public_url(key)
            item['seconds'] = round(time.monotonic() - started, 1)
            await Actor.push_data(item)
            # Charged after the result is saved; failed videos are free
            for event, count in charges.items():
                await Actor.charge(event, count=count)
            ok += 1
            Actor.log.info(f'{url}: {source}, {lang}, {len(segments)} segments, {charges}')
        await Actor.set_status_message(f'Transcribed {ok} video(s), failed {failed}.')
