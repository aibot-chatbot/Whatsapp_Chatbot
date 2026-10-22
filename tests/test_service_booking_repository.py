"""The booking repository scopes every read and write to the company, and guards updates by version.

The supabase query builder is replaced by a recorder, so these tests observe exactly which
filters reach the database.
"""

from unittest.mock import Mock

import pytest

from app.database import service_booking_repository as repo


class Recorder:
    """Stands in for the supabase query builder: records each call, chains, ends at execute()."""

    def __init__(self, data=None, count=None, error=None):
        self.calls = []
        self._data, self._count, self._error = data, count, error

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return call

    def execute(self):
        if self._error is not None:
            raise self._error
        return type("Response", (), {"data": self._data, "count": self._count})()

    def eq_filters(self):
        return {args for name, args, _ in self.calls if name == "eq"}

    def called(self, name):
        return [(args, kwargs) for n, args, kwargs in self.calls if n == name]


class PagedRecorder(Recorder):
    """A table of `rows` behind a server that never returns more than `max_rows` per response."""

    def __init__(self, rows, max_rows=1000):
        super().__init__()
        self.rows, self.max_rows, self.executions = rows, max_rows, 0

    def execute(self):
        self.executions += 1
        start, end = next(args for name, args, _ in reversed(self.calls) if name == "range")
        page = self.rows[start:end + 1][:self.max_rows]
        if self.executions == 1 and getattr(self, "insert_after_first", False):
            self.rows.insert(0, {"id": 99_999})  # a new booking lands while the file is being read
        return type("Response", (), {"data": page, "count": len(self.rows)})()


def newest_first(count):
    return [{"id": count - index} for index in range(count)]


@pytest.fixture
def db(monkeypatch):
    def install(recorder=None, **kwargs):
        recorder = recorder or Recorder(**kwargs)
        monkeypatch.setattr(repo, "supabase", Mock(table=Mock(return_value=recorder)))
        return recorder
    return install


def test_get_booking_is_scoped_to_the_company(db):
    recorder = db(data=[{"id": 9, "company_id": 42}])

    assert repo.get_booking(42, 9) == {"id": 9, "company_id": 42}
    assert {("company_id", 42), ("id", 9)} <= recorder.eq_filters()


@pytest.mark.parametrize("company_id,booking_id", [(0, 9), (42, 0), (None, 9), (42, None), ("42", 9), (True, 9)])
def test_get_booking_with_a_bad_id_never_queries(db, company_id, booking_id):
    recorder = db(data=[{"id": 9}])

    assert repo.get_booking(company_id, booking_id) is None
    assert recorder.calls == []


def test_list_is_scoped_filtered_newest_first_and_capped(db):
    recorder = db(data=[])

    repo.list_bookings(42, chatbot_id=7, status="requested", limit=10_000, offset=40)

    assert {("company_id", 42), ("chatbot_id", 7), ("status", "requested")} <= recorder.eq_filters()
    assert recorder.called("order")[0][0] == ("created_at",)
    assert recorder.called("range")[0][0] == (40, 40 + repo.MAX_PAGE - 1), "limit is capped at MAX_PAGE"


def test_list_without_optional_filters_still_scopes_the_company(db):
    recorder = db(data=[])

    repo.list_bookings(42)

    assert recorder.eq_filters() == {("company_id", 42)}


def test_csv_listing_is_scoped_and_ordered_newest_first(db):
    recorder = db(data=[])

    assert repo.list_bookings_for_csv(42, 5000) == []

    assert recorder.eq_filters() == {("company_id", 42)}
    assert [args for args, _ in recorder.called("order")] == [("created_at",), ("id",)]
    assert len(recorder.called("range")) == 1, "an empty company costs one query"


def test_csv_listing_for_one_chatbot_filters_every_page_to_it(db):
    recorder = db(PagedRecorder(newest_first(1500), max_rows=1000))

    repo.list_bookings_for_csv(42, 5000, chatbot_id=7)

    pages = len(recorder.called("range"))
    assert pages >= 2, "the read spans more than one page"
    assert recorder.eq_filters() == {("company_id", 42), ("chatbot_id", 7)}
    assert len(recorder.called("eq")) == 2 * pages, "both filters on every page"


def test_csv_listing_reads_every_page_despite_the_servers_response_cap(db):
    recorder = db(PagedRecorder(newest_first(2500), max_rows=1000))

    rows = repo.list_bookings_for_csv(42, 5000)

    assert [row["id"] for row in rows] == list(range(2500, 0, -1)), "complete and in order"
    assert recorder.called("range")[0][0] == (0, 999)
    assert recorder.eq_filters() == {("company_id", 42)}, "every page stays scoped to the company"


def test_csv_listing_stops_at_the_requested_number_of_rows(db):
    db(PagedRecorder(newest_first(2500)))

    rows = repo.list_bookings_for_csv(42, 1500)

    assert [row["id"] for row in rows] == list(range(2500, 1000, -1))


def test_csv_listing_survives_a_server_cap_smaller_than_the_page(db):
    db(PagedRecorder(newest_first(700), max_rows=300))

    assert len(repo.list_bookings_for_csv(42, 5000)) == 700


