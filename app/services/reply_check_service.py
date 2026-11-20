"""Local Section A checks against the evidence supplied for this particular reply."""

import logging
import re
import unicodedata
from urllib.parse import urlsplit


_MONTHS = {
    alias: number for number, names in enumerate((
        "jan january januari", "feb february februari", "mar march mac",
        "apr april", "may mei", "jun june", "jul july julai",
        "aug august ogos ogs", "sep sept september", "oct october okt oktober",
        "nov november", "dec december dis disember",
    ), 1) for alias in names.split()
}
_MONTH = "(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")(?![a-z])"
_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RINGGIT = r"(?:MYR|RM|ringgit|令吉|马币|馬幣)"
_CURRENCY = rf"(?:{_RINGGIT}|SGD|USD|\$)"
_PERIOD = r"(?:[ap]\.?m\.?|pagi|tengah\s+hari|petang|malam)"
_ZH_NUM = r"[0-9零〇一二两兩三四五六七八九十]{1,3}"
_ZH_PERIOD = r"(?:上午|早上|凌晨|中午|下午|晚上)"
# A single pass keeps embedded prices, dates and phone-like strings inside URLs
# from becoming additional, independent findings.
_TOKEN = re.compile(
    r"(?P<link>(?<![a-z0-9_.@-])(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,63}"
    r"(?::\d+)?(?:[/?#][^\s<>\"“”‘’。，、！？；：\[\]]*)?(?=$|[\s<>\"“”‘’。，、！？；：\[\]()]|[.,!?;](?:\s|$)))"
    rf"|(?P<price>(?<![a-z0-9]){_CURRENCY}\s*{_AMOUNT}|(?<![\d.]){_AMOUNT}\s*{_RINGGIT}(?![a-z]))"
    rf"|(?P<date>(?<!\d)(?:\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}[/\-]\d{{1,2}}(?:[/\-]\d{{2,4}})?"
    rf"|\d{{1,2}}\s+{_MONTH}(?:\s+\d{{4}})?|(?:\d{{4}}年)?{_ZH_NUM}月{_ZH_NUM}[日号號])(?!\d))"
    rf"|(?P<time>(?<!\d)(?:\d{{1,2}}:\d{{2}}(?:\s*{_PERIOD}(?![a-z]))?"
    rf"|\d{{1,2}}(?:\.\d{{2}})?\s*{_PERIOD}(?![a-z])"
    rf"|{_ZH_PERIOD}?{_ZH_NUM}[点點时時](?:半|{_ZH_NUM}分)?)(?!\d))"
    r"|(?P<number>(?<![\d+])\+?\d(?:[ \t()-]*\d){7,18}(?!\d))",
    re.IGNORECASE,
)
_BANK_CUE = re.compile(
    r"(?:bank(?:ing)?|account|a/c|acct|akaun|rekening|maybank|cimb|账户|帐户|账号|帳戶|帳號|户口)"
    r"[^.!?。！？\d]{0,50}$", re.I,
)
_PHONE_CUE = re.compile(r"(?:phone|hotline|tel(?:ephone|efon)?|whatsapp|电话|電話|热线|熱線)\s*(?:no\.?|number)?[:\s-]*$", re.I)
_BUDGET = re.compile(r"budget|bajet|预算|預算", re.I)
_ATTRIBUTION = re.compile(r"\byou (?:said|mentioned|wrote|asked)|\b(?:awak|anda) (?:kata|sebut)|你(?:说|說|提到)", re.I)
_ZH_PUNCTUATION = str.maketrans("，；！？、", "。。。。。")
_FACT_HINT = re.compile(r"\d|[月点點时時]|\.[a-z]", re.I)
_QUOTED_PRICE = re.compile(
    r"(?:price|costs?|charge[sd]?|fee|harga|berharga|caj|售价|價格|价格|收费|收費)"
    r"[^.!?。！？,\d]{0,22}$", re.I,
)


def _number(word):
    if word.isdecimal():
        return int(word)
    digits = "零一二三四五六七八九"
    word = word.replace("两", "二").replace("兩", "二").replace("〇", "零")
    if "十" in word:
        tens, _, units = word.partition("十")
        return (digits.find(tens or "一") * 10) + digits.find(units or "零")
    return int("".join(str(digits.index(char)) for char in word))


def _date(raw):
    if "月" in raw:
        parts = re.split("[年月日号號]", raw)[:-1]
        year, month, day = ([""] + parts if len(parts) == 2 else parts)
        day, month = _number(day), _number(month)
    elif re.search(r"[a-z]", raw, re.I):
        day, name, *years = raw.lower().split()
        day, month, year = int(day), _MONTHS[name], "".join(years)
    else:
        parts = re.split("[/-]", raw)
        if len(parts[0]) == 4:
            year, month, day = parts
        else:
            day, month, *years = parts
            year = "".join(years)
        day, month = int(day), int(month)
    if 1 <= day <= 31 and 1 <= month <= 12:
        return f"{day}/{month}" + (f"/{year}" if year else "")


