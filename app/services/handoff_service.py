"""Who owns this conversation right now, and when the model may speak again.

Today the "handoff" is one derived boolean: `is_conversation_escalated()` is
true while an `agent_actions` row sits at `status='detected'`, re-asked by every
sender through `automatic_reply_allowed()`. Three consequences of that:

* **Resolving resumes the AI.** `agent_routes.resolve_agent_action` flips the
  row to resolved and the model answers again, in the same breath as a human
  closing the case: mode and resolution are one bit. Here they are two fields,
  and only `resume_ai()` may write `ai_active`.
* **Nobody owns the conversation.** The staff reply endpoint has no assignee
  check and saves staff text as `sender_type='bot'`, so two agents can answer
  the same customer and neither is accountable. An assignee, an optimistic
  `version` and an audited supervisor override are the smallest fix.
* **A queued task outlives the takeover.** The pause is re-read at send time,
  but a task dispatched earlier carries no proof of which era it belongs to.
  `automation_epoch` is that proof.

Pure domain: no Supabase client, no network, no clock, no table assumptions.
State arrives through a repository handed to the constructor, so HO-2 owns
persistence and the tests pass a fake. `HANDOFF_CONTROL_ENABLED` is OFF by
default, and while it is off nothing here may decide anything in production.
"""

import os
from dataclasses import dataclass, replace


# Mode answers "who is holding the conversation". Resolution answers "is the
# work finished". Collapsing them is the bug this file exists to prevent.
AI_ACTIVE = "ai_active"
WAITING_HUMAN = "waiting_human"
HUMAN_ACTIVE = "human_active"
_MODES = (AI_ACTIVE, WAITING_HUMAN, HUMAN_ACTIVE)

OPEN = "open"
RESOLVED = "resolved"
_RESOLUTIONS = (OPEN, RESOLVED)

SOURCE_CUSTOMER_REQUEST = "customer_request"
SOURCE_STAFF_TAKEOVER = "staff_takeover"
SOURCE_AUTOMATION_RULE = "automation_rule"
_SOURCES = (SOURCE_CUSTOMER_REQUEST, SOURCE_STAFF_TAKEOVER, SOURCE_AUTOMATION_RULE)

# Only "admin" exists in this codebase today; "owner" is accepted so the role
# can be introduced without another edit here.
SUPERVISOR_ROLES = frozenset({"admin", "owner"})

# Outcome codes. Callers branch on these, never on the reason text.
HUMAN_REQUESTED = "HUMAN_REQUESTED"
ALREADY_WAITING = "ALREADY_WAITING"
CLAIMED = "CLAIMED"
ALREADY_ASSIGNEE = "ALREADY_ASSIGNEE"
ASSIGNED = "ASSIGNED"
CONVERSATION_RESOLVED = "CONVERSATION_RESOLVED"
ALREADY_RESOLVED = "ALREADY_RESOLVED"
CONVERSATION_REOPENED = "CONVERSATION_REOPENED"
ALREADY_OPEN = "ALREADY_OPEN"
AI_RESUMED = "AI_RESUMED"
ALREADY_AI_ACTIVE = "ALREADY_AI_ACTIVE"
NOTE_INTERNAL_ONLY = "NOTE_INTERNAL_ONLY"
NOTE_EMPTY = "NOTE_EMPTY"
REPLY_ALLOWED = "REPLY_ALLOWED"
CONFLICT = "CONFLICT"
CROSS_TENANT = "CROSS_TENANT"
NOT_ASSIGNEE = "NOT_ASSIGNEE"
NOT_SUPERVISOR = "NOT_SUPERVISOR"
INVALID_STATE = "INVALID_STATE"
CONTROL_UNREADABLE = "CONTROL_UNREADABLE"

ADMISSION_AI_ACTIVE = "AI_ACTIVE"
ADMISSION_HUMAN_CONTROLLED = "HUMAN_CONTROLLED"
ADMISSION_STALE_EPOCH = "STALE_EPOCH"
ADMISSION_UNREADABLE = CONTROL_UNREADABLE


