"""availability_service.py - Bookable times for availability booking (Pro).

Weekly hours (booking_schedules) are turned into slot rows ahead of time; one-off slots are
rows the owner adds; closed dates stop generation. The AI may only offer what open_slots
returns, and booking_reserve in the database has the final say on seats.
Times are Malaysia time (UTC+8, no daylight saving) and are stored in UTC.
"""

import re
from datetime import datetime, time, timedelta, timezone

from flask import g, has_request_context

from app.database import booking_availability_repository as repo

FEATURE_KEY = "availability_booking"
MYT = timezone(timedelta(hours=8))
PROMPT_DAYS = 14             # how far ahead the AI is shown open times
PROMPT_TIMES_PER_PACKAGE = 6  # listed with codes; any other open time is booked by package + time
_SLOT_CODE = re.compile(r"[Ss]?([0-9]{1,12})")
_PACKAGE_CODE = re.compile(r"[Pp]?([0-9]{1,12})")
GENERATE_DAYS = 28                 # weekly hours become slot rows this far ahead
TOP_UP_DAYS = 14                   # ...topped up once fewer days than this are left
MIN_LEAD = timedelta(minutes=30)   # never offer a time that starts sooner than this
MAX_PACKAGES = 25                  # per chatbot: every chat message reads them all
MAX_SLOTS_PER_PACKAGE = 2000       # generated per run: about 70 a day over GENERATE_DAYS
# Rows are read in pages of this size, below PostgREST's silent 1000-row cap. Full times
# stay 'open', so paging walks past a fully booked stretch to the times that still have seats.
SCAN_PER_PACKAGE = 200
# ponytail: at most this many pages per package and window; past them a package shows no
# further times in the prompt (they stay bookable by package + time).
SCAN_PAGES = 5


def _now():
    return datetime.now(timezone.utc)


