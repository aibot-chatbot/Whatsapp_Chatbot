"""What a staff reply must satisfy before it may leave the platform.

`channel_delivery_service` already answers "which connection owns this
conversation" and "did the provider accept the call". Two things it does not
answer, and that a human-handoff inbox cannot ship without:

* **May we send at all?** WhatsApp only allows free-form text inside the 24h
  customer-service window. Nothing in this repository checks that today, so a
  staff reply typed 30 hours after the customer's last message is handed to
  Meta and rejected there. A human typing it is not an exemption.
* **What actually happened to it?** `delivery_accepted()` returns a bool, and
  the transcript stores `sent` or `failed`. No channel in this repository
  parses a provider receipt -- there is no WhatsApp `statuses` handler -- so
  `delivered` and `read` are states we are not entitled to claim. The state
  machine below refuses to produce them without receipt evidence.

Everything here is a pure contract: no database, no provider call, no clock of
its own. The caller passes the timestamps and the provider's answer in.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import TypeGuard


# --- send eligibility -------------------------------------------------------

ALLOWED = "allowed"
BLOCKED = "blocked"
UNKNOWN = "unknown"
# A note is not "allowed to send" -- it is not sent at all. It needs its own
# verdict rather than ALLOWED, because a dispatcher written as
# `if eligibility.is_allowed: send(...)` would otherwise deliver staff-only
# text to the customer, and that text is where "escalate to legal" gets typed.
INTERNAL = "internal"

# WhatsApp Business Platform free-form reply window. Re-verify against the
# provider's current policy before HO-3 sign-off; this is the documented
# baseline, not proof of this account's approval state.
CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)

REPLY_TEXT = "reply_text"
REPLY_TEMPLATE = "reply_template"
INTERNAL_NOTE = "internal_note"
SYSTEM_NOTICE = "system_notice"

_OUTBOUND_KINDS = (REPLY_TEXT, REPLY_TEMPLATE, INTERNAL_NOTE, SYSTEM_NOTICE)


@dataclass(frozen=True)
class ChannelCapability:
    """What a channel can actually do, as verified in this repository.

    `verified` is false wherever the code path does not exist yet. An
    unverified channel never reaches ALLOWED -- it reaches UNKNOWN, and
    UNKNOWN is a refusal, not a default-open.
    """

    name: str
    supports_text: bool = False
    window: timedelta | None = None
    supports_template_outside_window: bool = False
    supports_delivery_receipt: bool = False
    supports_read_receipt: bool = False
    max_text_length: int = 4096
    verified: bool = False


# Facts taken from this repository, not from a vendor brochure. No channel
# here parses a receipt, so every supports_*_receipt stays False until an
# adapter actually reads one. Messenger has no adapter at all and is present
# only so it is refused by name rather than by accident.
CHANNEL_CAPABILITIES = {
    "whatsapp": ChannelCapability(
        "whatsapp", supports_text=True, window=CUSTOMER_SERVICE_WINDOW,
        supports_template_outside_window=True, max_text_length=4096,
        verified=True,
    ),
    "telegram": ChannelCapability(
        "telegram", supports_text=True, window=None, max_text_length=4096,
        verified=True,
    ),
    # Unofficial WhatsApp provider. It does not publish a window API and this
    # repository never reads one, so the platform window is applied anyway --
    # under-sending is recoverable, a silently dropped reply is not.
    "whatsapp_link": ChannelCapability(
        "whatsapp_link", supports_text=True, window=CUSTOMER_SERVICE_WINDOW,
        max_text_length=4096, verified=True,
    ),
    # The share-link conversation has no return channel: conversations.html
    # tells the merchant so in as many words. Staff text cannot reach them.
    "web": ChannelCapability("web", supports_text=False, verified=True),
    "messenger": ChannelCapability("messenger", verified=False),
}


@dataclass(frozen=True)
class SendEligibility:
    verdict: str
    code: str
    reason: str

    @property
    def is_allowed(self):
        """True only when this may be handed to a provider."""
        return self.verdict == ALLOWED

    @property
    def is_internal_only(self):
        """True when this must be stored and never transmitted."""
        return self.verdict == INTERNAL


def _blocked(code, reason):
    return SendEligibility(BLOCKED, code, reason)


def _unknown(code, reason):
    return SendEligibility(UNKNOWN, code, reason)


def evaluate_send_eligibility(
    *,
    channel,
    kind,
    now,
    last_customer_inbound_at=None,
    text_length=0,
    template_name=None,
):
    """Decide whether one outbound message may be handed to the provider.

    `last_customer_inbound_at` is the only clock that opens a window. A staff
    note, a system receipt or a provider callback must never be passed here:
    a reply window is reopened by the customer, and by nobody else.
    """
    if kind not in _OUTBOUND_KINDS:
        return _blocked("KIND_UNSUPPORTED", f"Unsupported outbound kind: {kind!r}.")

    # A note never leaves the platform, so channel state cannot block it --
    # but it is never "allowed" either. Callers gate storage on this verdict,
    # never on is_allowed.
    if kind == INTERNAL_NOTE:
        return SendEligibility(
            INTERNAL, "INTERNAL_ONLY",
            "An internal note is stored for staff and never delivered.")

    capability = CHANNEL_CAPABILITIES.get(channel)
    if capability is None:
        return _unknown("CHANNEL_UNKNOWN", f"No capability record for channel {channel!r}.")
    if not capability.verified:
        return _unknown(
            "CHANNEL_UNVERIFIED",
            f"The {channel} adapter is not implemented in this deployment.")
    if not capability.supports_text:
        return _blocked(
            "CHANNEL_NO_OUTBOUND",
            f"The {channel} conversation has no channel back to the customer.")

    if text_length <= 0:
        return _blocked("TEXT_EMPTY", "An outbound message needs text.")
    if text_length > capability.max_text_length:
        return _blocked(
            "TEXT_TOO_LONG",
            f"{text_length} characters exceeds the {channel} limit of "
            f"{capability.max_text_length}.")

    if capability.window is None:
        return SendEligibility(
            ALLOWED, "NO_WINDOW", f"{channel} does not enforce a reply window.")

    if kind == REPLY_TEMPLATE:
        if not capability.supports_template_outside_window:
            return _blocked(
                "TEMPLATE_UNSUPPORTED", f"{channel} has no approved template path.")
        # The template branch skips the window, so it must cost something to
        # enter. Without a named template, relabelling free text as
        # `reply_template` would be a complete bypass of the one control this
        # function exists to add. `kind` must be derived server-side from the
        # chosen template record, never read from a request body.
        if not isinstance(template_name, str) or not template_name.strip():
            return _blocked(
                "TEMPLATE_UNIDENTIFIED",
                "A template send needs the name of an approved template.")
        return SendEligibility(
            ALLOWED, "TEMPLATE",
            f"Approved template {template_name.strip()!r} may be sent outside the window.")

    if not isinstance(now, datetime) or now.tzinfo is None:
        return _unknown("CLOCK_UNKNOWN", "A timezone-aware current time is required.")
    if last_customer_inbound_at is None:
        return _unknown(
            "WINDOW_UNKNOWN",
            "No customer inbound timestamp is recorded, so the window cannot be proven open.")
    if not isinstance(last_customer_inbound_at, datetime) or last_customer_inbound_at.tzinfo is None:
        return _unknown(
            "WINDOW_UNKNOWN", "The customer inbound timestamp is not timezone-aware.")

    # A future-dated inbound timestamp is corrupt or spoofed. Honouring it
    # would invent window that the provider will not honour.
    if last_customer_inbound_at > now:
        return _unknown(
            "WINDOW_UNKNOWN",
            "The last customer message is timestamped in the future; the window is untrustworthy.")

    if now - last_customer_inbound_at > capability.window:
        return _blocked(
            "WINDOW_EXPIRED",
            "The customer-service window has closed. An approved template is required; "
            "a staff sender is not an exemption.")

    return SendEligibility(ALLOWED, "WINDOW_OPEN", "The customer-service window is open.")


# --- outbound command -------------------------------------------------------

@dataclass(frozen=True)
class OutboundCommand:
    """One staff-authored message, bound to the conversation that owns it.

    The recipient is not a parameter a caller may choose. It is read off the
    conversation's verified binding, so a forged request body cannot redirect
    a reply to another number, another company or another platform.
    """

    company_id: int
    chatbot_id: int
    conversation_id: int
    channel: str
    channel_connection_id: int
    recipient: str
    kind: str
    text: str
    actor_user_id: int
    idempotency_key: str
    control_version: int
    automation_epoch: int


class OutboundCommandError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _positive_int(value) -> TypeGuard[int]:
    """A real identifier. `bool` is an `int` subclass, so True must not pass."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def build_outbound_command(
    *,
    conversation,
    binding,
    kind,
    text,
    actor_user_id,
    idempotency_key,
    control,
):
    """Assemble a validated command, or refuse with a specific code.

    `binding` is the verified channel record that `get_bound_channel` already
    returns; `conversation` supplies the recipient. Nothing here accepts a
    recipient, a company or a connection id from request input, because that
    is how a reply ends up at someone else's number.
    """
    if kind not in _OUTBOUND_KINDS:
        raise OutboundCommandError("KIND_UNSUPPORTED", f"Unsupported outbound kind: {kind!r}.")
    if not isinstance(text, str) or not text.strip():
        raise OutboundCommandError("TEXT_EMPTY", "An outbound message needs text.")
    if not _positive_int(actor_user_id):
        raise OutboundCommandError("ACTOR_UNVERIFIED", "A verified staff user is required.")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise OutboundCommandError(
            "IDEMPOTENCY_KEY_MISSING", "A stable idempotency key is required.")

    conversation_id = conversation.get("id")
    chatbot_id = conversation.get("chatbot_id")
    channel = conversation.get("source_channel")
    if not _positive_int(conversation_id) or not _positive_int(chatbot_id):
        raise OutboundCommandError(
            "CONVERSATION_UNVERIFIED", "The conversation is not identified.")
    if control.conversation_id != conversation_id or control.chatbot_id != chatbot_id:
        raise OutboundCommandError(
            "CONTROL_MISMATCH", "The control record belongs to a different conversation.")

    # An internal note has no transport: it is deliberately built without a
    # connection or a recipient, so no later code path can hand it to a
    # provider even by mistake.
    if kind == INTERNAL_NOTE:
        return OutboundCommand(
            company_id=control.company_id, chatbot_id=chatbot_id,
            conversation_id=conversation_id, channel=channel,
            channel_connection_id=0, recipient="", kind=kind, text=text.strip(),
            actor_user_id=actor_user_id, idempotency_key=idempotency_key.strip(),
            control_version=control.version, automation_epoch=control.automation_epoch,
        )

    bound_connection = (binding or {}).get("id")
    if not _positive_int(bound_connection):
        raise OutboundCommandError(
            "CHANNEL_IDENTITY_UNVERIFIED", "The conversation's channel binding is unverified.")
    connection_id: int = bound_connection
    if (binding or {}).get("chatbot_id") != chatbot_id:
        raise OutboundCommandError(
            "CHANNEL_CROSS_TENANT", "The channel connection belongs to another chatbot.")

    recipient = conversation.get("platform_user_id") or conversation.get("customer_phone")
    if not recipient:
        raise OutboundCommandError("RECIPIENT_MISSING", "The conversation recipient is missing.")

    return OutboundCommand(
        company_id=control.company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, channel=channel,
        channel_connection_id=connection_id, recipient=str(recipient), kind=kind,
        text=text.strip(), actor_user_id=actor_user_id,
        idempotency_key=idempotency_key.strip(), control_version=control.version,
        automation_epoch=control.automation_epoch,
    )


