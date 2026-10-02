"""Decide whether a customer explicitly asked for a human, without a model.

The escalation path must stay open when the model, the knowledge base or an
MCP server is down, so this is pure text matching over a fixed phrase table --
no network call, no provider, no billing. `agent_decision_service` already
classifies intent by regex, but it matches a bare keyword list, so
"don't transfer me to a human" and "do you even have human agents?" both come
back as `handoff_request`. This module is the part that has to be right: a
false request pulls staff into a conversation nobody asked to escalate, and a
missed one strands a customer who did ask.

Six rules separate a request from a keyword:

1. **Clause scope.** A negator counts only inside the clause its phrase sits
   in, looking both sides of the phrase. "I am not happy, please talk to a
   human" is a request; "please don't talk to a human" and "talk to a human
   is not what I want" are refusals. A newline ends a clause, because a
   multi-line message is two thoughts, not one long one.
2. **Word boundaries.** Negators and question markers match as words, never as
   substrings. This is not pedantry: `"not" in "another"` is True, so a naive
   check turns "I want another human agent" into a refusal and silently denies
   a customer the help they asked for. The same trap sits in `ada`/`kepada`,
   `any`/`company`, and the single character 别 inside 特别 and 识别.
3. **Real quotes only.** An apostrophe between two letters is a contraction,
   not a quotation mark -- otherwise "I can't wait, please talk to a human,
   it's urgent" reads as one quoted span and swallows the request inside it.
4. **Questions scan the whole lead-in.** "do you have a human agent?" is the
   same question as "do you have human agents?"; one article must not turn a
   question into an escalation.
5. **Last decisive wins.** A message may hold several phrases. The last one
   that clearly asks or clearly refuses is the customer's actual intent, so
   "don't transfer me to a bot, please talk to a human" is a request and
   "talk to a human -- actually no need" is not.
6. **Bare nouns need an ask.** "customer service" is a request when it is the
   whole message and a topic when it is not, so "thanks for the great customer
   service" does not page anyone.

Anything the rules cannot settle returns AMBIGUOUS. The caller offers a fixed
clarification button for that; it never guesses, and it never asks a model to
break the tie. Chinese, English and Malay are covered because those are the
languages the deployed bots answer in.
"""

import re
from dataclasses import dataclass


REQUESTED = "requested"
DECLINED = "declined"
AMBIGUOUS = "ambiguous"
NONE = "none"

# Phrases that carry their own verb: wanting one of these IS the request.
_ACTION_PHRASES = {
    "en": (
        "talk to a human", "talk to human", "speak to a human", "speak to human",
        "talk to a person", "speak to a person", "talk to a real person",
        "speak to a real person", "talk to an agent", "speak to an agent",
        "talk to someone", "speak to someone", "talk to staff", "speak to staff",
        "transfer me", "connect me", "put me through", "escalate this",
    ),
    "zh": (
        "转人工", "转接人工", "接人工", "要人工", "找人工", "叫人工", "换人工",
        "找客服", "转客服", "转给客服", "联系客服", "转真人",
    ),
    "ms": (
        "bercakap dengan staf", "cakap dengan staf", "bercakap dengan manusia",
        "cakap dengan manusia", "bercakap dengan orang", "cakap dengan orang",
        "hubungkan saya", "pindahkan saya", "pindah kepada staf",
        "nak jumpa staf", "mahu bercakap dengan staf",
    ),
}

# Noun phrases. On their own they are a request ("customer service" typed into
# a chat means one thing); buried in a sentence they are just a topic.
_NOUN_PHRASES = {
    "en": (
        "real person", "human agent", "human agents", "live agent", "live person",
        "human support", "customer service", "customer support",
    ),
    "zh": ("人工客服", "真人客服", "真人服务"),
    "ms": ("khidmat pelanggan", "servis pelanggan", "staf manusia", "ejen manusia"),
}

# Matched as whole words. "not" must never fire inside "another" or "cannot".
_WORD_NEGATORS = (
    "don't", "dont", "do not", "won't", "wont", "no need", "not", "never",
    "rather not", "no thanks", "instead of", "without",
    "jangan", "tak perlu", "tidak perlu", "tak nak", "tidak mahu", "bukan",
)

# Chinese has no word boundaries, so these match as substrings. Every entry is
# two characters or more, which is what keeps them from colliding.
_CJK_NEGATORS = ("不要", "不用", "不想", "不需要", "无需", "毋须", "不必", "没有要")