def handoff_control_enabled():
    return os.getenv("HANDOFF_CONTROL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _counter(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class HandoffActor:
    """The staff account behind a command. `company_id` is the authenticated
    company, never a value off the request body: that is what makes a
    cross-tenant command refusable."""

    user_id: int
    company_id: int
    role: str | None = None

    def __post_init__(self):
        if not _positive_int(self.user_id) or not _positive_int(self.company_id):
            raise ValueError("An actor needs a positive user_id and company_id")

    @property
    def is_supervisor(self):
        return (self.role or "").strip().lower() in SUPERVISOR_ROLES


@dataclass(frozen=True)
class ConversationControl:
    """Who holds one conversation, and which automation era it is in.

    Validated on construction: a row that collapsed mode into resolution, or
    lost its owner, must fail loudly, not read as "the bot may answer"."""

    company_id: int
    chatbot_id: int
    conversation_id: int
    mode: str
    resolution: str
    assignee_user_id: int | None
    episode_id: int
    version: int
    automation_epoch: int
    source: str | None = None

    def __post_init__(self):
        if not all(_positive_int(v) for v in (self.company_id, self.chatbot_id, self.conversation_id)):
            raise ValueError("A control needs a positive company, chatbot and conversation id")
        if self.mode not in _MODES:
            raise ValueError(f"Unknown handoff mode: {self.mode!r}")
        if self.resolution not in _RESOLUTIONS:
            raise ValueError(f"Unknown handoff resolution: {self.resolution!r}")
        if self.assignee_user_id is not None and not _positive_int(self.assignee_user_id):
            raise ValueError("An assignee must be a positive user id or None")
        if not all(_counter(v) for v in (self.episode_id, self.version, self.automation_epoch)):
            raise ValueError("Episode, version and automation epoch are non-negative counters")
        if self.source is not None and self.source not in _SOURCES:
            raise ValueError(f"Unknown handoff source: {self.source!r}")


def initial_control(company_id, chatbot_id, conversation_id):
    """The state of a conversation that has never been escalated. `load()`
    returns this when there is no row, so the domain -- not the storage layer
    -- decides what "no handoff has happened yet" means.
    """
    return ConversationControl(company_id=company_id, chatbot_id=chatbot_id,
                               conversation_id=conversation_id, mode=AI_ACTIVE, resolution=OPEN,
                               assignee_user_id=None, episode_id=0, version=0, automation_epoch=0)


@dataclass(frozen=True)
class HandoffResult:
    ok: bool
    code: str
    control: ConversationControl | None
    reason: str
    override: bool = False


@dataclass(frozen=True)
class AutomationAdmission:
    allowed: bool
    code: str
    reason: str


def _with_resolution(control, resolution):
    """Change only whether the work is finished.

    Deliberately has no mode parameter: resolving cannot hand the customer back
    to the model even by mistake, because this path cannot write `mode`."""
    return replace(control, resolution=resolution, version=control.version + 1)


def _conflict(control, reason):
    holder = control.assignee_user_id if control is not None else None
    if holder is not None:
        reason = f"{reason} User {holder} currently holds it."
    return HandoffResult(False, CONFLICT, control, reason)


def _assignee_authority(control, actor, supervisor_override):
    """Only the assignee acts; a supervisor must say out loud that they are intervening."""
    if control.assignee_user_id == actor.user_id:
        return False, None
    if not supervisor_override:
        return False, HandoffResult(False, NOT_ASSIGNEE, control, "This conversation is not assigned to you.")
    if not actor.is_supervisor:
        return False, HandoffResult(False, NOT_SUPERVISOR, control, "Only a supervisor may override the assignee.")
    return True, None


def authorize_customer_reply(control, actor, *, supervisor_override=False):
    """May this actor send something the customer will see?

    `channel_delivery_service` answers "can this channel carry it"; this
    answers "is this the person holding the conversation"."""
    if not isinstance(control, ConversationControl):
        return HandoffResult(False, CONTROL_UNREADABLE, None, "This conversation's control state could not be read.")
    if actor.company_id != control.company_id:
        return HandoffResult(False, CROSS_TENANT, None, "This conversation belongs to another company.")
    if control.mode != HUMAN_ACTIVE:
        return HandoffResult(False, INVALID_STATE, control, f"No human holds this conversation (mode {control.mode}).")
    override, refusal = _assignee_authority(control, actor, supervisor_override)
    if refusal is not None:
        return refusal
    reason = "Supervisor override: replying over the assignee." if override else "You hold this conversation."
    return HandoffResult(True, REPLY_ALLOWED, control, reason, override)


def automation_admission(control, *, epoch_at_dispatch):
    """May an automated turn dispatched earlier still reach the customer?

    Called at the send boundary with the epoch the task was dispatched under,
    so a late model answer or a Flow task queued before a takeover fails the
    check even once the conversation is `ai_active` again. The feature flag is
    deliberately not read here: flipping it mid-flight must never turn a denial
    into an admission. An unreadable control is a denial."""
    if not isinstance(control, ConversationControl):
        return AutomationAdmission(False, ADMISSION_UNREADABLE, "The control state could not be read.")
    if control.mode != AI_ACTIVE:
        return AutomationAdmission(False, ADMISSION_HUMAN_CONTROLLED, "A human holds this conversation.")
    if not _counter(epoch_at_dispatch):
        return AutomationAdmission(False, ADMISSION_STALE_EPOCH, "The task carries no usable automation epoch.")
    if epoch_at_dispatch != control.automation_epoch:
        return AutomationAdmission(False, ADMISSION_STALE_EPOCH,
                                   f"Dispatched in epoch {epoch_at_dispatch}; "
                                   f"the conversation is in epoch {control.automation_epoch}.")
    return AutomationAdmission(True, ADMISSION_AI_ACTIVE, "The model still holds this conversation.")


# --- commands ---------------------------------------------------------------

class HandoffService:
    """Commands over one conversation's control state.

    `repository` is supplied by the caller and must provide:

        load(conversation_id) -> ConversationControl | None
            The stored control, or `initial_control(...)` for a conversation
            that has never been escalated -- returning None for one of those
            would break its first escalation. None means the state could not
            be read, which every command treats as a refusal, never consent.

        compare_and_set(expected_version, new_control) -> bool
            Persist `new_control` only while the stored version is still
            `expected_version`. False means another actor won the race: the
            loser is told who holds the conversation and must not overwrite.

    Nothing here imports a repository, opens a connection or reads a clock."""

    def __init__(self, repository):
        self._repository = repository

    def _begin(self, conversation_id, actor, expected_version, company_id=None):
        """Load, or return the refusal that replaces it.

        One or the other, never an optional control: each command stops at a
        single isinstance check, and below that guard the control exists.

        Ownership is always checked. A command with no staff actor -- reopen,
        driven by an inbound customer message -- must still say which company
        it acts for, and an unstated one is a refusal rather than a pass.
        Skipping the check when the actor was None is how this function once
        let a caller reopen, and read back, another tenant's conversation."""
        control = self._repository.load(conversation_id)
        if not isinstance(control, ConversationControl):
            return HandoffResult(False, CONTROL_UNREADABLE, None,
                                 "This conversation's control state could not be read.")
        owner = actor.company_id if actor is not None else company_id
        # A wrong-tenant refusal carries no control: it must not disclose
        # another company's assignee or mode.
        if owner != control.company_id:
            return HandoffResult(False, CROSS_TENANT, None, "This conversation belongs to another company.")
        if expected_version is not None and control.version != expected_version:
            return _conflict(control, "The conversation changed since it was read.")
        return control

    def _commit(self, previous, updated, code, reason, override=False):
        # The rule this file exists to keep: a command that writes ai_active
        # without going through resume_ai() dies here, in tests, rather than
        # silently handing a customer back to the model.
        if updated.mode == AI_ACTIVE and previous.mode != AI_ACTIVE and code != AI_RESUMED:
            raise ValueError("Only resume_ai may return a conversation to the model")
        if not self._repository.compare_and_set(previous.version, updated):
            current = self._repository.load(updated.conversation_id)
            return _conflict(current if isinstance(current, ConversationControl) else None,
                             "Another actor changed this conversation first.")
        return HandoffResult(True, code, updated, reason, override)

    def request_human(self, conversation_id, *, company_id, source=SOURCE_CUSTOMER_REQUEST,
                      expected_version=None):
        """Ask for a human. Idempotent within the episode: no second notification.

        `company_id` is required for the same reason as `reopen`: the customer
        asks, so there is no staff actor, and without a stated company
        `_begin` would have nothing to check ownership against. The inbound
        path already knows it from the conversation's chatbot.
        """
        if source not in _SOURCES:
            raise ValueError(f"Unknown handoff source: {source!r}")
        control = self._begin(conversation_id, None, expected_version, company_id=company_id)
        if isinstance(control, HandoffResult):
            return control
        if control.mode != AI_ACTIVE:
            # The escalation already exists. Re-asking must not clear the
            # assignee, restart the episode or re-notify the inbox.
            return HandoffResult(True, ALREADY_WAITING, control,
                                 "A human has already been requested for this conversation.")
        # ponytail: episode_id is a per-conversation counter, not a global id.
        # Enough to tell "this escalation" from "the next one"; upgrade it to an
        # opaque id in HO-2 if an episode ever has to be referenced across rows.
        updated = replace(control, mode=WAITING_HUMAN, resolution=OPEN, assignee_user_id=None,
                          episode_id=control.episode_id + 1, source=source, version=control.version + 1)
        return self._commit(control, updated, HUMAN_REQUESTED, "A human has been requested; the model is paused.")

    def claim(self, conversation_id, actor, *, expected_version):
        """Take an unclaimed escalation. Exactly one of two racing claims wins."""
        control = self._begin(conversation_id, actor, expected_version)
        if isinstance(control, HandoffResult):
            return control
        if control.mode == HUMAN_ACTIVE:
            if control.assignee_user_id == actor.user_id:
                return HandoffResult(True, ALREADY_ASSIGNEE, control, "You already hold this conversation.")
            return _conflict(control, "This conversation has already been claimed.")
        if control.mode != WAITING_HUMAN:
            return HandoffResult(False, INVALID_STATE, control, "Nobody has asked for a human here.")
        updated = replace(control, mode=HUMAN_ACTIVE, assignee_user_id=actor.user_id, version=control.version + 1)
        return self._commit(control, updated, CLAIMED, "You now hold this conversation.")

    def assign(self, conversation_id, actor, *, to_user_id, expected_version, supervisor_override=False):
        """Give the conversation to `to_user_id`, keeping it in human hands."""
        if not _positive_int(to_user_id):
            raise ValueError("An assignment needs a positive target user id")
        control = self._begin(conversation_id, actor, expected_version)
        if isinstance(control, HandoffResult):
            return control
        if control.mode == AI_ACTIVE:
            return HandoffResult(False, INVALID_STATE, control,
                                 "The model still holds this conversation; request a human first.")
        # Taking a conversation off the person holding it is an intervention;
        # handing on your own, or picking up an unheld one, is not.
        override = False
        if control.assignee_user_id is not None:
            override, refusal = _assignee_authority(control, actor, supervisor_override)
            if refusal is not None:
                return refusal
        updated = replace(control, mode=HUMAN_ACTIVE, assignee_user_id=to_user_id, version=control.version + 1)
        return self._commit(control, updated, ASSIGNED, f"Conversation assigned to user {to_user_id}.", override)

    def transfer(self, conversation_id, actor, *, to_user_id, expected_version, supervisor_override=False):
        """Hand your own conversation to a colleague -- `assign` under the same rules."""
        return self.assign(conversation_id, actor, to_user_id=to_user_id,
                           expected_version=expected_version, supervisor_override=supervisor_override)

    def resolve(self, conversation_id, actor, *, expected_version, supervisor_override=False):
        """Mark the work finished. The human keeps the conversation; AI does not resume."""
        control = self._begin(conversation_id, actor, expected_version)
        if isinstance(control, HandoffResult):
            return control
        if control.mode != HUMAN_ACTIVE:
            return HandoffResult(False, INVALID_STATE, control, "Only a conversation a human holds can be resolved.")
        override, refusal = _assignee_authority(control, actor, supervisor_override)
        if refusal is not None:
            return refusal
        if control.resolution == RESOLVED:
            return HandoffResult(True, ALREADY_RESOLVED, control, "This conversation is already resolved.")
        updated = _with_resolution(control, RESOLVED)
        return self._commit(control, updated, CONVERSATION_RESOLVED,
                            "Resolved. The conversation stays with its human owner.", override)

    def reopen(self, conversation_id, *, company_id, expected_version=None):
        """A new customer message reopens the work without changing who holds it.

        `company_id` is required even though no staff member is acting: this is
        the only command without an actor, and without it `_begin` would have
        nothing to check ownership against. The inbound path knows the company
        from the conversation's chatbot; a staff caller passes its own.
        """
        control = self._begin(conversation_id, None, expected_version, company_id=company_id)
        if isinstance(control, HandoffResult):
            return control
        if control.resolution == OPEN:
            return HandoffResult(True, ALREADY_OPEN, control, "This conversation is already open.")
        updated = _with_resolution(control, OPEN)
        return self._commit(control, updated, CONVERSATION_REOPENED,
                            "Reopened by a new customer message; the owner is unchanged.")

    def resume_ai(self, conversation_id, actor, *, expected_version, supervisor_override=False):
        """The only way back to the model, and only a staff member may ask for it.

        Never a timeout, never a new message, never a sentence the customer
        typed. The epoch moves so anything queued before now is stale."""
        control = self._begin(conversation_id, actor, expected_version)
        if isinstance(control, HandoffResult):
            return control
        if control.mode == AI_ACTIVE:
            return HandoffResult(True, ALREADY_AI_ACTIVE, control, "The model already holds this conversation.")
        override, refusal = _assignee_authority(control, actor, supervisor_override)
        if refusal is not None:
            return refusal
        updated = replace(control, mode=AI_ACTIVE, assignee_user_id=None,
                          automation_epoch=control.automation_epoch + 1, version=control.version + 1)
        return self._commit(control, updated, AI_RESUMED,
                            "The model is answering again; queued pre-takeover tasks are now stale.", override)

    def record_internal_note(self, conversation_id, actor, *, text):
        """Authorise a staff-only note. It changes nothing, and that is the point.

        A note is not a reply: nothing customer-facing, so it does not reopen,
        resolve, reassign or bump the version, and no timestamp here for it to
        touch. Any colleague in the company may leave one -- notes are how a
        supervisor helps without taking over."""
        control = self._begin(conversation_id, actor, None)
        if isinstance(control, HandoffResult):
            return control
        if not isinstance(text, str) or not text.strip():
            return HandoffResult(False, NOTE_EMPTY, control, "An internal note needs text.")
        return HandoffResult(True, NOTE_INTERNAL_ONLY, control, "Internal note; nothing is sent to the customer.")
