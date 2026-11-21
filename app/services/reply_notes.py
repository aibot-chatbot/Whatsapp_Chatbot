"""Parse hidden model notes without recording a booking or updating a needs card."""

import json
import re


NEEDS_OPEN = re.compile(r"<<[\s​-‏⁠﻿]*NEEDS\w*", re.IGNORECASE)
BOOKING_OPEN = re.compile(r"<<[\s​-‏⁠﻿]*BOOKING\w*", re.IGNORECASE)


def scan_markers(text, opening_pattern=BOOKING_OPEN):
    """Return (reply without markers, first valid marker's fields or None, whether any marker was seen).

    `opening_pattern` matches a marker's opening ("<<BOOKING" by default); needs_card_service
    passes its own so both hidden notes are parsed and removed by this one scanner.
    """
    decoder = json.JSONDecoder()
    pieces, fields, seen, position = [], None, False, 0
    for opening in opening_pattern.finditer(text):
        if opening.start() < position:
            continue
        seen = True
        pieces.append(text[position:opening.start()])
        start = opening.end()
        while start < len(text) and text[start].isspace():
            start += 1
        end, parsed = None, None
        try:
            parsed, after = decoder.raw_decode(text, start)
            while after < len(text) and text[after].isspace():
                after += 1
            if text.startswith(">>", after):
                end = after + 2
        except (ValueError, RecursionError):
            parsed = None
        if end is None:
            # Malformed. The marker is one line, so drop through the last ">>" on that line (or to
            # its end): the customer's own details must not leak, and the rest of the reply stays.
            line_end = text.find("\n", opening.end())
            line_end = len(text) if line_end == -1 else line_end
            close = text.rfind(">>", opening.end(), line_end)
            end = line_end if close == -1 else close + 2
            parsed = None
        if fields is None and isinstance(parsed, dict):
            fields = parsed
        position = end
    pieces.append(text[position:])
    if not seen:
        return text, None, False
    return "".join(pieces).strip(), fields, True


def visible_draft(reply):
    """Remove notes in delivery order while leaving the original for the note handlers."""
    if "<<" not in reply:
        return reply
    text, _, _ = scan_markers(reply, NEEDS_OPEN)
    return scan_markers(text, BOOKING_OPEN)[0]
