"""Filter 2: a review of customer text on Cloudflare Workers AI, never on OpenRouter (plan A4).

Llama Guard 3 does not list Malay or Chinese, but measured on 36 labelled messages (2026-11-10,
scripts/content_review_compare.py) it caught 17 of 18 unsafe ones read as written, with no false
alarm, at about 0.8 s; translating first with m2m100 caught only 13 at 2.3 s, because the
translation loses the meaning of threats. So the original text is reviewed by default; the
translate option stays for re-measuring. Both models run with zero data retention. Decision D4 (2026-11-10, the
owner) allows Cloudflare to read every customer message for this review.

review_text never raises: an outage or an unreadable answer is "unavailable", and callers let
the message through, because Filter 1 already ran on our own server. Nothing here logs the text.
"""
import logging
import os
import re
import time
from dataclasses import dataclass

import requests

from app.services import content_filter

GUARD_MODEL = "@cf/meta/llama-guard-3-8b"
TRANSLATE_MODEL = "@cf/meta/m2m100-1.2b"
OPTIONS = ("guard_only", "translate_guard")
TIMEOUT = (3, 6)
BLOCK_WAIT_SECONDS = 4
# shortcut: only the first 4,000 characters are reviewed; Phase 5's input cap makes this the whole message.
MAX_REVIEW_CHARS = 4000

# Llama Guard 3 hazard codes we act on, most serious first. S5 defamation, S6 specialised advice,
# S7 privacy, S8 intellectual property, S13 elections and S14 code abuse are ignored: clinics,
# insurers and lawyers are asked for advice and personal details every day.
_GROUPS = (
    ("S4", content_filter.CHILD_SEXUAL),
    ("S11", content_filter.SELF_HARM),
    ("S1", content_filter.THREAT),
    ("S9", content_filter.WEAPONS),
    ("S10", "hate"),
    ("S3", "sexual"),
    ("S12", "sexual"),
    ("S2", "crime"),
)
_CJK = re.compile(r"[㐀-鿿]")
# Common Malay words that English never uses; one is enough to translate first.
_MALAY = re.compile(
    r"\b(?:saya|aku|awak|kau|nak|tak|boleh|untuk|dengan|tolong|berapa|macam|mana|kenapa|bila|"
    r"sangat|hantar|tempah|beli|jual|dekat|sudah|belum|tiada|ada|ini|itu|kami|kita|mereka)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReviewResult:
    verdict: str  # "safe", "unsafe" or "unavailable"
    group: str | None = None
    categories: tuple = ()

    def as_flag(self):
        return content_filter.ContentFlag(self.group, "review." + self.categories[0], filter=2)


UNAVAILABLE = ReviewResult("unavailable")


def mode():
    """CONTENT_REVIEW_MODE: off (default), log (record only, off the reply path) or block.

    Block mode is safe with the reply pipeline's four-second wall-clock wait and stored-message
    IDs on blocking flags. History, report, observation and memory inputs exclude those IDs.
    A slow or unavailable review lets the message through; a late unsafe verdict is logged only.
    Keep production in log mode until the owner enables block after review.
    """
    value = os.getenv("CONTENT_REVIEW_MODE", "").strip().lower()
    return value if value in {"log", "block"} else "off"


def detect_language(text):
    if _CJK.search(text):
        return "zh"
    return "ms" if _MALAY.search(text) else "en"


def _run(model, body):
    account = os.getenv("CLOUDFLARE_AI_ACCOUNT_ID", "").strip()
    token = os.getenv("CLOUDFLARE_AI_API_TOKEN", "").strip()
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
        raise RuntimeError("Cloudflare Workers AI is not configured")
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}",
        headers={"Authorization": f"Bearer {token}"}, json=body, timeout=TIMEOUT, allow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Workers AI returned HTTP {response.status_code}")
    data = response.json()
    if not isinstance(data, dict) or data.get("success") is False or not isinstance(data.get("result"), dict):
        raise RuntimeError("Workers AI returned an unreadable envelope")
    return data["result"]


def _to_english(text, language):
    try:
        translated = _run(TRANSLATE_MODEL, {"text": text, "source_lang": language, "target_lang": "en"})
        result = translated.get("translated_text")
        if isinstance(result, str) and result.strip():
            return result
    except Exception as error:
        logging.warning("[ContentReview] translation unavailable (%s); reviewing the original", type(error).__name__)
    return text


def _parse_guard(answer):
    lines = [line.strip() for line in str(answer or "").strip().splitlines() if line.strip()]
    if lines and lines[0].lower() == "safe":
        return ReviewResult("safe")
    if not lines or lines[0].lower() != "unsafe":
        return UNAVAILABLE
    codes = tuple(re.findall(r"S\d{1,2}", " ".join(lines[1:])))
    if not codes:
        return UNAVAILABLE  # "unsafe" with no hazard code is a truncated answer, not a safe one
    acted = [(code, group) for code, group in _GROUPS if code in codes]
    if not acted:
        return ReviewResult("safe", categories=codes)
    first_code, group = acted[0]
    return ReviewResult("unsafe", group, (first_code,) + tuple(code for code in codes if code != first_code))


def review_text(text, *, option="guard_only"):
    """Review one customer message. Returns a ReviewResult; never raises."""
    text = str(text or "")[:MAX_REVIEW_CHARS]
    if not text.strip():
        return ReviewResult("safe")
    started = time.perf_counter()
    try:
        language = detect_language(text)
        english = _to_english(text, language) if option == "translate_guard" and language != "en" else text
        body = {"messages": [{"role": "user", "content": english}], "temperature": 0}
        result = _parse_guard(_run(GUARD_MODEL, body).get("response"))
    except Exception as error:
        logging.warning("[ContentReview] review unavailable (%s)", type(error).__name__)
        return UNAVAILABLE
    logging.info("[ContentReview] verdict=%s group=%s ms=%d", result.verdict, result.group,
                 (time.perf_counter() - started) * 1000)
    return result
