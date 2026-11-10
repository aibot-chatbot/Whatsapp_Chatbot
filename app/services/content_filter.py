"""Filter 1: a word and pattern check that runs on our own server before any AI sees the text.

Plan Part A3 (Omnexa_AI_Safety_Token_FollowUp_Plan_2026-11-06.md). Only narrow, clear phrases
stop here, so ordinary words ("kill termites", "wedding shoot", "breast pump") pass; borderline
text is Filter 2's job. A flag carries its category and rule id, never the matched words, so
callers can log and store it without copying customer text.

Every pattern is a plain alternation with no nested repetition, so matching stays linear in the
length of the message.
"""
import re
import unicodedata
from dataclasses import dataclass

CHILD_SEXUAL = "child_sexual"
MALWARE_SCAM = "malware_scam"
DRUGS = "drugs"
WEAPONS = "weapons"
GAMBLING = "gambling"
ADULT = "adult"
THREAT = "threat"
SELF_HARM = "self_harm"

# Hate, race, religion and royalty phrases wait for the lawyer check (plan action list), and
# impersonation is left to Filter 2: "pretending to be from the bank" is how customers REPORT scams.
_RULES = (
    ("child.porn", CHILD_SEXUAL,
     r"\b(?:child|kid|kiddie|minor|underage|preteen|toddler)s? ?(?:porn|porno|pornography|nudes?|sex videos?|sex pics?)\b"),
    ("child.cp", CHILD_SEXUAL, r"\bcp (?:links?|videos?|vids?|pics?|content|collection)\b"),
    ("child.loli", CHILD_SEXUAL, r"\b(?:loli|lolicon|shota) ?(?:porn|hentai|nudes?|sex)\b"),
    ("child.pedo", CHILD_SEXUAL, r"\bpedo(?:phile)? ?(?:videos?|pics?|content|links?|groups?)\b"),
    ("child.ms", CHILD_SEXUAL, r"\b(?:lucah|bogel|seks) (?:budak|kanak kanak|bawah umur)\b"),
    ("child.zh", CHILD_SEXUAL, r"(?:儿童|幼女|幼童|未成年|萝莉)(?:色情|裸照|裸体|性爱|黄片)"),

    ("malware.build", MALWARE_SCAM,
     r"\b(?:write|make|create|build|code|sell|buy|send|need) (?:me |us )?(?:a |an |some )?"
     r"(?:keylogger|ransomware|malware|trojan|botnet|rootkit|phishing (?:kit|page|site|website))s?\b"),
    ("malware.carding", MALWARE_SCAM,
     r"\b(?:cvv|card|credit card) dumps?\b|\bfullz\b|\bcarding (?:method|tutorial|shop|forum)s?\b"),
    ("scam.mule", MALWARE_SCAM,
     r"\b(?:akaun keldai|money mules?|mule accounts?)\b|\b(?:jual|beli|sewa|sell|buy|rent) (?:akaun bank|bank accounts?)\b"),
    ("malware.zh", MALWARE_SCAM, r"钓鱼网站|木马程序|勒索软件|勒索病毒|洗黑钱|帮忙洗钱|洗钱服务|收银行卡|卖银行卡|银行卡四件套"),

    ("drugs.street", DRUGS,
     r"\b(?:syabu|shabu|pil kuda|ice ball)\b"
     r"|\b(?:jual|beli|sell|selling|buy|buying|order) (?:ganja|weed|marijuana|meth|methamphetamine|cocaine|heroin|ecstasy|mdma|dadah|kush|lsd)\b"
     r"|\b(?:ganja|weed|cocaine|meth) for sale\b"),
    ("drugs.medicine", DRUGS,
     r"\b(?:jual|beli|sell|selling|buy|buying|order) (?:xanax|tramadol|codeine|morphine|fentanyl|oxycodone|ketamine)\b"),
    ("drugs.zh", DRUGS, r"冰毒|海洛因|摇头丸|k粉|买大麻|卖大麻|大麻出售"),

    ("weapons.sale", WEAPONS,
     r"\b(?:jual|beli|sell|selling|buy|buying) (?:a |an |some )?(?:real )?"
     r"(?:guns?|pistols?|rifles?|shotguns?|firearms?|ammo|ammunition|bullets|grenades?|explosives?|senjata api|peluru)\b"),
    ("weapons.bomb", WEAPONS, r"\b(?:make|build|buat) (?:a )?(?:bomb|pipe bomb|bom)\b"),
    ("weapons.zh", WEAPONS, r"买枪|卖枪|枪支出售|出售枪支|自制炸弹|制作炸弹"),

    ("gambling.online", GAMBLING, r"\b(?:online casinos?|casino online|judi (?:online|dalam talian)|slot gacor)\b"),
    ("gambling.zh", GAMBLING, r"网赌|赌博网站|网上赌场|线上赌场|百家乐|博彩网站"),

    ("adult.services", ADULT,
     r"\b(?:escort|sex|sexual) (?:services?|girls?)\b|\b(?:urut|servis|perkhidmatan) batin\b"
     r"|\bhappy ending massage\b|\bservis seks\b"),
    ("adult.zh", ADULT, r"援交|约炮|特殊服务|性服务|外围女"),

    ("threat.kill", THREAT,
     r"\b(?:i|im|i'm|i am|i'll) (?:going to |gonna |will )?(?:kill|stab|murder) (?:you|u|your family|ur family)\b"),
    ("threat.ms", THREAT,
     r"\b(?:aku|saya|gua|aq) (?:akan |nak |mahu )?(?:bunuh|tikam) (?:kau|awak|engkau|kamu|korang|hang|ko)\b"),
    ("threat.bomb", THREAT,
     r"\b(?:bomb|blow up|burn down) (?:your|ur|the) (?:shop|store|office|restaurant|clinic|building|house|kedai)\b"
     r"|\b(?:bom|bakar) (?:kedai|pejabat|rumah) (?:kau|awak|korang)\b"),
    ("threat.zh", THREAT, r"我要杀了你|我会杀了你|杀你全家|弄死你"),

    ("self_harm.en", SELF_HARM,
     r"\b(?:kill(?:ing)? my ?self|end(?:ing)? my (?:own )?life|take my (?:own )?life|suicidal|commit(?:ting)? suicide"
     r"|(?:don't|dont|do not) want to (?:live|be alive) anymore"
     # "i want to die" but not "i don't want to die from this", which a clinic hears daily.
     r"|i (?:just |really )?(?:want to|wanna) die)\b"),
    ("self_harm.ms", SELF_HARM, r"\bbunuh diri\b|\b(?:tak|tidak) (?:nak|mahu|ingin) hidup lagi\b"),
    ("self_harm.zh", SELF_HARM, r"自杀|不想活了|我想死|轻生|结束(?:我的|自己的)?生命"),
)
_COMPILED = tuple((rule, category, re.compile(pattern)) for rule, category, pattern in _RULES)

