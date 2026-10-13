"""service_booking_repository.py - Persistence for chat-collected bookings (table service_bookings).

Every read and write takes company_id and filters on it. An update also filters on the
version the caller last saw, so a stale edit changes nothing instead of overwriting a
newer one. The table comes from data/072_service_bookings.sql.
"""

from datetime import datetime, timezone

from app.database.db import supabase

TABLE = "service_bookings"
INTAKE_UNIQUE = "service_bookings_intake_unique"  # the constraint in data/072_service_bookings.sql
MAX_PAGE = 200
CSV_PAGE = 1000  # PostgREST on Supabase returns at most 1000 rows per response by default

_COLUMNS = (
    "id,company_id,chatbot_id,conversation_id,kind,status,customer_name,customer_phone,"
    "customer_ref,channel,service_name,scheduled_for,party_size,notes,source,version,"
    "created_at,updated_at,confirmed_at,cancelled_at,package_id,slot_id,seats,price_micro_myr"
)  # the last four need data/073; deploy after applying it
# Ownership and identity (company, chatbot, conversation, intake key, source, version) are
# fixed at creation; the version is advanced here, never taken from the caller.
_EDITABLE = frozenset({
    "status", "kind", "customer_name", "service_name", "scheduled_for", "party_size",
    "notes", "confirmed_at", "cancelled_at",
})


def _positive_int(value):
    return type(value) is int and value > 0


def _first(response):
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def _is_duplicate(error):
    """True only for a replay of the same intake key. Any other unique violation is a real error."""
    text = str(error)
    return INTAKE_UNIQUE in text and (getattr(error, "code", None) == "23505" or "duplicate key" in text.lower())


def create_booking(row):
    """Insert one booking. Returns None when its intake_key already exists for the company."""
    try:
        response = supabase.table(TABLE).insert(row).execute()
    except Exception as error:
        if _is_duplicate(error):
            return None
        raise
    return _first(response)


def get_booking(company_id, booking_id):
    if not (_positive_int(company_id) and _positive_int(booking_id)):
        return None
    response = (
        supabase.table(TABLE).select(_COLUMNS)
        .eq("company_id", company_id).eq("id", booking_id).limit(1).execute()
    )
    return _first(response)


def get_booking_by_intake_key(company_id, intake_key):
    if not _positive_int(company_id) or not intake_key:
        return None
    response = (
        supabase.table(TABLE).select(_COLUMNS)
        .eq("company_id", company_id).eq("intake_key", intake_key).limit(1).execute()
    )
    return _first(response)


def list_bookings(company_id, *, chatbot_id=None, status=None, limit=50, offset=0):
    """Newest first, one page. The page size is capped so a caller cannot ask for everything."""
    if not _positive_int(company_id):
        raise ValueError("A company is required.")
    limit = min(max(int(limit), 1), MAX_PAGE)
    offset = max(int(offset), 0)
    query = supabase.table(TABLE).select(_COLUMNS).eq("company_id", company_id)
    if chatbot_id is not None:
        query = query.eq("chatbot_id", chatbot_id)
    if status is not None:
        query = query.eq("status", status)
    response = (
        query.order("created_at", desc=True).order("id", desc=True)
        .range(offset, offset + limit - 1).execute()
    )
    return list(response.data or [])


def list_bookings_for_csv(company_id, limit):
    """The newest `limit` bookings, newest first, whatever the server's own response cap is.

    PostgREST silently truncates one response (1000 rows by default), so this reads pages
    until it has `limit` rows, has the company's total, or gets an empty page. Rows are
    de-duplicated by id because a booking inserted between pages shifts the next page.
    """
    if not _positive_int(company_id):
        raise ValueError("A company is required.")
    rows, seen, offset, target = [], set(), 0, limit
    while len(rows) < target:
        size = min(CSV_PAGE, limit - len(rows))
        response = (
            supabase.table(TABLE).select(_COLUMNS, count="exact").eq("company_id", company_id)
            .order("created_at", desc=True).order("id", desc=True)
            .range(offset, offset + size - 1).execute()
        )
        page = list(response.data or [])
        if not page:
            break
        total = getattr(response, "count", None)
        if total is not None:
            target = min(target, total)
        for row in page:
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
        offset += len(page)
    return rows


def _count_recent(query, since_iso, before_iso=None):
    query = query.gte("created_at", since_iso)
    if before_iso is not None:
        query = query.lt("created_at", before_iso)
    return getattr(query.limit(1).execute(), "count", None) or 0


def count_recent_for_conversation(company_id, conversation_id, since_iso):
    return _count_recent(
        supabase.table(TABLE).select("id", count="exact")
        .eq("company_id", company_id).eq("conversation_id", conversation_id), since_iso)


def count_recent_for_company(company_id, since_iso, source="chat", before_iso=None):
    """Bookings of one source created since the given time, across all of the company's chats.

    before_iso narrows it to those created strictly earlier than that moment.
    """
    return _count_recent(
        supabase.table(TABLE).select("id", count="exact")
        .eq("company_id", company_id).eq("source", source), since_iso, before_iso)


def update_booking(company_id, booking_id, expected_version, changes):
    """Apply an edit only if the row is still at expected_version. None means no row matched."""
    unknown = set(changes) - _EDITABLE
    if unknown:
        raise ValueError("These fields cannot be updated: " + ", ".join(sorted(unknown)))
    payload = dict(changes, version=expected_version + 1,
                   updated_at=datetime.now(timezone.utc).isoformat())
    response = (
        supabase.table(TABLE).update(payload)
        .eq("id", booking_id).eq("company_id", company_id).eq("version", expected_version)
        .execute()
    )
    return _first(response)


def set_intake_enabled(company_id, chatbot_id, enabled):
    """Turn chat booking intake on or off for one of this company's chatbots."""
    response = (
        supabase.table("chatbots").update({"booking_intake_enabled": bool(enabled)})
        .eq("id", chatbot_id).eq("company_id", company_id).execute()
    )
    return bool(getattr(response, "data", None))