def _utc(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def is_enabled(company_id, *, strict=False):
    """Check the plan flag. Fingerprints must distinguish a read failure from a disabled flag."""
    from app.services.billing_guard import BillingLimitError, can_use_plan_feature
    try:
        return can_use_plan_feature(company_id, FEATURE_KEY) is True
    except Exception as error:
        if strict and not (isinstance(error, BillingLimitError) and error.code == "feature_not_available"):
            raise
        return False


def _parse_code(pattern, value):
    if isinstance(value, bool):
        return None
    match = pattern.fullmatch(str(value).strip()) if isinstance(value, (str, int)) else None
    return int(match.group(1)) if match else None


def parse_slot_code(value):
    """The slot id in a model-supplied code like "S12", or None for anything else."""
    return _parse_code(_SLOT_CODE, value)


def parse_package_code(value):
    """The package id in a model-supplied code like "P5", or None for anything else."""
    return _parse_code(_PACKAGE_CODE, value)


def time_label(starts_at, *, year=False):
    """"Mon 5 Oct 10:00" (short enough for a button), or "Mon 5 Oct 2026, 10:00"."""
    local = _utc(starts_at).astimezone(MYT)
    day = f"{local:%a} {local.day} {local:%b}"
    return f"{day} {local.year}, {local:%H:%M}" if year else f"{day} {local:%H:%M}"


def format_myr(micro_myr):
    ringgit, sen = divmod(int(micro_myr) // 10_000, 100)
    return f"RM {ringgit:,}.{sen:02d}"


def price_text(package):
    """What the customer may be told about the price, following the package's price rule."""
    mode, price = package.get("price_mode"), package.get("price_micro_myr")
    if mode == "fixed" and price is not None:
        return format_myr(price)
    if mode == "per_person" and price is not None:
        return format_myr(price) + " per person"
    if mode == "quote":
        return "price on quote"
    return ""


def _clock(value):
    return time.fromisoformat(str(value)[:8])


def schedule_times(schedules, closures, package, first_day, last_day):
    """(starts_at, ends_at) in UTC for one package's weekly hours, skipping closed days.

    A time is only produced when the whole appointment fits before closing time.
    """
    duration = timedelta(minutes=package["duration_minutes"])
    closed = {str(c["closed_on"]) for c in closures if c.get("package_id") in (None, package["id"])}
    hours = [s for s in schedules if s["package_id"] == package["id"]]
    day = first_day
    while day <= last_day:
        if day.isoformat() not in closed:
            for block in (s for s in hours if s["weekday"] == day.isoweekday()):
                start = datetime.combine(day, _clock(block["start_time"]), MYT)
                close = datetime.combine(day, _clock(block["end_time"]), MYT)
                step = timedelta(minutes=block["interval_minutes"])
                while start + duration <= close:
                    yield start.astimezone(timezone.utc), (start + duration).astimezone(timezone.utc)
                    start += step
        day += timedelta(days=1)


def _enabled_packages(company_id, chatbot_id):
    return [p for p in repo.list_packages(company_id, chatbot_id) if p.get("enabled")]


def generate_slots(company_id, chatbot_id, now, packages=None):
    """Turn weekly hours into slot rows for the next GENERATE_DAYS. Safe to repeat."""
    packages = _enabled_packages(company_id, chatbot_id) if packages is None else packages
    if not packages:
        return 0
    today = now.astimezone(MYT).date()
    schedules = repo.list_schedules_for_chatbot(company_id, chatbot_id)
    closures = repo.list_closures(company_id, chatbot_id, today.isoformat())
    rows = []
    for package in packages:
        # Overlapping hour blocks repeat a start; one row each, and a bounded number per package.
        by_start = {}
        for starts, ends in schedule_times(schedules, closures, package, today, today + timedelta(days=GENERATE_DAYS)):
            if starts > now and starts not in by_start and len(by_start) < MAX_SLOTS_PER_PACKAGE:
                by_start[starts] = {
                    "company_id": company_id, "chatbot_id": chatbot_id, "package_id": package["id"],
                    "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
                    "capacity": package["seats_per_slot"], "source": "schedule"}
        rows.extend(by_start.values())
    if rows:
        repo.insert_slots(rows)
    return len(rows)


def _top_up(company_id, chatbot_id, now, packages):
    latest = repo.latest_schedule_slot_start(company_id, chatbot_id)
    if latest is None or _utc(latest) < now + timedelta(days=TOP_UP_DAYS):
        generate_slots(company_id, chatbot_id, now, packages)


def open_slots(company_id, chatbot_id, *, now=None, days=14):
    """Times the AI may offer, earliest first: open, not full, of a switched-on package,
    and starting at least MIN_LEAD from now. Each has slot_id, package_id, package_name,
    starts_at (UTC ISO) and seats_left."""
    now = now or _now()
    packages = _enabled_packages(company_id, chatbot_id)
    if not packages:
        return []
    if not (has_request_context() and getattr(g, "publish_test", False)):
        _top_up(company_id, chatbot_id, now, packages)
    start, end = (now + MIN_LEAD).isoformat(), (now + timedelta(days=days)).isoformat()
    # A one-off or reopened time on a closed date is refused by booking_reserve; never offer it.
    closures = repo.list_closures(company_id, chatbot_id, now.astimezone(MYT).date().isoformat())
    offered = []
    for package in packages:
        closed = {str(c["closed_on"]) for c in closures if c.get("package_id") in (None, package["id"])}
        for slot in _rows_with_seats(company_id, chatbot_id, package["id"], start, end):
            if _utc(slot["starts_at"]).astimezone(MYT).date().isoformat() not in closed:
                offered.append({"slot_id": slot["id"], "package_id": package["id"],
                                "package_name": package["name"], "starts_at": slot["starts_at"],
                                "seats_left": slot["capacity"] - slot["booked_seats"],
                                "seats_by_party": bool(package.get("seats_by_party"))})
    return sorted(offered, key=lambda slot: (_utc(slot["starts_at"]), slot["package_id"]))


def _rows_with_seats(company_id, chatbot_id, package_id, start, end):
    """Open rows of one package that still have a seat, earliest first."""
    rows, seen = [], set()
    for _ in range(SCAN_PAGES):
        page = repo.list_open_slots(company_id, chatbot_id, package_id, start, end, SCAN_PER_PACKAGE)
        rows += [r for r in page if r["id"] not in seen and r["capacity"] > r["booked_seats"]]
        seen.update(r["id"] for r in page)
        if len(page) < SCAN_PER_PACKAGE or len(rows) >= SCAN_PER_PACKAGE:
            break
        start = page[-1]["starts_at"]  # starts are unique per package; `seen` drops the repeat
    return rows


def _seats_left(count):
    return f"{count} seat left" if count == 1 else f"{count} seats left"


def prompt_catalogue(company_id, chatbot_id, *, now=None):
    """The packages and open times the AI may offer, one block per package, or "" when the
    chatbot has no switched-on package. Each time carries the code the model books with."""
    now = now or _now()
    packages = _enabled_packages(company_id, chatbot_id)
    if not packages:
        return ""
    times = open_slots(company_id, chatbot_id, now=now, days=PROMPT_DAYS)
    lines = []
    for package in packages:
        price = price_text(package)
        lines.append(f"- [P{package['id']}] {package['name']} ({package['duration_minutes']} min)"
                     + (f" - {price}" if price else ""))
        if package.get("seats_by_party"):
            lines.append("  Each person takes a seat, so ask how many people are coming.")
        own = [t for t in times if t["package_id"] == package["id"]]
        listed = own[:PROMPT_TIMES_PER_PACKAGE]
        lines.append("  Open times: " + "; ".join(
            f"[S{t['slot_id']}] {time_label(t['starts_at'])} ({_seats_left(t['seats_left'])})" for t in listed)
            if listed else f"  No open times in the next {PROMPT_DAYS} days.")
        more_days = list(dict.fromkeys(_day_label(t["starts_at"]) for t in own[PROMPT_TIMES_PER_PACKAGE:]))
        if more_days:
            lines.append("  Also open on: " + ", ".join(more_days))
    return "\n".join(lines)


def _day_label(starts_at):
    local = _utc(starts_at).astimezone(MYT)
    return f"{local:%a} {local.day} {local:%b}"


def slot_at(company_id, chatbot_id, package_code, when):
    """The slot id of a package's time given as Malaysia time ("2026-10-10 19:00"), else None.

    Lets the model book an open time that was not listed with a code; booking_reserve still
    decides whether it is open and has a seat.
    """
    package_id = parse_package_code(package_code)
    try:
        moment = _local_moment(when)
    except AvailabilityError:
        return None
    if package_id is None:
        return None
    slot = repo.get_slot_at(company_id, chatbot_id, package_id, moment.isoformat())
    return slot["id"] if slot else None


# --- owner management (Pro) -------------------------------------------------------------

class AvailabilityError(Exception):
    status_code = 400
    code = "invalid_availability"


class AvailabilityNotFound(AvailabilityError):
    status_code = 404
    code = "not_found"


class AvailabilityConflict(AvailabilityError):
    status_code = 409
    code = "availability_changed"


class FeatureLocked(AvailabilityError):
    status_code = 403
    code = "feature_not_available"


PRICE_MODES = ("none", "fixed", "per_person", "quote")
MAX_HOUR_BLOCKS = 50
# What a new package starts with for each industry (the owner can change every field).
INDUSTRY_DEFAULTS = {
    "restaurant":     {"label": "Table",        "price_mode": "none",       "seats_by_party": True,  "seats_per_slot": 40},
    "clinic":         {"label": "Appointment",  "price_mode": "none",       "seats_by_party": False, "seats_per_slot": 1},
    "tuition_center": {"label": "Class",        "price_mode": "fixed",      "seats_by_party": True,  "seats_per_slot": 20},
    "beauty_salon":   {"label": "Treatment",    "price_mode": "fixed",      "seats_by_party": False, "seats_per_slot": 1},
    "car_workshop":   {"label": "Service slot", "price_mode": "quote",      "seats_by_party": False, "seats_per_slot": 3},
    "property_agent": {"label": "Viewing",      "price_mode": "none",       "seats_by_party": False, "seats_per_slot": 1},
    "travel_agency":  {"label": "Tour",         "price_mode": "per_person", "seats_by_party": True,  "seats_per_slot": 30},
    "retail_shop":    {"label": "Pickup",       "price_mode": "none",       "seats_by_party": False, "seats_per_slot": 5},
    "general":        {"label": "Booking",      "price_mode": "none",       "seats_by_party": False, "seats_per_slot": 1},
}
_HHMM = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LOCAL_MOMENT = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


def defaults_for(industry_id):
    return dict(INDUSTRY_DEFAULTS.get(industry_id) or INDUSTRY_DEFAULTS["general"])


def require_enabled(company_id):
    if not is_enabled(company_id):
        raise FeatureLocked("Availability booking is part of the Pro plan.")


def _whole(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise AvailabilityError(f"{name} must be a whole number from {low} to {high}.")
    return value


def _text(value, name, maximum, *, required=False):
    from app.services.booking_service import clean_text  # one cleaner for all booking text
    if value is not None and not isinstance(value, str):
        raise AvailabilityError(f"{name} must be text.")
    cleaned = clean_text(value, maximum)
    if required and not cleaned:
        raise AvailabilityError(f"{name} is required.")
    return cleaned


def _price_micro(value):
    """A ringgit amount like "35.00" or 35 as integer micro-MYR, or None when absent."""
    from decimal import Decimal, InvalidOperation
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise AvailabilityError("Price must be an amount in ringgit, like 35.00.")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        raise AvailabilityError("Price must be an amount in ringgit, like 35.00.") from None
    if not amount.is_finite() or amount < 0 or amount > 100_000 or amount != amount.quantize(Decimal("0.01")):
        raise AvailabilityError("Price must be from RM 0.00 to RM 100,000.00, in sen.")
    return int(amount * 1_000_000)


def _package_fields(data):
    fields = {}
    if "name" in data:
        fields["name"] = _text(data["name"], "Name", 80, required=True)
    if "description" in data:
        fields["description"] = _text(data["description"], "Description", 500)
    if "duration_minutes" in data:
        fields["duration_minutes"] = _whole(data["duration_minutes"], "Duration", 5, 1440)
    if "price_mode" in data:
        if data["price_mode"] not in PRICE_MODES:
            raise AvailabilityError("Unknown price rule.")
        fields["price_mode"] = data["price_mode"]
    if "price_myr" in data:
        fields["price_micro_myr"] = _price_micro(data["price_myr"])
    if "seats_per_slot" in data:
        fields["seats_per_slot"] = _whole(data["seats_per_slot"], "Seats", 1, 1000)
    for flag in ("seats_by_party", "enabled"):
        if flag in data:
            if type(data[flag]) is not bool:
                raise AvailabilityError(f"{flag} must be true or false.")
            fields[flag] = data[flag]
    if "sort_order" in data:
        fields["sort_order"] = _whole(data["sort_order"], "Order", -1000, 1000)
    return fields


def _settle_price(fields, current=None):
    """A fixed or per-person price needs an amount; none and quote keep no amount."""
    merged = dict(current or {}, **fields)
    if merged.get("price_mode") in ("fixed", "per_person"):
        if merged.get("price_micro_myr") is None:
            raise AvailabilityError("Enter the price for this package.")
    elif "price_mode" in fields or "price_micro_myr" in fields:
        fields["price_micro_myr"] = None
    return fields


def get_package(company_id, package_id):
    package = repo.get_package(company_id, package_id) if type(package_id) is int else None
    if not package:
        raise AvailabilityNotFound("Package not found.")
    return package


def create_package(company_id, chatbot_id, data):
    require_enabled(company_id)
    if len(repo.list_packages(company_id, chatbot_id)) >= MAX_PACKAGES:
        raise AvailabilityError(f"A chatbot can have up to {MAX_PACKAGES} packages.")
    fields = {"price_mode": "none", "seats_per_slot": 1, "seats_by_party": False, "enabled": True,
              "sort_order": 0, **_package_fields(data)}
    if "name" not in fields or "duration_minutes" not in fields:
        raise AvailabilityError("A package needs a name and a duration.")
    _settle_price(fields)
    return repo.create_package(dict(fields, company_id=company_id, chatbot_id=chatbot_id))


def update_package(company_id, package_id, expected_version, data):
    require_enabled(company_id)
    current = get_package(company_id, package_id)
    changes = _settle_price(_package_fields(data), current)
    if not changes:
        raise AvailabilityError("Nothing to change.")
    updated = repo.update_package(company_id, package_id, expected_version, changes)
    if updated is None:
        raise AvailabilityConflict("This package was changed by someone else. Reload and try again.")
    if {"duration_minutes", "seats_per_slot", "enabled"} & set(changes):
        _regenerate(company_id, current["chatbot_id"], package_id)
    return updated


def _regenerate(company_id, chatbot_id, package_id):
    """Rebuild the package's future open, unbooked weekly times. Booked and closed times are
    never touched, so a time the owner closed stays closed."""
    now = _now()
    repo.delete_future_unbooked_schedule_slots(company_id, chatbot_id, package_id, now.isoformat())
    generate_slots(company_id, chatbot_id, now)


def _hour_block(block):
    if not isinstance(block, dict):
        raise AvailabilityError("Each opening-hours row needs a weekday, start, end and interval.")
    weekday = _whole(block.get("weekday"), "Weekday", 1, 7)
    start, end = block.get("start"), block.get("end")
    if not (isinstance(start, str) and _HHMM.fullmatch(start) and isinstance(end, str) and _HHMM.fullmatch(end)):
        raise AvailabilityError("Opening hours must be written like 09:30.")
    if end <= start:
        raise AvailabilityError("Closing time must be after opening time.")
    interval = _whole(block.get("interval_minutes"), "Interval", 5, 1440)
    return weekday, start, end, interval


def replace_weekly_hours(company_id, package_id, hours):
    require_enabled(company_id)
    package = get_package(company_id, package_id)
    if not isinstance(hours, list) or len(hours) > MAX_HOUR_BLOCKS:
        raise AvailabilityError(f"Send up to {MAX_HOUR_BLOCKS} opening-hours rows.")
    rows = [{"company_id": company_id, "chatbot_id": package["chatbot_id"], "package_id": package_id,
             "weekday": weekday, "start_time": start, "end_time": end, "interval_minutes": interval}
            for weekday, start, end, interval in map(_hour_block, hours)]
    repo.replace_schedules(company_id, package["chatbot_id"], package_id, rows)
    _regenerate(company_id, package["chatbot_id"], package_id)
    return rows


def _local_moment(text):
    if not isinstance(text, str) or not _LOCAL_MOMENT.fullmatch(text.strip()):
        raise AvailabilityError("Give the date and time like 2026-10-10 15:00 (Malaysia time).")
    try:
        return datetime.fromisoformat(text.strip().replace(" ", "T")).replace(tzinfo=MYT).astimezone(timezone.utc)
    except ValueError:
        raise AvailabilityError("That date and time does not exist.") from None


def add_one_off_slot(company_id, package_id, starts_at, capacity=None):
    require_enabled(company_id)
    package = get_package(company_id, package_id)
    moment, now = _local_moment(starts_at), _now()
    if not now < moment <= now + timedelta(days=365):
        raise AvailabilityError("Choose a time in the next 12 months.")
    seats = package["seats_per_slot"] if capacity is None else _whole(capacity, "Seats", 1, 1000)
    slot = repo.create_slot({
        "company_id": company_id, "chatbot_id": package["chatbot_id"], "package_id": package_id,
        "starts_at": moment.isoformat(),
        "ends_at": (moment + timedelta(minutes=package["duration_minutes"])).isoformat(),
        "capacity": seats, "source": "one_off"})
    if slot is None:
        raise AvailabilityConflict("This package already has a time then.")
    return slot


def update_slot(company_id, chatbot_id, slot_id, expected_version, data):
    require_enabled(company_id)
    current = repo.get_slot(company_id, chatbot_id, slot_id) if type(slot_id) is int else None
    if not current:
        raise AvailabilityNotFound("Time not found.")
    changes = {}
    if "capacity" in data:
        changes["capacity"] = _whole(data["capacity"], "Seats", 1, 1000)
        if changes["capacity"] < current["booked_seats"]:
            raise AvailabilityError(f"{current['booked_seats']} seats are already booked at this time.")
    if "status" in data:
        if data["status"] not in ("open", "closed"):
            raise AvailabilityError("A time is either open or closed.")
        changes["status"] = data["status"]
    if not changes:
        raise AvailabilityError("Nothing to change.")
    updated = repo.update_slot(company_id, slot_id, expected_version, changes)
    if updated is None:
        raise AvailabilityConflict("This time was changed by someone else. Reload and try again.")
    return updated


def _day_bounds(day):
    start = datetime.combine(day, time(0), MYT)
    return start.astimezone(timezone.utc).isoformat(), (start + timedelta(days=1)).astimezone(timezone.utc).isoformat()


def add_closure(company_id, chatbot_id, closed_on, package_id=None, reason=None):
    require_enabled(company_id)
    if not isinstance(closed_on, str) or not _DATE.fullmatch(closed_on):
        raise AvailabilityError("Give the date like 2026-10-05.")
    try:
        day = datetime.strptime(closed_on, "%Y-%m-%d").date()
    except ValueError:
        raise AvailabilityError("That date does not exist.") from None
    if day < _now().astimezone(MYT).date():
        raise AvailabilityError("Choose today or a later date.")
    if package_id is not None and get_package(company_id, package_id)["chatbot_id"] != chatbot_id:
        raise AvailabilityNotFound("Package not found.")
    closure = repo.add_closure({"company_id": company_id, "chatbot_id": chatbot_id, "package_id": package_id,
                                "closed_on": day.isoformat(), "reason": _text(reason, "Reason", 120)})
    if closure is None:
        raise AvailabilityConflict("That date is already closed.")
    repo.close_slots_between(company_id, chatbot_id, *_day_bounds(day), package_id=package_id)
    return closure


def remove_closure(company_id, closure_id):
    """Reopen a closed date: its weekly times open again (one-off times stay as the owner left them)."""
    require_enabled(company_id)
    closure = repo.delete_closure(company_id, closure_id) if type(closure_id) is int else None
    if not closure:
        raise AvailabilityNotFound("Closed date not found.")
    company_id, chatbot_id = closure["company_id"], closure["chatbot_id"]
    day = datetime.strptime(str(closure["closed_on"]), "%Y-%m-%d").date()
    remaining = [c for c in repo.list_closures(company_id, chatbot_id, day.isoformat())
                 if str(c["closed_on"]) == day.isoformat()]
    if any(c.get("package_id") is None for c in remaining):
        return closure  # the whole chatbot is still closed that day
    bounds = _day_bounds(day)
    repo.reopen_schedule_slots_between(company_id, chatbot_id, *bounds, package_id=closure.get("package_id"))
    for other in remaining:  # packages still closed that day stay closed
        repo.close_slots_between(company_id, chatbot_id, *bounds, package_id=other["package_id"])
    generate_slots(company_id, chatbot_id, _now())  # times skipped while the date was closed
    return closure


def overview(company_id, chatbot_id, bot):
    """Everything the owner's Availability tab shows for one chatbot."""
    require_enabled(company_id)
    now = _now()
    packages = repo.list_packages(company_id, chatbot_id)
    enabled = [p for p in packages if p.get("enabled")]
    if enabled:
        _top_up(company_id, chatbot_id, now, enabled)
    published = (bot or {}).get("industry_template_published")
    industry = published.get("template_id") if isinstance(published, dict) else None
    return {
        "packages": packages,
        "hours": repo.list_schedules_for_chatbot(company_id, chatbot_id),
        "closures": repo.list_closures(company_id, chatbot_id, now.astimezone(MYT).date().isoformat()),
        "slots": repo.list_slots(company_id, chatbot_id, now.isoformat(), (now + timedelta(days=PROMPT_DAYS)).isoformat()),
        "industry": industry or "general",
        "defaults": defaults_for(industry),
        "auto_confirm": (bot or {}).get("booking_auto_confirm") is not False,
    }


def set_auto_confirm(company_id, chatbot_id, enabled):
    require_enabled(company_id)
    if type(enabled) is not bool:
        raise AvailabilityError("auto_confirm must be true or false.")
    if not repo.set_auto_confirm(company_id, chatbot_id, enabled):
        raise AvailabilityNotFound("Chatbot not found.")
    return enabled


def next_time_labels(company_id, chatbot_id, package_id=None, *, now=None, count=3,
                     exclude=None, party_size=1, after=None):
    """Button labels for the next open times, earliest first: of one package when given,
    never the refused time `exclude`, with room for the party when each person takes a
    seat, and from `after` onwards when there are any (else from now)."""
    times = [t for t in open_slots(company_id, chatbot_id, now=now or _now(), days=PROMPT_DAYS)
             if (package_id is None or t["package_id"] == package_id) and t["slot_id"] != exclude
             and (not t["seats_by_party"] or t["seats_left"] >= party_size)]
    if after is not None:
        times = [t for t in times if _utc(t["starts_at"]) >= after] or times
    return [time_label(t["starts_at"]) for t in times[:count]]
