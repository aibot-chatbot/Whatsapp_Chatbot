"""Storage for one conversation's handoff control state (HO-2).

`handoff_service` is pure domain and reaches storage only through the two
functions below, so this module *is* the repository it asks for:
``HandoffService(handoff_control_repository)``. No class, because the
protocol holds no state of its own.

Two rules from that protocol are load-bearing and easy to get backwards:

* **An absent row is not an absent answer.** A conversation that was never
  escalated has no row by design -- 060 adds no backfill precisely because
  the domain already answers this: `initial_control()`. Returning None here
  would refuse the very first escalation of every conversation.
* **None means the state could not be read.** Every command treats it as a
  refusal, so a caught exception returns None and never a synthesised
  default. Failing open would hand a customer back to the model in the
  middle of a human conversation, which is the whole bug HO-1 exists to
  prevent.

The new version is never computed here. `handoff_control_compare_and_set`
derives it from `p_expected_version` inside one conditional UPDATE, because
a read-then-write in Python lets two staff both win the same claim.
"""

import logging

from app.database.bot_repository import get_bot_by_id
from app.database.db import supabase
from app.services.handoff_service import ConversationControl, initial_control


logger = logging.getLogger(__name__)

TABLE_NAME = "conversation_handoff_controls"
COMPARE_AND_SET_FUNCTION = "handoff_control_compare_and_set"


def load(conversation_id):
    """The stored control, `initial_control(...)` when there is no row yet,
    or None when the state could not be read at all."""
    try:
        response = (
            supabase
            .table(TABLE_NAME)
            .select("*")
            .eq("conversation_id", conversation_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []
        if rows:
            return _to_control(rows[0])

        company_id, chatbot_id = _resolve_owner(conversation_id)
        return initial_control(company_id, chatbot_id, conversation_id)
    except Exception:
        # Also catches a row that fails ConversationControl's validation, and
        # that is the intent: a control whose mode and resolution cannot be
        # trusted is unreadable state, not a conversation the model may
        # answer. Unreadable refuses; it never defaults.
        logger.exception(
            "[Handoff] control state unreadable for conversation_id=%s", conversation_id
        )
        return None


def compare_and_set(expected_version, new_control):
    """Persist `new_control` only while the stored version is still
    `expected_version`. False means someone else won the race."""
    try:
        response = supabase.rpc(COMPARE_AND_SET_FUNCTION, {
            "p_conversation_id": new_control.conversation_id,
            "p_company_id": new_control.company_id,
            "p_chatbot_id": new_control.chatbot_id,
            # The version the caller READ, not the one it wants written. The
            # function writes p_expected_version + 1 itself; sending
            # new_control.version (already incremented by the domain) would
            # match no stored row and lose every single write.
            "p_expected_version": expected_version,
            "p_handling_mode": new_control.mode,
            "p_resolution_status": new_control.resolution,
            "p_assignee_user_id": new_control.assignee_user_id,
            "p_episode_id": new_control.episode_id,
            "p_automation_epoch": new_control.automation_epoch,
            "p_source": new_control.source,
        }).execute()
    except Exception:
        # A refusal the function decided is a `won: false` payload, but a
        # CHECK violation (23514 -- an unknown mode, a negative counter, an
        # assignee on a conversation no human holds) raises out of it
        # instead. Both mean "you did not get this conversation", so both
        # have to reach the caller as the same plain False; an exception
        # escaping here would bypass every _conflict() branch in the domain.
        logger.exception(
            "[Handoff] compare-and-set failed for conversation_id=%s",
            new_control.conversation_id,
        )
        return False

    outcome = response.data
    # Only an explicit win is a win. A null payload, a list, a missing key or
    # a truthy-but-not-True value all mean the caller must not believe it
    # holds this conversation -- the same posture as the refusal codes.
    return isinstance(outcome, dict) and outcome.get("won") is True


def _to_control(row):
    """One stored row as the domain's value object.

    The column names differ from the field names on purpose: handling_mode
    and resolution_status are the two columns that must never collapse into
    one, and the domain calls them mode and resolution."""
    return ConversationControl(
        company_id=row["company_id"],
        chatbot_id=row["chatbot_id"],
        conversation_id=row["conversation_id"],
        mode=row["handling_mode"],
        resolution=row["resolution_status"],
        assignee_user_id=row.get("assignee_user_id"),
        episode_id=row["episode_id"],
        version=row["version"],
        automation_epoch=row["automation_epoch"],
        source=row.get("source"),
    )


def _resolve_owner(conversation_id):
    """Who owns a conversation that has no control row yet.

    Read from storage, never taken from a caller: `load()` is handed only a
    conversation_id, and a company_id off a request body is exactly the
    value the RPC's tenancy check exists to distrust. This walks the same
    conversation -> chatbot -> company chain as
    chat_pipeline_service._resolve_chatbot_company_id and reuses its
    turn-cached bot read, so inside one reply turn it costs one round trip.
    Anything missing raises, and load() turns that into "unreadable"."""
    rows = (
        supabase
        .table("conversations")
        .select("chatbot_id")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    ).data or []
    if not rows:
        raise LookupError(f"No conversation {conversation_id}")

    chatbot_id = rows[0].get("chatbot_id")
    chatbot = get_bot_by_id(chatbot_id) or {}
    if chatbot.get("id") != chatbot_id:
        raise LookupError(f"Chatbot ownership unresolved for conversation {conversation_id}")

    # company_id is not validated here: initial_control() builds a
    # ConversationControl, which rejects a missing or non-positive owner and
    # is caught above. One validator, in the domain that defines the rule.
    return chatbot.get("company_id"), chatbot_id
