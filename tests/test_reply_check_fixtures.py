"""Offline checks for the labelled examples, independent of any reply reviewer."""

import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path


CHATS = json.loads((Path(__file__).parent / "fixtures/reply_check_chats.json").read_text(encoding="utf-8"))
FIELDS = set("id language industry knowledge business_profile history customer_message bot_reply "
             "expected category subtype reason pending_lawyer".split())

# All long numbers in every text field must be fake. XX ranges from 00 to 99.
# Phones: +60 12-000 00XX or 012-000 00XX. Bank accounts: 0000 0000 00XX.
LONG_NUMBER = re.compile(r"\+?\d(?:[ ().-]*\d){6,}")
FAKE_PHONE = re.compile(r"(?:6012|012)00000\d{2}")
FAKE_BANK = re.compile(r"0{10}\d{2}")
KEY_PREFIX = re.compile(r"sk-|AKIA|ASIA[A-Z0-9]{16}|gh[pousr]_|github_pat_|xox[baprs]-", re.I)
LINK = re.compile(r"(?:https?://)?((?:[\w-]+\.)+[a-z]{2,})([/#?][\w./?&=%#-]*)?", re.I | re.ASCII)


def test_fixture_shape_and_coverage():
    assert len(CHATS) == 60
    assert len({c["id"] for c in CHATS}) == 60
    languages = Counter(c["language"] for c in CHATS)
    assert set(languages) == {"en", "ms", "zh", "mixed"} and min(languages.values()) >= 12
    assert {c["expected"] for c in CHATS} == {"pass", "hold", "filter"}
    holds = Counter(c["category"] for c in CHATS if c["expected"] == "hold")
    assert set(holds) == {"facts", "leak", "promise"} and min(holds.values()) >= 8
    for c in CHATS:
        assert c.keys() == FIELDS and re.fullmatch(r"rc-\d{3}", c["id"])
        assert all(isinstance(c[k], str) and c[k].strip() for k in FIELDS - {
            "knowledge", "business_profile", "history", "pending_lawyer"
        }), c["id"]
        assert isinstance(c["knowledge"], list) and all(isinstance(s, str) and s.strip() for s in c["knowledge"])
        assert c["business_profile"].keys() == {"name", "phone", "website"}
        assert all(isinstance(s, str) and s.strip() for s in c["business_profile"].values())
        assert isinstance(c["history"], list)
        for turn in c["history"]:
            assert turn.keys() == {"role", "content"} and turn["role"] in {"user", "assistant"}
            assert isinstance(turn["content"], str) and turn["content"].strip()
        assert (c["category"] == "filtered") == (c["expected"] == "filter")
        assert (c["category"] == "none") == (c["expected"] == "pass")
        assert isinstance(c["pending_lawyer"], bool)
        if c["industry"] in {"clinic", "dental", "dental_clinic", "insurance"}:
            assert c["pending_lawyer"], c["id"]


def test_contacts_and_credentials_are_synthetic():
    for c in CHATS:
        text = json.dumps(c, ensure_ascii=False)
        if KEY_PREFIX.search(text):
            raise AssertionError(f"{c['id']} contains a credential-like prefix")
        for host, _ in LINK.findall(text):
            assert host.lower() == "example.my" or host.lower().endswith(".example.my"), c["id"]
        assert FAKE_PHONE.fullmatch(re.sub(r"\D", "", c["business_profile"]["phone"])), c["id"]
        for candidate in LONG_NUMBER.findall(text):
            digits = re.sub(r"\D", "", candidate)
            if not (FAKE_PHONE.fullmatch(digits) or FAKE_BANK.fullmatch(digits)):
                raise AssertionError(f"{c['id']} contains a number outside the fake ranges")


def fact_values(kind, text):
    """Compare only the notations used in this corpus."""
    if kind == "price":
        return {Decimal(v.replace(",", "")) for v in re.findall(r"RM\s*(\d[\d,]*(?:\.\d+)?)", text, re.I)}
    if kind in {"phone", "bank"}:
        numbers = {re.sub(r"\D", "", v) for v in LONG_NUMBER.findall(text)}
        if kind == "bank":
            return {v for v in numbers if FAKE_BANK.fullmatch(v)}
        return {re.sub(r"^60", "0", v) for v in numbers if FAKE_PHONE.fullmatch(v)}
    if kind == "link":
        return {host.lower() + path.rstrip(".").removesuffix("/") for host, path in LINK.findall(text)}
    if kind == "date":
        text = re.sub(r"(\d{1,2})\s+(?:Dec(?:ember)?|Dis(?:ember)?)\b", r"\1/12", text, flags=re.I)
        text = re.sub(r"(\d{1,2})月(\d{1,2})[日号]", r"\2/\1", text)
        return {(int(d), int(m)) for d, m in re.findall(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)}
    assert kind == "time", f"Unknown fact subtype {kind}"
    def clock_24(match):
        hour, minute, period = match.groups()
        hour = int(hour) % 12 + (12 if period == "pm" else 0)
        return f"{hour}:{minute or '00'}"

    text = re.sub(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", clock_24, text.lower())
    return {(int(h), int(m)) for h, m in re.findall(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)}


def test_facts_holds_have_an_unsupported_value():
    for c in CHATS:
        if (c["expected"], c["category"]) != ("hold", "facts"):
            continue
        sources = [*c["knowledge"], *c["business_profile"].values(), c["customer_message"]]
        sources.extend(turn["content"] for turn in c["history"] if turn["role"] == "user")
        supported = set().union(*(fact_values(c["subtype"], s) for s in sources))
        assert fact_values(c["subtype"], c["bot_reply"]) - supported, c["id"]
