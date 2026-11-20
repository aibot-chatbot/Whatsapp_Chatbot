"""Local, log-only draft checks against the evidence supplied for this reply."""

import logging
import re
import unicodedata
from urllib.parse import urlsplit

from app.services.reply_promise_rules import promise_findings


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

_SECRET = re.compile(
    r"(?<![A-Za-z0-9_])(?:(sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16}(?![A-Z0-9])"
    r"|ghp_[A-Za-z0-9]{36}(?![A-Za-z0-9])|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
    r"|(?i:bearer)[ \t]+([A-Za-z0-9._~+/-]{8,}=*)"
    r"|(?i:(?:api[_ -]?)?key|token|secret|password)[\"']?\s*(?:[:=]\s*|\s+)[\"']?"
    r"([A-Za-z0-9+/_-]{24,}={0,2}))"
)
_PROMPT_DISCLOSURE = re.compile(
    r"\b(?:my (?:internal |system )?instructions are|my system prompt (?:is|says)"
    r"|saya diarahkan untuk|arahan sistem saya (?:ialah|berbunyi))\b|我的(?:内部指令|系统提示)", re.I,
)
_INTERNAL_DISCLOSURE = re.compile(
    r"(?:staff[- ]only notes?|internal notes?|nota staf)\s*(?:says?|reads?|berbunyi|写着|写明)", re.I,
)
_REFUSAL = re.compile(
    r"\b(?:cannot|can't|can’t|won't|will not|tidak boleh|tak boleh)\s+"
    r"(?:tell|share|reveal|disclose|berkongsi|kongsi)|(?:不能|无法)(?:分享|透露|公开)", re.I,
)
_CLAUSE = re.compile(r"[.!?;。\n！？；]+")
_WORDS = re.compile(r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+")
_CONTACT = re.compile(
    r"(?<![a-z0-9_%+.-])(?P<email>[a-z0-9_%+.-]{1,64}@(?:[a-z0-9-]{1,63}\.)+[a-z]{2,63})(?![a-z0-9-])"
    r"|(?<![a-z0-9_+/.-])(?P<phone>\+?\(?\d(?:[ ()\t-]*\d){7,14})(?![a-z0-9_])", re.I | re.ASCII,
)
_NANP = re.compile(r"\(?[2-9]\d{2}\)?[ -]?[2-9]\d{2}[ -]?\d{4}")


def _secret_findings(reply):
    # Keep values only for local deduplication, including a token quoted under two labels.
    secrets = {m[m.lastindex].rstrip(".") for m in _SECRET.finditer(reply)}
    return [{"category": "leak", "subtype": "secret"} for _ in secrets]


def _phone_digits(digits):
    if len(digits) == 11 and digits.startswith("1") and _NANP.fullmatch(digits[1:]):
        return digits[1:]
    return digits


def _contacts(text, *, evidence=False):
    for match in _CONTACT.finditer(text):
        value = match.group()
        if match.lastgroup == "email":
            yield value.casefold()
            continue
        digits = re.sub(r"\D", "", value)
        before = text[max(0, match.start() - 65):match.start()]
        if _BANK_CUE.search(before):
            continue
        # Section A already checks Malaysian numbers against these same sources.
        local = "0" + digits[2:] if digits.startswith("60") else digits
        if re.fullmatch(r"0[1-9]\d{7,9}", local):
            continue
        if (value.startswith("+") or _NANP.fullmatch(value) or _PHONE_CUE.search(before)
                or (evidence and value == text.strip())):
            yield _phone_digits(digits)


def _contact_findings(reply, business, customer, facts):
    missing = set(_contacts(reply))
    if missing:
        for text in (*business, *customer):
            missing.difference_update(_contacts(text, evidence=True))
        missing.difference_update(_phone_digits(f["value"]) for f in facts if f["subtype"] == "bank")
    return [{"category": "leak", "subtype": "other_customer"} for _ in missing]


def _prompt_findings(reply, system_prompt):
    subtypes = set()
    for clause in _CLAUSE.split(reply):
        if not _REFUSAL.search(clause):
            if _PROMPT_DISCLOSURE.search(clause):
                subtypes.add("system_prompt")
            if _INTERNAL_DISCLOSURE.search(clause):
                subtypes.add("internal")
    if system_prompt and "system_prompt" not in subtypes:
        # Match whole tokens, including individual Han characters in unspaced text.
        words = _WORDS.findall(reply.casefold())
        if len(words) >= 12:
            windows = {tuple(words[i:i + 12]) for i in range(len(words) - 11)}
            for section in system_prompt.split("\n\n"):
                private = _WORDS.findall(section.casefold())
                if any(tuple(private[i:i + 12]) in windows for i in range(len(private) - 11)):
                    subtypes.add("system_prompt")
                    break
    return [{"category": "leak", "subtype": subtype} for subtype in sorted(subtypes)]


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


def _fact_findings(claims, business, customer):
    if not claims:
        return []
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


def check_reply(reply, *, knowledge, profile, history, customer_message, system_prompt=""):
    """Return findings for this draft. Errors never interrupt delivery."""
    try:
        chunks = [chunk if isinstance(chunk, str) else chunk.get("content") or chunk.get("text") or ""
                  for chunk in knowledge]
        business = list(chunks)
        for field, value in profile.items():
            if isinstance(value, str):
                if "account" in field.lower() or "akaun" in field.lower():
                    value = f"Account: {value}"
                business.append(value)
        customer = [turn["content"] for turn in history if turn.get("role") == "user"]
        customer.append(customer_message)
        findings = _fact_findings(list(_facts(reply)), business, customer)
        contacts = _contact_findings(reply, business, customer, findings)
        findings.extend(_secret_findings(reply))
        findings.extend(_prompt_findings(reply, system_prompt))
        findings.extend(contacts)
        findings.extend(promise_findings(reply, chunks))
        return findings
    except Exception as error:
        logging.warning("[ReplyCheck] %s", type(error).__name__)
        return []
