"""Transcript segments -> another language with a Groq-hosted LLM (qwen3.8-27b without reasoning: chosen for the
Perekladach voice-over on 28.10.2026 as the fastest model with good Ukrainian and Russian)."""
from __future__ import annotations

import json
import os
import re
import time

import httpx

CHAT_URL = 'https://api.groq.com/openai/v1/chat/completions'
MODEL = os.environ.get('TRANSLATE_MODEL', 'qwen/qwen3.8-27b')
# Same quality checked 16.11.2026 on the same transcript (13/13 lines into Ukrainian); used when MODEL is rate-limited
MODELS = [MODEL] + [m for m in ('openai/gpt-oss-120b', 'openai/gpt-oss-20b') if m != MODEL]
_blocked: dict[str, float] = {}   # model -> monotonic time it may be used again
BATCH = 40           # segments per request: keeps answers short enough to stay reliable
MAX_RETRIES = 5

LANGUAGES = {'en': 'English', 'uk': 'Ukrainian', 'ru': 'Russian', 'de': 'German', 'fr': 'French', 'es': 'Spanish',
             'pt': 'Portuguese', 'it': 'Italian', 'pl': 'Polish', 'nl': 'Dutch', 'tr': 'Turkish', 'cs': 'Czech',
             'ro': 'Romanian', 'sv': 'Swedish', 'ar': 'Arabic', 'hi': 'Hindi', 'id': 'Indonesian', 'vi': 'Vietnamese',
             'zh': 'Chinese (Simplified)', 'ja': 'Japanese', 'ko': 'Korean'}


class TranslationError(Exception):
    pass


def _headers() -> dict:
    h = {'Content-Type': 'application/json'}
    if os.environ.get('GROQ_API_KEY'):  # on Apify; locally a proxy may add the header instead
        h['Authorization'] = 'Bearer ' + os.environ['GROQ_API_KEY']
    return h


def _chat(client: httpx.Client, prompt: str) -> str:
    """One answer from the first model that is not at its rate limit. Each Groq model has its own limit (8,000 tokens a
    minute, 1,000 requests a day on the current plan), so a limited model hands over to the next one at once; the run
    waits only when every model is limited."""
    last, empty = 'no answer', set()   # models that answered this prompt with nothing (gpt-oss sometimes does)
    for attempt in range(MAX_RETRIES * 2):
        now = time.monotonic()
        ready = [m for m in MODELS if _blocked.get(m, 0) <= now and m not in empty]
        if not ready and len(empty) == len(MODELS):
            raise TranslationError('the translation service returned empty answers')
        if not ready:
            wait = min(_blocked[m] for m in MODELS if m not in empty) - now
            if wait > 300:
                raise TranslationError('the translation service is at its usage limit right now; try again later')
            time.sleep(max(wait, 1))
            continue
        model = ready[0]
        body = {'model': model, 'temperature': 0.2, 'messages': [{'role': 'user', 'content': prompt}]}
        if 'qwen' in model:
            body['reasoning_effort'] = 'none'  # qwen thinks aloud by default: slow and costly
        elif 'gpt-oss' in model:
            body['reasoning_effort'] = 'low'
        try:
            r = client.post(CHAT_URL, json=body, headers=_headers())
        except httpx.HTTPError as e:
            last = str(e)
            time.sleep(min(30, 3 * 2 ** min(attempt, 3)))
            continue
        if r.status_code == 200:
            content = (r.json()['choices'][0]['message'].get('content') or '').strip()
            if content:
                return content
            empty.add(model)
            last = f'empty answer from {model}'
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            try:
                wait = float(r.headers.get('retry-after') or 0)
            except ValueError:
                wait = 0
            if 'per day' in r.text:
                wait = max(wait, 3600)
            _blocked[model] = time.monotonic() + (wait or min(30, 3 * 2 ** min(attempt, 3)))
            last = f'HTTP {r.status_code}'
            continue
        if r.status_code in (401, 403):
            raise TranslationError('translation service authorisation failed (Actor configuration problem)')
        raise TranslationError(f'translation service error HTTP {r.status_code}')
    raise TranslationError(f'the translation service did not respond ({last}), try again later')


def _json_object(text: str) -> dict | None:
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


# Letters that never occur in the target language: a line with them slipped into a neighbour language ("Сэр" in
# Ukrainian) and is asked again
_FOREIGN = {'Ukrainian': re.compile('[\u044b\u044d\u044a\u0451\u042b\u042d\u042a\u0401]'),
            'Russian': re.compile('[\u0456\u0457\u0454\u0491\u0406\u0407\u0404\u0490]')}


def _numbered(client: httpx.Client, lines: list[str], lang: str, context: str,
              strict: bool = True) -> dict[int, str]:
    """Lines sent as {"1": "...", "2": "..."}; returns the translations the model gave back, by number."""
    prompt = (f'Translate each numbered line of this video transcript into natural {lang}. The lines are '
              'consecutive fragments of speech: keep the meaning and names; translate every line separately, even '
              'if a sentence continues on the next line - never merge or skip lines. '
              + (f'Previous lines for context (do not translate): {context}\n' if context else '')
              + 'Return only a JSON object with exactly the same keys, each value the translation of that line.\n\n'
              + json.dumps({str(i + 1): t for i, t in enumerate(lines)}, ensure_ascii=False))
    obj = _json_object(_chat(client, prompt)) or {}
    out = {}
    for k, v in obj.items():
        if str(k).strip().isdigit() and isinstance(v, str) and v.strip():
            out[int(str(k).strip()) - 1] = v.strip()
    bad = _FOREIGN.get(lang) if strict else None
    return {i: t for i, t in out.items() if 0 <= i < len(lines) and not (bad and bad.search(t) and not bad.search(lines[i]))}


def _batch(client: httpx.Client, lines: list[str], lang: str, context: str, depth: int = 0) -> list[str]:
    """Every line translated: missing lines are asked again; a stubborn batch is split in halves down to one line."""
    got: dict[int, str] = {}
    for _ in range(2):
        missing = [i for i in range(len(lines)) if i not in got]
        if not missing:
            break
        part = _numbered(client, [lines[i] for i in missing], lang, context)
        for j, t in part.items():
            got[missing[j]] = t
    missing = [i for i in range(len(lines)) if i not in got]
    if missing and len(lines) > 1 and depth < 6:
        half = len(lines) // 2
        first = _batch(client, lines[:half], lang, context, depth + 1)
        second = _batch(client, lines[half:], lang, ' '.join(lines[max(0, half - 3):half]), depth + 1)
        return first + second
    if missing and len(lines) == 1 and _FOREIGN.get(lang):
        # the model keeps writing a neighbour language's letters into one line: keep its last answer
        last = _numbered(client, lines, lang, context, strict=False)
        if 0 in last:
            return [last[0]]
    if missing:
        raise TranslationError('translation failed: the model returned a malformed answer')
    return [got[i] for i in range(len(lines))]


def translate(segments: list[dict], target: str) -> list[dict]:
    """Same segments (start, end) with the text in the target language."""
    lang = LANGUAGES[target]
    out = []
    with httpx.Client(timeout=httpx.Timeout(120, connect=20)) as client:
        for i in range(0, len(segments), BATCH):
            part = segments[i:i + BATCH]
            context = ' '.join(s['text'] for s in segments[max(0, i - 3):i])
            texts = _batch(client, [s['text'] for s in part], lang, context)
            out += [{**s, 'text': t or s['text']} for s, t in zip(part, texts)]
    return out