def same_logical_message(first, second):
    """Two clicks of the same button are one message; a changed body is not.

    Raising on a reused key with different text is what stops a retry from
    quietly replacing what the customer was already told.
    """
    if first.idempotency_key != second.idempotency_key:
        return False
    # The tenant fields are part of the identity, not decoration. Without
    # them, a key collision between two companies reads as "duplicate" and
    # silently swallows the second tenant's message instead of raising.
    if (first.company_id, first.chatbot_id, first.conversation_id, first.channel,
            first.channel_connection_id, first.kind, first.text, first.recipient) != (
            second.company_id, second.chatbot_id, second.conversation_id, second.channel,
            second.channel_connection_id, second.kind, second.text, second.recipient):
        raise OutboundCommandError(
            "IDEMPOTENCY_KEY_CONFLICT",
            "This idempotency key was already used for a different message.")
    return True


# --- delivery result --------------------------------------------------------

QUEUED = "queued"
SENDING = "sending"
ACCEPTED = "accepted"
DELIVERED = "delivered"
READ = "read"
FAILED = "failed"
UNKNOWN_RESULT = "unknown"
SUPPRESSED = "suppressed"

# Forward-only. `accepted` means the provider took the call and nothing more.
# `unknown` is where a provider timeout lands: it may still resolve to any
# settled state, but nothing may fall back into an earlier one.
_TRANSITIONS = {
    QUEUED: {SENDING, SUPPRESSED, FAILED, UNKNOWN_RESULT},
    SENDING: {ACCEPTED, FAILED, UNKNOWN_RESULT},
    ACCEPTED: {DELIVERED, READ, FAILED, UNKNOWN_RESULT},
    DELIVERED: {READ},
    READ: set(),
    FAILED: set(),
    UNKNOWN_RESULT: {ACCEPTED, DELIVERED, READ, FAILED},
    SUPPRESSED: set(),
}