# Characters that may sit between a Chinese negator and the phrase without
# breaking the negation -- adverbs, modals and particles, never a noun or a
# content verb. 不要再转人工 still refuses; 不要机器人要人工 refuses the ROBOT
# and asks for a human. Without this the two are indistinguishable, and
# 要人工不要机器人 (already correct) would disagree with its own reversal.
_CJK_NEGATOR_BRIDGE = frozenset("再又还也就想要能会可以需请麻烦的了吧啊呢 ")

# 别 is a single character negator ("don't"), but it is also the second half
# of many ordinary words. It therefore only counts immediately before the
# phrase AND only when it is not closing one of those words.
# ponytail: a hand-listed set of compounds, not word segmentation. Proper
# segmentation (jieba or equivalent) is the upgrade path if this list starts
# growing; until then a miss here costs one clarification button, not a
# wrongly refused customer.
_CJK_ADJACENT_NEGATORS = ("别",)
_CJK_NEGATOR_COMPOUNDS = (
    "特别", "识别", "分别", "区别", "个别", "差别", "性别", "告别", "级别",
    "类别", "派别", "送别", "离别", "鉴别", "辨别", "分辨别",
)

# Explicit pairs only. A bare "said" or "说" is too common to treat as a quote.
_REPORTED_SPEECH = (
    "you said", "u said", "it said", "he said", "she said", "they said",
    "the bot said", "bot said", "system said", "you told me", "you mentioned",
    "你说", "他说", "她说", "它说", "机器人说", "系统说", "你刚才说",
    "kata awak", "kata dia", "awak kata", "dia kata",
)

# Existence questions: the customer wants to know whether staff exist.
_WORD_INQUIRY = (
    "do you have", "do u have", "does it have", "is there", "are there",
    "got any", "just asking", "just checking", "just wondering",
    "ada", "adakah", "cuma tanya", "sekadar bertanya", "nak tanya",
)
_CJK_INQUIRY = ("只是问", "只是想问", "想问一下", "请问有没有", "有没有", "是否有")

# A noun phrase is a topic rather than an ask when it is the subject of a
# statement ("customer service IS excellent") or sits inside praise or a
# complaint. Everything else -- "I want another human agent" -- is a request.
_EVALUATION_WORDS = (
    "thanks", "thank", "great", "excellent", "good", "bad", "terrible", "poor",
    "awful", "amazing", "love", "hate", "appreciate", "worst", "best",
    "terima kasih", "bagus", "teruk", "hebat",
)
_EVALUATION_CJK = ("谢谢", "感谢", "多谢", "很好", "不错", "很差", "糟糕")

# An explicit first-person ask outranks praise or complaint in the same
# clause. The customers most likely to need a human are exactly the ones
# typing complaint words, so "your support is terrible, I want a human agent"
# must stay a request.
_EXPLICIT_ASK_WORDS = (
    "i want", "i need", "i'd like", "i would like", "can i", "could i",
    "please", "give me", "get me", "saya nak", "saya mahu", "tolong",
)
_EXPLICIT_ASK_CJK = ("我要", "我想", "请", "麻烦")

# Withdrawing a request is its own small vocabulary, deliberately NOT "any
# negator in a later clause". A retraction stands alone ("actually no need");
# a contrast names the alternative ("...a human, not a bot") and is still a
# request. Reading the second as the first is how you strand a customer who
# asked as clearly as they know how.
_RETRACTION_WORDS = (
    "no need", "never mind", "nevermind", "forget it", "forget that",
    "cancel that", "no thanks", "don't bother", "dont bother", "all good",
    "it's fine", "its fine", "sorted now", "tak payah", "tak jadi",
)
_RETRACTION_CJK = ("不用了", "算了", "不需要了", "没事了", "不必了", "不用麻烦")

# What may sit on either side of a retraction and still leave it standing
# alone. Both sides matter and each has been a bug: a complement on the right
# means the customer withdrew that rather than the request, and a subject on
# the left means they are reporting something else as settled.
_RETRACTION_TRIM = " .!?,;:。！？，、…-'\""
_RETRACTION_LEADIN_FILLER = frozenset((
    "", "actually", "ok", "okay", "so", "but", "anyway", "oh", "um", "erm",
    "hmm", "well", "and", "then", "sorry", "wait", "哦", "那", "好", "嗯",
))

# What may follow a retraction and still leave it standing alone. Anything
# else is a complement, and a retraction with a complement withdraws that
# complement, not the request: "no need TO RUSH" is a polite customer still
# waiting for a human, and declining them makes them unreachable.
_RETRACTION_TAIL_FILLER = frozenset((
    "", "now", "then", "already", "thanks", "thank you", "ok", "okay",
    "la", "lah", "ya", "yeah", "anyway", "谢谢", "了",
))

