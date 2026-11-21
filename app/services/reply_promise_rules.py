"""Lexical Section C checks. Only retrieved policy text can support an offer."""

import re
import unicodedata


_SENTENCE = re.compile(r"(?:[^.!?。！？;\n；]|(?<=\d)\.(?=\d))+(?:[?？]+|$)?")
_HAN_LATIN_BOUNDARY = re.compile(r"(?<=[\u3400-\u9fff])(?=[a-z])|(?<=[a-z])(?=[\u3400-\u9fff])")
_CONTRAST = re.compile(r"\s*(?:,\s*)?\b(?:but|however|tetapi|tapi)\b\s*|[，,]?(?:但是?|不过|不過)")
_HYPOTHETICAL = re.compile(r"\b(?:if|jika|kalau)\b|如果|假如")
_CLAUSE_BREAK = re.compile(r",|\b(?:and|dan)\s+(?=(?:do|does|did|we|i|kami|saya|staf|tidak|tak)\b)")
_QUESTION_START = re.compile(
    r"^(?:can|could|would|do|does|did|is|are|will|what|which|who|when|where|how|why"
    r"|adakah|bolehkah|apakah|bagaimana)\b|^(?:请问|請問|是否|能否)"
)
_NON_ASSERTION = re.compile(
    r"(?P<negation>\b(?:cannot|can['’]t|won['’]t|no(?![- ]cost\b)|not|never|unable to"
    # 不另收费 / 没有额外收费 / 无需付费 deny a fee, which strengthens a free or guaranteed offer.
    r"|tidak|tak|bukan|belum)\b|[不没沒无無](?!有?(?:另|额外|額外)|收|需(?:付|额外|額外))|并非|未必)"
    r"|\b(?:whether|sama ada|mungkin)\b|是否|能否|可能|也[许許]|[吗嗎]\s*$"
    r"|\b(?:may|might|could) (?:be|offer|provide|get|receive|qualify|apply|have|include)\b"
    r"|\b(?:needs? to|will|must|perlu|akan) (?:confirm|check|verify|semak|sahkan|disahkan|disemak)\b"
    r"|\bneeds? to be (?:confirmed|checked|verified)\b|需(?:要)?(?:确认|確認|核实|核實|查证|查證)"
    r"|\b(?:ask|apply|request|check|mohon|memohon|semak)\b.{0,24}"
    r"(?:refund|bayaran balik|discount|guarantee|free)|(?:申请|询问|核实)(?:全额)?退款"
    r"|^(?:can (?:i|we|you)|would you|do you|is (?:it|there)|adakah|bolehkah)\b"
)
_EXPLICIT_COMMITMENT = re.compile(r"\b(?:(?:we|i) (?:guarantee|promise)|(?:kami|saya) (?:men)?jamin)\b"
                                  r"|(?:我们|我們|我方|我)(?:保证|保證)")
_CERTAIN = re.compile(
    r"\b(?:guarantee[ds]?|guaranteeing|(?:we|i) promise|certain to|confirm(?:ed)? (?:pass|approved)"
    r"|pasti|dijamin|menjamin|jamin|mesti)\b|100\s*%(?!\s*(?:of|cotton|wool|silk|linen|pure|natural|kapas)\b)"
    r"|一定|保证|保證"
)
_BENEFITS = (
    ("refund", re.compile(r"\b(?:full refund|refund (?:your |the )?(?:entire|whole)|"
                          r"(?:will|we'll|we’ll) refund|refund (?:is|was|has been) approved|"
                          r"bayaran balik penuh)\b|全[额額]退款")),
    ("discount", re.compile(r"\b(?:half[- ]price|(?:get|give|receive|dapat|beri|offer)(?: you)? (?:a )?discount"
                            r"|discount of)\b|\d+(?:\.\d+)?\s*%\s*(?:off|discount)\b"
                            r"|打[一二三四五六七八九\d.]+折|(?:给你|享受|享有)折扣")),
    ("free_item", re.compile(r"(?<!feel )(?<!-)\bfree\b(?![- ](?:from|of (?!charge)|to\b))"
                             r"|\bpercuma\b|免[费費]")),
)
_OUTCOMES = (
    ("medical", re.compile(r"\b(?:cur(?:e[ds]?|ing)|heal(?:ed)?|recover|sembuh)\b|治好|治愈|痊愈")),
    ("legal", re.compile(r"\b(?:lawsuit|court|win (?:your |the )?case|mahkamah)\b|胜诉|勝訴|打赢官司")),
    ("financial", re.compile(r"\b(?:savings|returns?|loan|investment|claim|pinjaman|pelaburan)\b|贷款|回报|理赔")),
    ("timing", re.compile(r"\b(?:deliver(?:y|ed)?|arriv(?:e|al)|appointment|rider|hantar|sampai|temu janji)\b"
                          r"|送达|送到|到货|预约")),
)


_ELIGIBILITY = re.compile(r"^(?:only\b|limited to\b|minimum\b|valid (?:for|until)\b|"
                          r"hanya\b|terhad\b|仅限|只限|仅适用)")