# Rules an industry may discuss, keyed by industry template id. Never add a rule here from
# NEVER_ALLOWED: check_text refuses to release those whatever this table says.
ALLOW_LIST = {
    "clinic": frozenset({"drugs.medicine"}),
    "dental_clinic": frozenset({"drugs.medicine"}),
}
NEVER_ALLOWED = frozenset({CHILD_SEXUAL, MALWARE_SCAM, THREAT, SELF_HARM})
_ALLOWABLE_RULES = frozenset().union(*ALLOW_LIST.values())

# Format (Cf) and combining (Mn) characters render as nothing, so they would split a phrase unseen.
_HIDDEN_CATEGORIES = frozenset({"Cf", "Mn"})
_SEPARATORS = re.compile(r"[-_.]+")
_SPACES = re.compile(r"\s+")
# Chinese has no spaces between words, so one typed space must not break a phrase.
_CJK_GAP = re.compile(r"(?<=[㐀-鿿]) (?=[㐀-鿿])")


@dataclass(frozen=True)
class ContentFlag:
    category: str
    rule: str

    @property
    def is_self_harm(self):
        return self.category == SELF_HARM


def _normalize(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = "".join(char for char in text if unicodedata.category(char) not in _HIDDEN_CATEGORIES)
    text = _SEPARATORS.sub(" ", text.replace("’", "'").replace("‘", "'"))
    return _CJK_GAP.sub("", _SPACES.sub(" ", text)).casefold()


def check_text(text, industry=None, *, include_self_harm=True):
    """Return the first ContentFlag the text trips, or None when it may go to an AI."""
    normalized = _normalize(text)
    if not normalized:
        return None
    allowed = ALLOW_LIST.get(industry or "", frozenset())
    for rule, category, pattern in _COMPILED:
        if category == SELF_HARM and not include_self_harm:
            continue
        if rule in allowed and category not in NEVER_ALLOWED:
            continue
        if pattern.search(normalized):
            return ContentFlag(category, rule)
    return None


def industry_for_bot(chatbot_id):
    """The bot's published industry template id, or None."""
    from app.services.rag_service import get_deployed_settings

    published = get_deployed_settings(chatbot_id).get("industry_template_published") or {}
    return published.get("template_id") if isinstance(published, dict) else None


def check_bot_text(text, chatbot_id, *, include_self_harm=True):
    """check_text with the bot's industry allow list, read only when an allow-listed rule matched."""
    flag = check_text(text, include_self_harm=include_self_harm)
    if flag is None or flag.rule not in _ALLOWABLE_RULES:
        return flag
    return check_text(text, industry_for_bot(chatbot_id), include_self_harm=include_self_harm)


_CARD = re.compile(r"(?<![\d+])\d(?:[ -]?\d){12,18}(?!\d)")
_IC_SPLIT = re.compile(r"(?<![\d+])\d{6}[ -]\d{2}[ -]\d{4}(?!\d)")
_IC_PLAIN = re.compile(r"(?<![\d+])\d{12}(?!\d)")
IC_HIDDEN = "[IC number hidden]"
CARD_HIDDEN = "[card number hidden]"


def _passes_luhn(digits):
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def _hide_card(match):
    digits = re.sub(r"\D", "", match.group())
    return CARD_HIDDEN if _passes_luhn(digits) else match.group()


def _hide_plain_ic(match):
    digits = match.group()
    month, day = int(digits[2:4]), int(digits[4:6])
    # shortcut: 12 digits starting "601" are read as a +60 1x mobile number, so ICs of people born
    # Oct-Dec 1960 typed without dashes stay visible; add a place-of-birth code check if that matters.
    if digits.startswith("601") or not (1 <= month <= 12 and 1 <= day <= 31):
        return digits
    return IC_HIDDEN


def hide_sensitive_numbers(text):
    """Replace MyKad (IC) and payment card numbers before text goes to an AI."""
    if not text:
        return text
    text = _CARD.sub(_hide_card, text)
    text = _IC_SPLIT.sub(IC_HIDDEN, text)
    return _IC_PLAIN.sub(_hide_plain_ic, text)


def clean_history(history, chatbot_id=None):
    """A new history without flagged messages, with IC and card numbers hidden in the rest.

    With a chatbot_id, that bot's industry allow list applies, as it does to new messages.
    """
    return [
        {**row, "content": hide_sensitive_numbers(row.get("content") or "")}
        for row in history
        if (check_bot_text(row.get("content"), chatbot_id) if chatbot_id else check_text(row.get("content"))) is None
    ]
