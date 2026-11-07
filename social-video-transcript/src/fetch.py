"""Video pages -> caption tracks or the audio file, with yt-dlp.

YouTube answers server addresses with "Sign in to confirm you're not a bot", so it goes through residential proxies
(measured 28.10.2026: captions ~0.16 MB of proxy traffic per video). TikTok and Facebook work without a proxy.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse

import yt_dlp

MAX_FILE_BYTES = 300 * 1024 * 1024


class FetchError(Exception):
    pass


def platform(url: str) -> str:
    host = (urllib.parse.urlparse(url).hostname or '').lower().removeprefix('www.').removeprefix('m.')
    for name, hosts in (('youtube', ('youtube.com', 'youtu.be', 'youtube-nocookie.com')),
                        ('tiktok', ('tiktok.com',)), ('instagram', ('instagram.com',)),
                        ('facebook', ('facebook.com', 'fb.watch', 'fb.com')), ('x', ('x.com', 'twitter.com')),
                        ('vimeo', ('vimeo.com',))):
        if any(host == h or host.endswith('.' + h) for h in hosts):
            return name
    return 'other'


def _opts(proxy: str | None, workdir: str | None = None) -> dict:
    o = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'socket_timeout': 30, 'retries': 2,
         'max_filesize': MAX_FILE_BYTES, 'noprogress': True, 'logger': _Quiet()}
    if workdir:
        o['outtmpl'] = os.path.join(workdir, 'media.%(ext)s')
    if proxy:
        o['proxy'] = proxy
    return o


class _Quiet:
    def debug(self, msg):
        pass

    info = warning = debug

    def error(self, msg):
        pass


def _clean(err: Exception) -> str:
    msg = re.sub(r'\x1b\[[0-9;]*m', '', str(err)).removeprefix('ERROR: ').strip()
    if 'Sign in to confirm' in msg:
        return 'the site asked to sign in (bot check); try again later'
    if 'Private video' in msg or 'login required' in msg.lower() or 'rate-limit reached or login' in msg:
        return 'the video is private or needs a login'
    if 'Unsupported URL' in msg:
        return 'unsupported URL: give a link to a single video, not a profile or a search page'
    msg = msg.split('; please report this issue')[0]
    return msg[:300] or type(err).__name__


def info(url: str, proxy: str | None) -> dict:
    """Video metadata including caption tracks; nothing is downloaded."""
    try:
        # flat + playlistend: a channel or playlist link is recognised from its first page, not walked video by video
        with yt_dlp.YoutubeDL({**_opts(proxy), 'extract_flat': 'in_playlist', 'playlistend': 1}) as y:
            data = y.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001 - yt-dlp raises many kinds; all mean "this video failed"
        raise FetchError(_clean(e)) from e
    if not data:
        raise FetchError('no video found at this URL')
    if data.get('_type') == 'playlist' or data.get('entries'):
        raise FetchError('this is a playlist or a profile: give a link to a single video')
    return data


def _pick_track(data: dict, language: str | None) -> tuple[str, str, list] | None:
    """(language, kind, formats) of the best caption track: uploaded captions first, then YouTube's automatic
    captions in the spoken language. Auto-translated tracks are skipped (YouTube rate-limits them; we translate)."""
    manual = {k: v for k, v in (data.get('subtitles') or {}).items() if k != 'live_chat'}
    auto = data.get('automatic_captions') or {}
    spoken = (language or data.get('language') or '').split('-')[0].lower() or None

    def base(k):
        return k.split('-')[0].lower()

    if manual:
        for k in manual:
            if spoken and base(k) == spoken:
                return k, 'uploaded', manual[k]
        if not spoken:
            k = next(iter(manual))
            return k, 'uploaded', manual[k]
    orig = [k for k in auto if k.endswith('-orig')]
    for k in orig:
        if not spoken or base(k) == spoken:
            return k.removesuffix('-orig'), 'automatic', auto[k]
    if spoken and spoken in auto and not orig:
        return spoken, 'automatic', auto[spoken]
    if manual:  # captions exist only in another language than the spoken one
        k = next(iter(manual))
        return k, 'uploaded', manual[k]
    return None


def _json3_segments(body: str) -> list[dict]:
    events = json.loads(body).get('events') or []
    segs = []
    for e in events:
        text = ''.join(s.get('utf8', '') for s in e.get('segs') or []).replace('\n', ' ').strip()
        if not text or 'tStartMs' not in e:
            continue
        start = e['tStartMs'] / 1000
        segs.append({'start': round(start, 2), 'end': round(start + e.get('dDurationMs', 0) / 1000, 2),
                     'text': re.sub(r'\s+', ' ', text)})
    for a, b in zip(segs, segs[1:]):  # automatic captions overlap the next line: cut at its start
        a['end'] = min(a['end'], b['start']) if b['start'] > a['start'] else a['end']
    return segs


def captions(url: str, data: dict, proxy: str | None, language: str | None) -> dict | None:
    """{'language', 'kind', 'segments'} from the video's caption track, or None if it has none."""
    track = _pick_track(data, language)
    if not track:
        return None
    lang, kind, formats = track
    fmt = next((f for f in formats if f.get('ext') == 'json3'), None)
    if not fmt:
        return None
    try:
        with yt_dlp.YoutubeDL(_opts(proxy)) as y:
            body = y.urlopen(fmt['url']).read().decode('utf-8', 'replace')
        segments = _json3_segments(body)
    except Exception as e:  # noqa: BLE001
        raise FetchError(_clean(e)) from e
    return {'language': lang, 'kind': kind, 'segments': segments} if segments else None


