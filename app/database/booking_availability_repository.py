"""booking_availability_repository.py - Persistence for availability booking (data/073).

Tables: booking_packages, booking_schedules, booking_closures, booking_slots, plus the
functions booking_reserve and booking_cancel, which are the only way seats move. Every
read and write takes company_id (and the chatbot where it applies) and filters on it;
edits also filter on the version the caller last saw, so a stale edit changes nothing.
"""

from datetime import datetime, timezone

from app.database.db import supabase

PACKAGE_COLUMNS = ("id,company_id,chatbot_id,name,description,duration_minutes,price_mode,"
                   "price_micro_myr,seats_per_slot,seats_by_party,enabled,sort_order,version,"
                   "created_at,updated_at")
SLOT_COLUMNS = "id,company_id,chatbot_id,package_id,starts_at,ends_at,capacity,booked_seats,status,source,version"
PACKAGE_EDITABLE = frozenset({"name", "description", "duration_minutes", "price_mode", "price_micro_myr",
                              "seats_per_slot", "seats_by_party", "enabled", "sort_order"})
SLOT_EDITABLE = frozenset({"capacity", "status"})
MAX_ROWS = 1000  # PostgREST's silent per-response cap on Supabase


def _rows(response):
    return list(getattr(response, "data", None) or [])


def _first(response):
    rows = _rows(response)
    return rows[0] if rows else None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# --- packages ----------------------------------------------------------------------

def list_packages(company_id, chatbot_id):
    return _rows(supabase.table("booking_packages").select(PACKAGE_COLUMNS)
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
                 .order("sort_order").order("id").limit(MAX_ROWS).execute())


def get_package(company_id, package_id):
    return _first(supabase.table("booking_packages").select(PACKAGE_COLUMNS)
                  .eq("company_id", company_id).eq("id", package_id).limit(1).execute())


def create_package(row):
    return _first(supabase.table("booking_packages").insert(row).execute())


def update_package(company_id, package_id, expected_version, changes):
    """None when the package is not this company's or was changed since expected_version."""
    unknown = set(changes) - PACKAGE_EDITABLE
    if unknown:
        raise ValueError("These fields cannot be updated: " + ", ".join(sorted(unknown)))
    payload = dict(changes, version=expected_version + 1, updated_at=_now_iso())
    return _first(supabase.table("booking_packages").update(payload)
                  .eq("company_id", company_id).eq("id", package_id).eq("version", expected_version).execute())


# --- weekly hours and closed dates ---------------------------------------------------

def list_schedules_for_chatbot(company_id, chatbot_id):
    return _rows(supabase.table("booking_schedules")
                 .select("id,package_id,weekday,start_time,end_time,interval_minutes")
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
                 .order("package_id").order("weekday").order("start_time").limit(MAX_ROWS).execute())


def replace_schedules(company_id, chatbot_id, package_id, rows):
    """Replace one package's weekly hours. Two statements: a failure between them leaves the
    package with no hours (safe: nothing new is generated) until the owner saves again."""
    (supabase.table("booking_schedules").delete()
     .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("package_id", package_id).execute())
    if rows:
        supabase.table("booking_schedules").insert(rows).execute()


def list_closures(company_id, chatbot_id, from_date):
    return _rows(supabase.table("booking_closures").select("id,package_id,closed_on,reason")
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
                 .gte("closed_on", from_date).order("closed_on").limit(MAX_ROWS).execute())


def add_closure(row):
    """None when that date is already closed for that package (or the whole chatbot)."""
    try:
        return _first(supabase.table("booking_closures").insert(row).execute())
    except Exception as error:
        if "booking_closures_once" in str(error):
            return None
        raise


def delete_closure(company_id, closure_id):
    return _first(supabase.table("booking_closures").delete()
                  .eq("company_id", company_id).eq("id", closure_id).execute())


# --- slots ----------------------------------------------------------------------------

def latest_schedule_slot_start(company_id, chatbot_id):
    row = _first(supabase.table("booking_slots").select("starts_at")
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("source", "schedule")
                 .order("starts_at", desc=True).limit(1).execute())
    return row["starts_at"] if row else None


def insert_slots(rows):
    """Insert slots, silently skipping times that already exist for the package."""
    for start in range(0, len(rows), 500):
        (supabase.table("booking_slots")
         .upsert(rows[start:start + 500], on_conflict="package_id,starts_at", ignore_duplicates=True)
         .execute())


