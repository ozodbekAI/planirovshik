# utils/telegram_html.py
from __future__ import annotations

import re
from typing import Optional

from aiogram.exceptions import TelegramBadRequest


# Telegram Bot API HTML supported tags (minimum set + spoiler)
_ALLOWED_CANONICAL = {"b", "i", "u", "s", "code", "pre", "tg-spoiler", "a"}

# Map synonyms to canonical tags
_OPEN_MAP = {
    "b": "b",
    "strong": "b",
    "i": "i",
    "em": "i",
    "u": "u",
    "ins": "u",
    "s": "s",
    "strike": "s",
    "del": "s",
    "code": "code",
    "pre": "pre",
    "tg-spoiler": "tg-spoiler",
}

_CLOSE_MAP = {
    "b": "b",
    "strong": "b",
    "i": "i",
    "em": "i",
    "u": "u",
    "ins": "u",
    "s": "s",
    "strike": "s",
    "del": "s",
    "code": "code",
    "pre": "pre",
    "tg-spoiler": "tg-spoiler",
    "a": "a",
    # spoiler as span
    "span": "span",
}

_TAG_RE = re.compile(r"<[^>]+>")
_A_OPEN_RE = re.compile(r"""^<a\s+href=(["'])(.*?)\1\s*>$""", re.IGNORECASE)
_SIMPLE_OPEN_RE = re.compile(r"^<([a-zA-Z0-9\-]+)\s*>$", re.IGNORECASE)
_CODE_OPEN_RE = re.compile(r"^<code(\s+class=(['\"]).*?\2)?\s*>$", re.IGNORECASE)
_PRE_OPEN_RE = re.compile(r"^<pre(\s+.*)?\s*>$", re.IGNORECASE)
_CLOSE_RE = re.compile(r"^</([a-zA-Z0-9\-]+)\s*>$", re.IGNORECASE)
_BR_RE = re.compile(r"^<br\s*/?>$", re.IGNORECASE)
_SPOILER_SPAN_OPEN_RE = re.compile(r"""^<span\s+class=(["'])tg-spoiler\1\s*>$""", re.IGNORECASE)

_AMP_SAFE_RE = re.compile(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z]+;)")


def _escape_text_preserve_entities(s: str) -> str:
    # Escape < and > always; escape & only when it is not an entity start
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    s = _AMP_SAFE_RE.sub("&amp;", s)
    return s


def _escape_attr(s: str) -> str:
    s = _escape_text_preserve_entities(s)
    s = s.replace('"', "&quot;")
    return s


def strip_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]*>", "", text)


def preview_plain(text: Optional[str], limit: int = 80) -> str:
    """
    Day list / schedule list uchun: HTML'ni strip qilib, xavfsiz preview qaytaradi.
    Bu string parse_mode="HTML" ichida ham xavfsiz (taglar yo‘q).
    """
    if not text:
        return ""
    plain = strip_tags(text)
    plain = plain.strip()
    if len(plain) > limit:
        plain = plain[: max(0, limit - 1)] + "…"
    return _escape_text_preserve_entities(plain)


def repair_telegram_html(text: Optional[str]) -> str:
    """
    Telegram HTML uchun minimal "repair":
    - ruxsat etilgan teglarni qoldiradi (b,i,u,s,code,pre,tg-spoiler,a)
    - yopilmagan teglarni oxirida yopib beradi
    - nesting buzilsa ham stack asosida to‘g‘rilab yopadi
    - noma'lum teglarni oddiy tekst sifatida escape qiladi
    """
    if not text:
        return ""

    out: list[str] = []
    stack: list[str] = []

    last = 0
    for m in _TAG_RE.finditer(text):
        # Text segment
        chunk = text[last:m.start()]
        if chunk:
            out.append(_escape_text_preserve_entities(chunk))

        raw_tag = m.group(0)
        tag = raw_tag.strip()

        # <br> -> newline
        if _BR_RE.match(tag):
            out.append("\n")
            last = m.end()
            continue

        # <span class="tg-spoiler">
        if _SPOILER_SPAN_OPEN_RE.match(tag):
            out.append("<tg-spoiler>")
            stack.append("tg-spoiler")
            last = m.end()
            continue

        # <a href="...">
        a_open = _A_OPEN_RE.match(tag)
        if a_open:
            href = a_open.group(2).strip()
            safe_href = _escape_attr(href)
            out.append(f'<a href="{safe_href}">')
            stack.append("a")
            last = m.end()
            continue

        # <code ...> (class is optional)
        if _CODE_OPEN_RE.match(tag):
            out.append("<code>")
            stack.append("code")
            last = m.end()
            continue

        # <pre ...>
        if _PRE_OPEN_RE.match(tag):
            out.append("<pre>")
            stack.append("pre")
            last = m.end()
            continue

        # Simple open: <b>, <strong>, <i>, ...
        o = _SIMPLE_OPEN_RE.match(tag)
        if o:
            name_raw = o.group(1).lower()
            name = _OPEN_MAP.get(name_raw)
            if name in _ALLOWED_CANONICAL:
                out.append(f"<{name}>")
                stack.append(name)
                last = m.end()
                continue
            # unknown open tag -> escape
            out.append(_escape_text_preserve_entities(tag))
            last = m.end()
            continue

        # Closing tag
        c = _CLOSE_RE.match(tag)
        if c:
            close_raw = c.group(1).lower()

            # Special: </span> for spoiler
            if close_raw == "span" and stack and stack[-1] == "tg-spoiler":
                stack.pop()
                out.append("</tg-spoiler>")
                last = m.end()
                continue

            close_name = _CLOSE_MAP.get(close_raw)
            if close_name is None:
                out.append(_escape_text_preserve_entities(tag))
                last = m.end()
                continue

            # Close according to stack
            if close_name in stack:
                while stack and stack[-1] != close_name:
                    top = stack.pop()
                    out.append(f"</{top}>")
                if stack and stack[-1] == close_name:
                    stack.pop()
                    out.append(f"</{close_name}>")
            else:
                # extra closing tag -> escape
                out.append(_escape_text_preserve_entities(tag))

            last = m.end()
            continue

        # Anything else -> escape
        out.append(_escape_text_preserve_entities(tag))
        last = m.end()

    # Tail text
    tail = text[last:]
    if tail:
        out.append(_escape_text_preserve_entities(tail))

    # Close remaining tags
    while stack:
        out.append(f"</{stack.pop()}>")

    return "".join(out)


async def safe_answer_html(message_obj, text: str, **kwargs):
    """
    1) HTML'ni repair qilib yuboradi
    2) TelegramBadRequest bo‘lsa — plain text (escape) fallback yuboradi
    """
    fixed = repair_telegram_html(text)
    try:
        return await message_obj.answer(fixed, parse_mode="HTML", **kwargs)
    except TelegramBadRequest:
        fallback = _escape_text_preserve_entities(text or "")
        return await message_obj.answer(fallback, parse_mode="HTML", **kwargs)