def _time(raw):
    if re.search("[点點时時]", raw):
        match = re.fullmatch(rf"({_ZH_PERIOD})?({_ZH_NUM})[点點时時](半|{_ZH_NUM}分)?", raw)
        period, hour, minutes = match.groups()
        hour = _number(hour)
        minute = _number(minutes[:-1]) if minutes and minutes != "半" else 0
        if minutes == "半":
            minute = 30
    else:
        match = re.fullmatch(rf"(\d+)(?:[:.](\d+))?\s*({_PERIOD})?", raw, re.I)
        hours, minutes, period = match.groups()
        hour, minute = int(hours), int(minutes or 0)
    if period:
        if not 1 <= hour <= 12:
            return None
        period = period.lower().replace(".", "")
        if period == "malam" and hour == 12:
            hour = 0
        elif period in ("pm", "petang", "malam", "下午", "中午", "晚上") or period.startswith("tengah"):
            hour = hour % 12 + 12
        else:
            hour %= 12
    if hour < 24 and minute < 60:
        return f"{hour:02}:{minute:02}"


def _facts(text):
    text = unicodedata.normalize("NFKC", text.translate(_ZH_PUNCTUATION))
    if not _FACT_HINT.search(text):
        return
    for match in _TOKEN.finditer(text):
        kind, raw = match.lastgroup, match.group()
        usage = None
        if kind == "number":
            digits = re.sub(r"\D", "", raw)
            before = text[max(0, match.start() - 65):match.start()]
            local = "0" + digits[2:] if digits.startswith("60") else digits
            if _BANK_CUE.search(before) and not _PHONE_CUE.search(before):
                kind, value = "bank", digits
            elif re.fullmatch(r"0[1-9]\d{7,9}", local):
                kind, value = "phone", local
            elif raw == text.strip() or (len(digits) >= 12 and digits.startswith("0000")):
                kind, value = "bank", digits
            else:
                continue
        elif kind == "price":
            amount = re.search(_AMOUNT, raw).group().replace(",", "")
            whole, _, fraction = amount.partition(".")
            fraction = fraction.rstrip("0")
            currency = re.search(_CURRENCY, raw, re.I).group().upper()
            currency = "RM" if re.fullmatch(_RINGGIT, currency, re.I) else currency
            value = currency + (whole.lstrip("0") or "0") + ("." + fraction if fraction else "")
            before = re.split(r"[.!?。！？,]", text[max(0, match.start() - 45):match.start()])[-1]
            after = re.split(r"[.!?。！？,]", text[match.end():match.end() + 25])[0]
            if _QUOTED_PRICE.search(before):
                usage = "price"
            elif _BUDGET.search(before) or re.match(r"\s*(?:within|is|in|of|的)?\s*(?:my |our )?budget\b", after, re.I):
                usage = "budget"
            elif _ATTRIBUTION.search(before):
                usage = "quote"
        elif kind == "date":
            value = _date(raw)
        elif kind == "time":
            value = _time(raw)
        else:
            raw = raw.rstrip(".,!?;")
            # Markdown wraps destinations in parentheses. Paired parentheses inside a path are significant.
            extra_closes = raw.count(")") - raw.count("(")
            if extra_closes > 0 and raw.endswith(")"):
                trailing_closes = len(raw) - len(raw.rstrip(")"))
                raw = raw[:-min(extra_closes, trailing_closes)]
            parts = urlsplit(raw if "://" in raw else "//" + raw)
            value = parts.netloc.lower() + parts.path.rstrip("/")
            if parts.query:
                value += "?" + parts.query
            if parts.fragment:
                value += "#" + parts.fragment
        if value is not None:
            yield kind, value, usage


def check_reply(reply, *, knowledge, profile, history, customer_message):
    """Return unique unsupported values in draft order. Errors never interrupt delivery."""
    try:
        claims = list(_facts(reply))
        if not claims:
            return []
        business = [
            chunk if isinstance(chunk, str) else chunk.get("content") or chunk.get("text") or ""
            for chunk in knowledge
        ]
        for field, value in profile.items():
            if isinstance(value, str):
                if "account" in field.lower() or "akaun" in field.lower():
                    value = f"Account: {value}"
                business.append(value)
        customer = [turn["content"] for turn in history if turn.get("role") == "user"]
        customer.append(customer_message)
        missing = {(kind, value) for kind, value, _ in claims}
        for text in business:
            for kind, value, _ in _facts(text):
                missing.discard((kind, value))
                if not missing:
                    return []
        budgets = set()
        for text in customer:
            for kind, value, usage in _facts(text):
                if usage == "budget":
                    budgets.add((kind, value))
                else:
                    missing.discard((kind, value))
        findings = {}
        for kind, value, usage in claims:
            fact = (kind, value)
            if fact in missing and (fact not in budgets or usage not in ("budget", "quote")):
                findings[fact] = {"category": "facts", "subtype": kind, "value": value}
        return list(findings.values())
    except Exception as error:
        logging.warning("[ReplyCheck] %s", type(error).__name__)
        return []