class DeliveryStateError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DeliveryResult:
    """The status of one logical message. Immutable; `advance` returns a copy."""

    idempotency_key: str
    channel: str
    status: str = QUEUED
    provider_message_id: str | None = None
    detail: str = ""
    history: tuple = field(default_factory=tuple)

    def advance(self, status, *, provider_message_id=None, detail="", receipt_verified=False):
        """Move to a later status, or refuse.

        `delivered` and `read` require `receipt_verified`, because no channel
        in this repository parses a provider receipt -- without one these
        states would be fiction shown to a merchant as fact. A repeated or
        out-of-order receipt is absorbed rather than rejected: providers
        resend, and a resend is not an error.
        """
        if status not in _TRANSITIONS:
            raise DeliveryStateError("STATUS_UNKNOWN", f"Unknown delivery status: {status!r}.")
        if status == self.status:
            return self
        if status in (DELIVERED, READ):
            if not receipt_verified:
                raise DeliveryStateError(
                    "RECEIPT_UNVERIFIED",
                    f"{status!r} requires a verified provider receipt; a send call is not proof.")
            # `receipt_verified` is the caller's word. The capability table is
            # this repository's own record of which adapters actually parse a
            # receipt, and today none of them do. Checking it is what stops a
            # merchant being shown "read" for a message nothing can prove
            # arrived. An unknown channel fails closed, like CHANNEL_UNKNOWN.
            capability = CHANNEL_CAPABILITIES.get(self.channel)
            supported = capability is not None and (
                capability.supports_read_receipt if status == READ
                else capability.supports_delivery_receipt)
            if not supported:
                raise DeliveryStateError(
                    "RECEIPT_UNSUPPORTED",
                    f"The {self.channel} adapter does not parse a {status!r} receipt, "
                    f"so that state cannot be claimed for it.")
        if status not in _TRANSITIONS[self.status]:
            # A late duplicate of a state already passed through is stale, not
            # a violation: keep the further-along status we already hold.
            if status in self.history:
                return self
            raise DeliveryStateError(
                "TRANSITION_INVALID", f"Cannot move from {self.status!r} to {status!r}.")
        return replace(
            self, status=status, detail=detail,
            provider_message_id=provider_message_id or self.provider_message_id,
            history=self.history + (self.status,),
        )

    @property
    def is_settled(self):
        return not _TRANSITIONS[self.status]

    @property
    def claims_delivery(self):
        return self.status in (DELIVERED, READ)