def test_csv_listing_never_repeats_a_row_when_a_booking_arrives_mid_read(db):
    recorder = PagedRecorder(newest_first(1500))
    recorder.insert_after_first = True
    db(recorder)

    rows = repo.list_bookings_for_csv(42, 5000)

    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)) == 1500


def test_csv_listing_refuses_a_bad_company_without_querying(db):
    recorder = db(data=[])

    with pytest.raises(ValueError):
        repo.list_bookings_for_csv(None, 100)
    assert recorder.calls == []


def test_update_is_guarded_by_company_and_version(db):
    recorder = db(data=[{"id": 9, "version": 4}])

    row = repo.update_booking(42, 9, 3, {"status": "confirmed"})

    assert row == {"id": 9, "version": 4}
    assert {("company_id", 42), ("id", 9), ("version", 3)} <= recorder.eq_filters()
    payload = recorder.called("update")[0][0][0]
    assert payload["status"] == "confirmed" and payload["version"] == 4 and "updated_at" in payload


def test_a_stale_version_updates_nothing(db):
    db(data=[])  # no row matched company + id + version

    assert repo.update_booking(42, 9, 3, {"status": "confirmed"}) is None


@pytest.mark.parametrize("forbidden", ["company_id", "chatbot_id", "id", "created_at", "intake_key",
                                       "conversation_id", "source", "version"])
def test_ownership_and_identity_fields_cannot_be_updated(db, forbidden):
    recorder = db(data=[{"id": 9}])

    with pytest.raises(ValueError):
        repo.update_booking(42, 9, 3, {"status": "confirmed", forbidden: 1})

    assert recorder.calls == []


def test_create_returns_the_inserted_row(db):
    db(data=[{"id": 1}])

    assert repo.create_booking({"company_id": 42}) == {"id": 1}


def test_create_returns_none_for_a_duplicate_intake_key(db):
    error = Exception('duplicate key value violates unique constraint "service_bookings_intake_unique"')
    error.code = "23505"
    db(error=error)

    assert repo.create_booking({"company_id": 42, "intake_key": "k"}) is None


def test_create_does_not_swallow_a_unique_violation_on_anything_else(db):
    error = Exception('duplicate key value violates unique constraint "service_bookings_pkey"')
    error.code = "23505"
    db(error=error)

    with pytest.raises(Exception, match="service_bookings_pkey"):
        repo.create_booking({"company_id": 42, "intake_key": "k"})


def test_create_raises_for_any_other_database_error(db):
    db(error=RuntimeError("connection reset"))

    with pytest.raises(RuntimeError):
        repo.create_booking({"company_id": 42})


def test_intake_key_lookup_is_company_scoped(db):
    recorder = db(data=[{"id": 3}])

    assert repo.get_booking_by_intake_key(42, "abc") == {"id": 3}
    assert {("company_id", 42), ("intake_key", "abc")} <= recorder.eq_filters()


def test_recent_count_is_scoped_to_company_and_conversation(db):
    recorder = db(data=[], count=2)

    assert repo.count_recent_for_conversation(42, 55, "2026-10-01T00:00:00+00:00") == 2
    assert {("company_id", 42), ("conversation_id", 55)} <= recorder.eq_filters()
    assert recorder.called("gte")[0][0] == ("created_at", "2026-10-01T00:00:00+00:00")


def test_recent_count_treats_a_missing_count_as_zero(db):
    db(data=[], count=None)

    assert repo.count_recent_for_conversation(42, 55, "2026-10-01T00:00:00+00:00") == 0


def test_company_count_spans_conversations_but_only_this_company_and_source(db):
    recorder = db(data=[], count=7)

    assert repo.count_recent_for_company(42, "2026-10-01T00:00:00+00:00") == 7
    assert recorder.eq_filters() == {("company_id", 42), ("source", "chat")}, "no conversation filter"
    assert recorder.called("gte")[0][0] == ("created_at", "2026-10-01T00:00:00+00:00")


def test_company_count_can_be_bounded_to_rows_created_before_a_moment(db):
    recorder = db(data=[], count=1)

    repo.count_recent_for_company(42, "2026-10-01T04:00:00+00:00", before_iso="2026-10-01T04:05:00+00:00")

    assert recorder.called("gte")[0][0] == ("created_at", "2026-10-01T04:00:00+00:00")
    assert recorder.called("lt")[0][0] == ("created_at", "2026-10-01T04:05:00+00:00")


def test_company_count_without_a_bound_adds_no_upper_filter(db):
    recorder = db(data=[], count=1)

    repo.count_recent_for_company(42, "2026-10-01T04:00:00+00:00")

    assert recorder.called("lt") == []


def test_company_count_treats_a_missing_count_as_zero(db):
    db(data=[], count=None)

    assert repo.count_recent_for_company(42, "2026-10-01T00:00:00+00:00") == 0


def test_toggle_updates_only_that_companys_chatbot(db):
    recorder = db(data=[{"id": 7}])

    assert repo.set_intake_enabled(42, 7, True) is True
    assert {("company_id", 42), ("id", 7)} <= recorder.eq_filters()
    assert recorder.called("update")[0][0][0] == {"booking_intake_enabled": True}


def test_toggle_reports_false_when_the_chatbot_is_not_theirs(db):
    db(data=[])

    assert repo.set_intake_enabled(42, 7, True) is False