_POLICY_INTRO = re.compile(r"^(?:(?:our|the published) policy (?:says|states)|according to our policy)[:,]?\s*")


def _assertions(text):
    pending = ""
    normalized = _HAN_LATIN_BOUNDARY.sub(" ", unicodedata.normalize("NFKC", text).casefold())
    for match in _SENTENCE.finditer(normalized):
        sentence = match.group().strip()
        if pending and _ELIGIBILITY.match(sentence) and not sentence.endswith("?"):
            pending += " " + sentence
            continue
        if pending:
            yield pending
            pending = ""
        if sentence.endswith("?"):
            # A separate follow-up question doesn't retract a preceding assertion.
            statement, comma, question = sentence.rpartition(",")
            if (not comma or _QUESTION_START.match(sentence) or
                    not (_QUESTION_START.match(question.strip()) or question.rstrip("?").endswith(("吗", "嗎")))):
                continue
            sentence = statement
        for clause in _CONTRAST.split(sentence):
            if pending:
                yield pending
            pending = _POLICY_INTRO.sub("", clause.strip()).strip(" \"'“”‘’")
    if pending:
        yield pending


def _kinds(clause):
    # Keep the complete clause for grounding, but scope a refusal to its own
    # assertion ("full refund, no questions asked" still promises a refund).
    if not (_NON_ASSERTION.search(clause) or _HYPOTHETICAL.search(clause)):
        return _positive_kinds(clause)
    kinds = []
    for part in _CLAUSE_BREAK.split(clause):
        assertion = _HYPOTHETICAL.split(part, maxsplit=1)[0]
        modifier = _NON_ASSERTION.search(assertion)
        if modifier:
            # "We guarantee you won't lose" still commits to an outcome.
            assertion = assertion[:modifier.start()]
            if modifier.lastgroup != "negation" or not _EXPLICIT_COMMITMENT.search(assertion):
                continue
        kinds.extend(_positive_kinds(assertion))
    return kinds


def _positive_kinds(clause):
    benefits = [kind for kind, pattern in _BENEFITS if pattern.search(clause)]
    if benefits or not _CERTAIN.search(clause):
        return benefits
    return [next((kind for kind, pattern in _OUTCOMES if pattern.search(clause)), "guarantee")]


# Common offer wording can change order across English and Malay. Retain item,
# quantity and eligibility terms and compare conditions separately from benefits.
_CONDITION = re.compile(r"\b(?:if|when|kalau|jika|for|untuk|on orders|provided that)\b")
_ATTRIBUTED_OFFER = re.compile(r"^(?:(?:the \w+|we) (?:guarantee[sd]?|offers?) |(?:refund|discount) policy:\s*)")
_FILLER = re.compile(r"\b(?:the|a|an|is|are|we|you|our|offer|offers|get|will|"
                     r"memang|kami|hanya|yang|it|comes)\b")
_MALAY_TERMS = {"percuma": "free", "baru": "newly", "dipasang": "fitted", "longgar": "loose"}
_ALIASES = {**_MALAY_TERMS, "shipping": "delivery", "above": "over", "below": "under"}
_CONDITION_ALIAS = re.compile(r"\b(?:" + "|".join(_MALAY_TERMS) + r")\b")
_RESTRICTION = re.compile(r"only|first|new|last|minimum|maximum|over|under|before|after|except|excluding|"
                          r"members?|customers?|orders?|warranty|unopened|unused|original|eligible|premium")


def _terms(text):
    text = _FILLER.sub(" ", _ATTRIBUTED_OFFER.sub("", text))
    return {_ALIASES.get(word, word) for word in re.findall(r"[\w%-]+", text)}


def _supported(claim, kind, policies):
    for policy in policies:
        if claim == policy:
            return True
        if kind not in {"free_item", "refund", "discount"} or kind not in _kinds(policy):
            continue
        item, *condition = _CONDITION.split(claim, maxsplit=1)
        source_item, *source_condition = _CONDITION.split(policy, maxsplit=1)
        if _terms(item) != _terms(source_item) or bool(condition) != bool(source_condition):
            continue
        if not condition:
            return True
        stated, published = _terms(condition[0]), _terms(source_condition[0])
        if stated == published:
            return True
        # In a bilingual paraphrase, allow one untranslated noun modifier when
        # the offer and at least four condition terms (including the noun) agree.
        extra = published - stated
        if len(stated) >= 4 and stated < published and len(extra) == 1 and _CONDITION_ALIAS.search(condition[0]):
            modifier = next(iter(extra))
            if re.fullmatch("[a-z]+", modifier) and not _RESTRICTION.fullmatch(modifier):
                return True
    return False


def promise_findings(reply, knowledge):
    claims = [(clause, kind) for clause in _assertions(reply) for kind in _kinds(clause)]
    if not claims:
        return []
    policies = [clause for chunk in knowledge for clause in _assertions(chunk)]
    missing = dict.fromkeys(kind for clause, kind in claims if not _supported(clause, kind, policies))
    return [{"category": "promise", "subtype": kind} for kind in missing]