def suppressed_result(idempotency_key, channel, reason):
    """A message the platform refused to send. Never reported as delivered."""
    return DeliveryResult(idempotency_key, channel, SUPPRESSED, detail=reason,
                          history=(QUEUED,))


# --- staff notification events ---------------------------------------------

HUMAN_HANDOFF_REQUESTED = "human_handoff_requested"
CONVERSATION_ASSIGNED = "conversation_assigned"
CUSTOMER_MESSAGE_WAITING = "customer_message_waiting"

_EVENT_TYPES = (HUMAN_HANDOFF_REQUESTED, CONVERSATION_ASSIGNED, CUSTOMER_MESSAGE_WAITING)


@dataclass(frozen=True)
class HandoffNotificationEvent:
    """An in-app event. Delivering one proves nothing about staff attention.

    Deduplicated per tenant, conversation, takeover episode, event type and
    recipient, so a customer sending five messages while waiting does not
    become five pages for every member of staff.
    """

    company_id: int
    conversation_id: int
    episode_id: int
    event_type: str
    recipient_user_id: int

    def __post_init__(self):
        if self.event_type not in _EVENT_TYPES:
            raise ValueError(f"Unknown handoff notification event: {self.event_type!r}")
        # Annotations do not enforce anything at runtime, and dedupe_key is a
        # colon-joined string: a non-integer id lets two different events
        # collapse to one key, which drops a page and leaves a customer
        # waiting with nobody notified.
        for field_name in ("company_id", "conversation_id", "recipient_user_id"):
            if not _positive_int(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be a positive integer")
        # episode_id is 0 for a conversation that has never been escalated.
        if (not isinstance(self.episode_id, int) or isinstance(self.episode_id, bool)
                or self.episode_id < 0):
            raise ValueError("episode_id must be a non-negative integer")

    @property
    def dedupe_key(self):
        return (f"{self.company_id}:{self.conversation_id}:{self.episode_id}:"
                f"{self.event_type}:{self.recipient_user_id}")


def deduplicate_events(events, already_sent=()):
    """Keep the first event per dedupe key; drop repeats and already-sent keys."""
    seen = set(already_sent)
    kept = []
    for event in events:
        if event.dedupe_key in seen:
            continue
        seen.add(event.dedupe_key)
        kept.append(event)
    return kept


def utc_now():
    """One place for the caller's clock, so tests can pass their own."""
    return datetime.now(timezone.utc)