def _has_audio(path: str) -> bool:
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0',
                          path], capture_output=True, text=True, timeout=120)
    return bool(out.stdout.strip())


def audio(data: dict, workdir: str, proxy: str | None) -> str:
    """Downloads the smallest file with the speech track of an info() result (same proxy: YouTube links are bound
    to the address that asked for them); returns its path."""
    o = _opts(proxy, workdir)
    # TikTok's audio-only format ('audio') is the clip's background music track, often minutes longer than the video
    # and without the speech: Whisper then "transcribes" music. The video file with its own sound is used instead.
    selector = ('ba[filesize<100M][format_id!=audio]/ba[format_id!=audio]/wa[format_id!=audio]/'
                'w[acodec!=none][vcodec!=none]/w[acodec!=none]/worst')
    skip = []
    for attempt in range(4):
        o['format'] = '/'.join(p + ''.join(f'[format_id!={s}]' for s in skip) for p in selector.split('/'))
        for f in os.listdir(workdir):
            if f.startswith('media.'):
                os.remove(os.path.join(workdir, f))
        try:
            # info() already chose formats for its own default selector: for a video whose best picture has no sound
            # (TikTok's bytevc1) that is a picture + sound pair in 'requested_formats', which yt-dlp would carry into
            # our format and download instead ("No such file ... media.f<id>.mp4"). The choice is dropped here.
            clean = {k: v for k, v in data.items() if k not in ('requested_formats', 'requested_downloads')}
            with yt_dlp.YoutubeDL(o) as y:
                got = y.process_ie_result(clean, download=True) or {}
        except Exception as e:  # noqa: BLE001
            # a format whose file yt-dlp cannot find after the download ("No such file ... media.f<id>.mp4"):
            # the next format is tried instead.
            bad = re.search(r"media\.f(.+?)\.\w+'", str(e)) if 'No such file' in str(e) else None
            if bad and bad.group(1) not in skip and attempt < 3:
                skip.append(bad.group(1))
                continue
            raise FetchError(_clean(e)) from e
        files = [os.path.join(workdir, f) for f in os.listdir(workdir) if f.startswith('media.')]
        files = [f for f in files if os.path.getsize(f) > 0 and not f.endswith('.part')]
        if not files:
            raise FetchError('the video has no downloadable audio')
        if _has_audio(files[0]):
            return files[0]
        # TikTok labels some video-only files (bytevc1) as having sound: the next format then
        fid = got.get('format_id')
        if not fid or fid in skip or attempt == 3:
            break
        skip.append(fid)
    raise FetchError('the video has no downloadable audio')
