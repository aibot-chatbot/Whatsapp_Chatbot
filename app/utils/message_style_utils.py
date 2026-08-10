"""
message_style_utils.py
~~~~~~~~~~~~~~~~~~~~~~~
Shared helpers for platform-specific message formatting.

Used by telegram_utils.py and whatsapp_utils.py to:
- Extract [BUTTONS: A | B | C] tags from AI replies
- Format text for Telegram MarkdownV2
- Format text for WhatsApp markdown (*bold*, _italic_)
"""

import re


# ---------------------------------------------------------------------------
# Button tag parsing
# ---------------------------------------------------------------------------

_BUTTONS_PATTERN = re.compile(
    r"\[BUTTONS?:\s*(.*?)\]\s*$",
    re.IGNORECASE | re.DOTALL,
)

_BUTTON_MAX_LABEL_LEN = 20
_BUTTON_MAX_COUNT = 3


def parse_buttons_tag(text: str) -> tuple:
    """Extract [BUTTONS: A | B | C] tag from the end of an AI reply.

    Returns:
        (clean_text, button_labels) where:
        - clean_text has the tag stripped
        - button_labels is a list of up to 3 strings, each ≤20 chars
        If no tag is found, returns (text, []).
    """
    if not text:
        return text, []

    match = _BUTTONS_PATTERN.search(text)
    if not match:
        return text, []

    raw_labels = match.group(1)
    labels = [lbl.strip() for lbl in raw_labels.split("|") if lbl.strip()]

    # Enforce platform limits
    labels = [lbl[:_BUTTON_MAX_LABEL_LEN] for lbl in labels]
    labels = labels[:_BUTTON_MAX_COUNT]

    clean_text = text[: match.start()].rstrip()

    return clean_text, labels


# ---------------------------------------------------------------------------
# Telegram MarkdownV2 formatting
# ---------------------------------------------------------------------------

# Characters that must be escaped in MarkdownV2 plain text (not inside entities)
_TG_ESCAPE_CHARS = r"\_*[]()~`>#+-=|{}.!"

_TG_BOLD_PATTERN = re.compile(r"\*\*(.*?)\*\*", re.DOTALL)
_TG_ITALIC_PATTERN = re.compile(r"(?<!\w)_(.*?)_(?!\w)", re.DOTALL)
_TG_CODE_PATTERN = re.compile(r"`([^`]+)`")


def _escape_tg(text: str) -> str:
    """Escape special MarkdownV2 characters in plain text segments."""
    result = []
    for ch in text:
        if ch in _TG_ESCAPE_CHARS:
            result.append("\\" + ch)
        else:
            result.append(ch)
    return "".join(result)


def format_for_telegram_markdown(text: str) -> str:
    """Convert AI reply text to Telegram MarkdownV2 format.

    - **word** → *word* (bold)
    - _word_  → _word_ (italic)
    - `word`  → `word` (code, preserved)
    - All other special MarkdownV2 chars are escaped.

    Returns a string safe to send with parse_mode="MarkdownV2".
    Falls back to escaping the whole string if patterns fail.
    """
    if not text:
        return text

    # We process the string in segments to correctly escape non-entity text.
    # Strategy: find all markdown spans in order, escape text between them,
    # then wrap spans in their entity markers.

    segments = []
    cursor = 0
    combined = re.compile(
        r"(\*\*.*?\*\*|_.*?_|`[^`]+`)",
        re.DOTALL,
    )

    for m in combined.finditer(text):
        # Escape the plain text before this match
        plain = text[cursor : m.start()]
        if plain:
            segments.append(_escape_tg(plain))

        span = m.group(0)
        if span.startswith("**") and span.endswith("**"):
            inner = _escape_tg(span[2:-2])
            segments.append(f"*{inner}*")
        elif span.startswith("`") and span.endswith("`"):
            # Code: escape backtick content minimally
            inner = span[1:-1].replace("\\", "\\\\").replace("`", "\\`")
            segments.append(f"`{inner}`")
        elif span.startswith("_") and span.endswith("_"):
            inner = _escape_tg(span[1:-1])
            segments.append(f"_{inner}_")
        else:
            segments.append(_escape_tg(span))

        cursor = m.end()

    # Escape remaining plain text
    tail = text[cursor:]
    if tail:
        segments.append(_escape_tg(tail))

    return "".join(segments)


# ---------------------------------------------------------------------------
# WhatsApp markdown formatting
# ---------------------------------------------------------------------------

def format_for_whatsapp_markdown(text: str) -> str:
    """Convert AI reply text to WhatsApp markdown format.

    WhatsApp supports:
    - *bold*
    - _italic_
    - ~strikethrough~
    - `monospace`

    Converts **word** → *word* and preserves _italic_.
    Strips markdown headings (# ## ###) as WhatsApp does not support them.
    """
    if not text:
        return text

    # Convert **bold** → *bold* (WhatsApp bold)
    result = re.sub(r"\*\*(.*?)\*\*", r"*\1*", text)

    # Strip markdown headings
    result = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", result)

    # Collapse excess blank lines
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()