# Newlines are absent here on purpose: _normalise turns them into spaces and
# reports their positions separately, so a line break still ends a clause
# without breaking a phrase that was typed across two lines.
_CLAUSE_BOUNDARIES = ",.;:!?，。；：！？、"
# Straight and curly apostrophes double as quote marks, so a candidate only
# opens a quotation when it is not sitting between two letters.
_QUOTE_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
)


def _word_pattern(terms):
    """Match any term as a whole word, apostrophes and spaces included."""
    alternatives = "|".join(
        re.escape(term) for term in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


_NEGATOR_RE = _word_pattern(_WORD_NEGATORS)
_INQUIRY_RE = _word_pattern(_WORD_INQUIRY)
_EVALUATION_RE = _word_pattern(_EVALUATION_WORDS)
_EXPLICIT_ASK_RE = _word_pattern(_EXPLICIT_ASK_WORDS)
_COPULA_RE = re.compile(
    r"^\s*(?:isn't|aren't|wasn't|weren't|is|are|was|were|has|have|had"
    r"|seems?|looks?)(?!\w)")
# These carry the negation inside the contraction, so the trailer needs no
# separate negator word: "talk to a human ISN'T what I want".
_NEGATIVE_COPULAS = frozenset(("isn't", "aren't", "wasn't", "weren't"))
_RETRACTION_RE = _word_pattern(_RETRACTION_WORDS)
_WHITESPACE_RUN_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class HandoffRequestSignal:
    """What the customer's own words support -- never what a model inferred."""

    decision: str
    matched_phrase: str = ""
    language: str = ""
    reason: str = ""

    @property
    def is_explicit_request(self):
        return self.decision == REQUESTED

    @property
    def needs_clarification(self):
        return self.decision == AMBIGUOUS


def _normalise(message):
    """Collapse whitespace to single spaces, remembering where lines broke.

    Two things have to be true at once. A line break separates two thoughts,
    so it must end a clause -- otherwise "I don't like this bot\\nplease talk
    to a human" reads as one clause and the negator declines a plain request.
    But a phrase typed across two lines is still that phrase, so the break
    must not break matching. Collapsing it to a space and recording the index
    gives both; returns the text and the break positions within it.
    """
    stripped = message.strip()
    breaks = set()
    text = ""
    position = 0
    for run in _WHITESPACE_RUN_RE.finditer(stripped):
        text += stripped[position:run.start()]
        if any(character in "\n\r" for character in run.group(0)):
            breaks.add(len(text))
        text += " "
        position = run.end()
    text += stripped[position:]
    return text, frozenset(breaks)


def _quoted_spans(text):
    """Ranges inside real quotation marks, ignoring in-word apostrophes."""
    spans = []
    for opener, closer in _QUOTE_PAIRS:
        index = 0
        while True:
            start = text.find(opener, index)
            if start < 0:
                break
            if _is_contraction(text, start):
                index = start + 1
                continue
            end = text.find(closer, start + 1)
            while end >= 0 and _is_contraction(text, end):
                end = text.find(closer, end + 1)
            if end < 0:
                break
            spans.append((start, end))
            index = end + 1
    return spans


def _is_contraction(text, position):
    """An apostrophe with a letter on both sides belongs to a word."""
    return (0 < position < len(text) - 1
            and text[position - 1].isalnum() and text[position + 1].isalnum())


def _clause_around(text, start, end, breaks):
    """The whole clause the phrase sits in, both sides of it.

    Reading only the lead-in would miss "talk to a human is not what I want",
    which is a refusal written the other way round.
    """
    before = max(
        [text.rfind(mark, 0, start) for mark in _CLAUSE_BOUNDARIES]
        + [position for position in breaks if position < start],
        default=-1,
    )
    after = min(
        [position for position in
         (text.find(mark, end) for mark in _CLAUSE_BOUNDARIES) if position >= 0]
        + [position for position in breaks if position >= end],
        default=len(text),
    )
    return text[before + 1:start], text[end:after], after


def _all_matches(lowered):
    """Every phrase occurrence, in the order the customer typed them."""
    found = []
    for table, is_noun in ((_ACTION_PHRASES, False), (_NOUN_PHRASES, True)):
        for language, phrases in table.items():
            for phrase in phrases:
                start = lowered.find(phrase)
                while start >= 0:
                    found.append((start, phrase, language, is_noun))
                    start = lowered.find(phrase, start + 1)
    # Longest phrase first at a shared offset, so the most specific entry wins
    # and the language label stays right.
    found.sort(key=lambda item: (item[0], -len(item[1])))
    return found


def _negates_the_request(lead_in, trailer):
    """Whether a negator in this clause negates the request itself.

    Before the phrase, a negator negates it: "don't talk to a human". After
    it, a negator almost always contrasts a noun instead -- "a human not a
    bot" is the most emphatic way a customer can ask FOR a human, and reading
    that as a refusal strands exactly the person who needed help most. A
    trailing negator therefore only counts when a copula has made the phrase
    the subject: "talk to a human IS NOT what I want".

    Chinese is checked in the lead-in only, for the same reason and with no
    copula to lean on: 要人工不要机器人 ("I want a human, not a robot") must
    not read as a refusal. A withdrawal in a later clause is caught by
    `_retraction_follows` instead.
    """
    if _NEGATOR_RE.search(lead_in) or _cjk_negator_binds(lead_in):
        return True
    # The copula must open the trailer, not merely appear somewhere in it.
    # "talk to a human IS NOT what I want" makes the phrase the subject;
    # "talk to a human the bot is not helping" introduces a new subject, and
    # the complaint about the bot is the customer's reason for wanting one.
    copula = _COPULA_RE.match(trailer)
    if copula is None:
        return False
    if copula.group(0).strip() in _NEGATIVE_COPULAS:
        return True
    return _NEGATOR_RE.search(trailer) is not None


def _cjk_negator_binds(lead_in):
    """Whether a Chinese negator in the lead-in negates the phrase itself.

    不要转人工 refuses a handoff. 不要机器人要人工 refuses the ROBOT and then
    asks for a human -- the same four words as 要人工不要机器人, which already
    resolves correctly, so clause order alone must not flip the answer. The
    discriminator is what sits between them: adverbs and particles carry the
    negation across, a noun or a content verb gives it a different object.

    ponytail: adjacency plus a bridge set, not parsing. The Latin side has the
    same gap ("I don't want a bot talk to a human") and is deliberately left
    alone -- there is no equivalent passing case to check a fix against, and
    every speculative fix in this module has so far opened a defect in the
    mirror position.
    """
    for negator in _CJK_NEGATORS:
        position = lead_in.rfind(negator)
        if position < 0:
            continue
        bridge = lead_in[position + len(negator):]
        if all(character in _CJK_NEGATOR_BRIDGE for character in bridge):
            return True
    return False


def _retraction_follows(lowered, clause_end, match_starts):
    """A later clause that withdraws the ask, using retraction words only.

    "talk to a human, actually no need" holds no second phrase, so nothing
    downstream would ever reconsider it; staff get paged after the customer
    stood them down. Scanning for any negator instead would catch
    "...a human, not a bot", which is the opposite of a withdrawal, so only
    the explicit retraction vocabulary counts here.
    """
    tail = lowered[clause_end:]
    if not tail.strip() or any(start >= clause_end for start in match_starts):
        return False
    match = _RETRACTION_RE.search(tail)
    if match is not None and _is_bare_retraction(tail, match.start(), match.end()):
        return True
    for marker in _RETRACTION_CJK:
        position = tail.find(marker)
        if position >= 0 and _is_bare_retraction(tail, position, position + len(marker)):
            return True
    return False


def _is_bare_retraction(tail, start, end):
    """A real retraction has no subject and no object of its own.

    Both sides have to be checked, and each has already been a bug. To the
    right, a complement means the customer withdrew that and not the request:
    "no need TO RUSH" is a polite customer still waiting. To the left, a
    subject means they are reporting something else as settled -- "the payment
    IS all good" -- or quoting the bot back at us -- "the bot said no need".
    Neither withdraws the ask, and declining them makes the customer
    unreachable.
    """
    boundary = max(
        (tail.rfind(mark, 0, start) for mark in _CLAUSE_BOUNDARIES), default=-1)
    lead_in = tail[boundary + 1:start].strip(_RETRACTION_TRIM)
    if lead_in.lower() not in _RETRACTION_LEADIN_FILLER:
        return False
    return tail[end:].strip(_RETRACTION_TRIM).lower() in _RETRACTION_TAIL_FILLER


def _is_topic_mention(lead_in, trailer):
    """True when a noun phrase names a service instead of asking for one.

    Two signals, both cheap and both specific. A copula straight after the
    phrase makes it the subject of a statement ("customer service IS
    excellent"), and praise or a complaint anywhere in the clause means the
    customer is talking ABOUT the service. Anything else -- "I want another
    human agent", "tolong hantar saya kepada staf manusia" -- is an ask, so
    the default for a noun phrase stays REQUESTED.
    """
    # An explicit ask settles it. "your support is terrible, I want a human
    # agent" is a request from the customer most likely to need one, and
    # downgrading it to a clarification button makes them ask twice.
    if _EXPLICIT_ASK_RE.search(lead_in) or any(
            marker in lead_in for marker in _EXPLICIT_ASK_CJK):
        return False
    if _COPULA_RE.match(trailer):
        return True
    clause = lead_in + " " + trailer
    return bool(_EVALUATION_RE.search(clause)) or any(
        marker in clause for marker in _EVALUATION_CJK)


def _classify(lowered, quoted, breaks, start, phrase, is_noun):
    end = start + len(phrase)

    if any(open_at < start and end <= close_at for open_at, close_at in quoted):
        return AMBIGUOUS, "The phrase is quoted, so it is not this customer's own request.", end

    lead_in, trailer, clause_end = _clause_around(lowered, start, end, breaks)

    for marker in _REPORTED_SPEECH:
        if marker in lead_in:
            return AMBIGUOUS, "The phrase is reported speech, not a request.", clause_end

    if _negates_the_request(lead_in, trailer):
        return DECLINED, "The customer declined a human handoff.", clause_end
    trimmed_lead_in = lead_in.strip()
    if (trimmed_lead_in.endswith(_CJK_ADJACENT_NEGATORS)
            and not trimmed_lead_in.endswith(_CJK_NEGATOR_COMPOUNDS)):
        return DECLINED, "The customer declined a human handoff.", clause_end

    stripped_lead_in = lead_in.strip()
    if _INQUIRY_RE.search(stripped_lead_in) or stripped_lead_in.endswith(_CJK_INQUIRY):
        return AMBIGUOUS, "The customer asked whether staff exist, not to be transferred.", clause_end

    if is_noun and _is_topic_mention(lead_in, trailer):
        return AMBIGUOUS, "The phrase names a service rather than asking to be transferred.", clause_end

    return REQUESTED, "The customer explicitly asked for a human.", clause_end


def detect_explicit_handoff_request(message):
    """Classify a customer message as a human request without calling a model.

    Returns a HandoffRequestSignal. Only REQUESTED authorises an escalation;
    AMBIGUOUS means offer the fixed clarification button, and DECLINED means
    the customer said no and must not be escalated or asked again.
    """
    if not isinstance(message, str):
        return HandoffRequestSignal(NONE, reason="Message was not text.")

    text, breaks = _normalise(message)
    if not text:
        return HandoffRequestSignal(NONE, reason="Message was empty.")

    lowered = text.lower()
    matches = _all_matches(lowered)
    if not matches:
        return HandoffRequestSignal(NONE, reason="No explicit human-request phrase.")

    quoted = _quoted_spans(lowered)
    match_starts = [start for start, _, _, _ in matches]
    decisive = None
    decisive_clause_end = None
    fallback = None
    for start, phrase, language, is_noun in matches:
        decision, reason, clause_end = _classify(
            lowered, quoted, breaks, start, phrase, is_noun)
        if decision in (REQUESTED, DECLINED):
            decisive_clause_end = clause_end
            # Later statements supersede earlier ones, so both a correction
            # and a retraction land on the customer's final intent.
            decisive = HandoffRequestSignal(decision, phrase, language, reason)
        elif fallback is None:
            fallback = HandoffRequestSignal(decision, phrase, language, reason)

    if (decisive is not None and decisive.decision == REQUESTED
            and _retraction_follows(lowered, decisive_clause_end, match_starts)):
        decisive = HandoffRequestSignal(
            DECLINED, decisive.matched_phrase, decisive.language,
            "The customer withdrew the request in a later clause.")

    # Every classification returns one of the three non-NONE decisions, so a
    # match always produces a signal. The fallthrough exists so a future
    # classifier branch cannot silently hand callers a None to unpack.
    return decisive or fallback or HandoffRequestSignal(
        AMBIGUOUS, matches[0][1], matches[0][2],
        "A human-request phrase was found but could not be classified.")


def button_handoff_request(*, channel_supports_buttons=True):
    """A pressed handoff button is an explicit request; no text is parsed.

    Kept beside the parser so both entry points produce the same signal type
    and the caller has one code path into HandoffService.
    """
    if not channel_supports_buttons:
        return HandoffRequestSignal(
            NONE, reason="This channel cannot present a handoff button.")
    return HandoffRequestSignal(
        REQUESTED, "<button>", "", "The customer pressed the handoff button.")