def create_slot(row):
    """Insert one owner-made slot. None when the package already has a slot at that time."""
    try:
        return _first(supabase.table("booking_slots").insert(row).execute())
    except Exception as error:
        if "booking_slots_once" in str(error):
            return None
        raise


def reopen_schedule_slots_between(company_id, chatbot_id, start_iso, end_iso, package_id=None):
    """Reopen the weekly times of a date that is no longer closed."""
    query = (supabase.table("booking_slots").update({"status": "open", "updated_at": _now_iso()})
             .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("status", "closed")
             .eq("source", "schedule").gte("starts_at", start_iso).lt("starts_at", end_iso))
    if package_id is not None:
        query = query.eq("package_id", package_id)
    query.execute()


def list_open_slots(company_id, chatbot_id, package_id, start_iso, end_iso, limit):
    return _rows(supabase.table("booking_slots").select(SLOT_COLUMNS)
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("package_id", package_id)
                 .eq("status", "open").gte("starts_at", start_iso).lt("starts_at", end_iso)
                 .order("starts_at").limit(min(limit, MAX_ROWS)).execute())


def list_slots(company_id, chatbot_id, start_iso, end_iso, limit=MAX_ROWS):
    """Every slot in the window, open or closed, for the owner's list."""
    return _rows(supabase.table("booking_slots").select(SLOT_COLUMNS)
                 .eq("company_id", company_id).eq("chatbot_id", chatbot_id)
                 .gte("starts_at", start_iso).lt("starts_at", end_iso)
                 .order("starts_at").limit(min(limit, MAX_ROWS)).execute())


def get_slot(company_id, chatbot_id, slot_id):
    return _first(supabase.table("booking_slots").select(SLOT_COLUMNS)
                  .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("id", slot_id).limit(1).execute())


def get_slot_at(company_id, chatbot_id, package_id, starts_iso):
    """The package's slot starting exactly then (starts are unique per package)."""
    return _first(supabase.table("booking_slots").select(SLOT_COLUMNS)
                  .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("package_id", package_id)
                  .eq("starts_at", starts_iso).limit(1).execute())


def update_slot(company_id, slot_id, expected_version, changes):
    """Capacity or open/closed. A capacity below the booked seats fails on the table's CHECK."""
    unknown = set(changes) - SLOT_EDITABLE
    if unknown:
        raise ValueError("These fields cannot be updated: " + ", ".join(sorted(unknown)))
    payload = dict(changes, version=expected_version + 1, updated_at=_now_iso())
    return _first(supabase.table("booking_slots").update(payload)
                  .eq("company_id", company_id).eq("id", slot_id).eq("version", expected_version).execute())


def close_slots_between(company_id, chatbot_id, start_iso, end_iso, package_id=None):
    """Close every open slot in the window (a newly closed date). Bookings in them are kept."""
    query = (supabase.table("booking_slots").update({"status": "closed", "updated_at": _now_iso()})
             .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("status", "open")
             .gte("starts_at", start_iso).lt("starts_at", end_iso))
    if package_id is not None:
        query = query.eq("package_id", package_id)
    query.execute()


def delete_future_unbooked_schedule_slots(company_id, chatbot_id, package_id, from_iso):
    """Drop open generated slots nobody booked, before regenerating from new weekly hours.
    Closed ones stay: the owner closed them, and regeneration skips starts that exist."""
    (supabase.table("booking_slots").delete()
     .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("package_id", package_id)
     .eq("source", "schedule").eq("status", "open").eq("booked_seats", 0)
     .gte("starts_at", from_iso).execute())


# --- seats ----------------------------------------------------------------------------
# booking_reserve takes seats; giving them back needs no call here: cancelling a booking
# through service_booking_repository.update_booking fires the database trigger that does it.

def reserve(company_id, chatbot_id, slot_id, party_size, confirm, booking):
    """Take seats atomically. Returns the function's {"outcome": ..., "booking"?: {...}}."""
    response = supabase.rpc("booking_reserve", {
        "p_company_id": company_id, "p_chatbot_id": chatbot_id, "p_slot_id": slot_id,
        "p_party_size": party_size, "p_confirm": bool(confirm), "p_booking": booking,
    }).execute()
    return getattr(response, "data", None) or {}


def set_auto_confirm(company_id, chatbot_id, enabled):
    response = (supabase.table("chatbots").update({"booking_auto_confirm": bool(enabled)})
                .eq("id", chatbot_id).eq("company_id", company_id).execute())
    return bool(getattr(response, "data", None))
