"""Supabase boundary of workspace deletion, against an in-memory PostgREST stand-in.

The stand-in applies eq / in_ / order / range for real, so the pagination test
fails if the code stops paging (PostgREST silently truncates at 1000 rows).
"""

from unittest.mock import Mock

import pytest

from app.database import account_deletion_repository as repo


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.mode, self.payload, self.filters = "select", None, []
        self.sort, self.window, self.limit_n, self.on_conflict = None, None, None, None

    def select(self, columns):
        self.mode, self.columns = "select", columns
        return self

    def upsert(self, payload, on_conflict=None):
        self.mode, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload):
        self.mode, self.payload = "update", payload
        return self

    def delete(self):
        self.mode = "delete"
        return self

    def eq(self, column, value):
        self.filters.append(lambda row: row.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda row: row.get(column) in values)
        return self

    def order(self, column):
        self.sort = column
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def limit(self, count):
        self.limit_n = count
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        self.db.log.append((self.table, self.mode, self.payload, self.on_conflict))
        if self.mode == "upsert":
            rows[:] = [r for r in rows if r.get(self.on_conflict) != self.payload.get(self.on_conflict)] + [self.payload]
            return Mock(data=[self.payload])
        matched = [r for r in rows if all(f(r) for f in self.filters)]
        if self.mode == "update":
            for row in matched:
                row.update(self.payload)
            return Mock(data=matched)
        if self.mode == "delete":
            rows[:] = [r for r in rows if r not in matched]
            return Mock(data=matched)
        if self.sort:
            matched.sort(key=lambda r: r[self.sort])
        if self.window:
            matched = matched[self.window[0]:self.window[1] + 1]
        if self.limit_n is not None:
            matched = matched[:self.limit_n]
        return Mock(data=[dict(r) for r in matched])


class FakeSupabase:
    def __init__(self):
        self.tables, self.log, self.rpcs, self.rpc_data = {}, [], [], None

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        return Mock(execute=lambda: Mock(data=self.rpc_data))


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(repo, "supabase", db)
    return db


@pytest.mark.parametrize("data,expected", [
    ("not_owner", "not_owner"), (["payment_history"], "payment_history"),
    (None, None), ([], None), ([None], None),
])
def test_the_blocker_is_read_from_a_scalar_or_a_one_row_list(fake, data, expected):
    fake.rpc_data = data

    assert repo.get_deletion_blocker(42, 7) == expected
    assert fake.rpcs == [("account_deletion_blocker", {"p_company_id": 42, "p_user_id": 7})]


@pytest.mark.parametrize("data", ["", 42, {"code": "x"}, [42], True])
def test_an_answer_the_blocker_never_gives_fails_closed_instead_of_reading_as_eligible(fake, data):
    fake.rpc_data = data

    with pytest.raises(ValueError):
        repo.get_deletion_blocker(42, 7)


@pytest.mark.parametrize("data,expected", [
    ({"status": "success"}, {"status": "success"}), ([{"status": "error", "code": "x"}], {"status": "error", "code": "x"}),
    ([], None), (None, None),
])
def test_the_deletion_verdict_is_returned_whole(fake, data, expected):
    fake.rpc_data = data

    assert repo.delete_company_account_rpc(42, 7) == expected
    assert fake.rpcs == [("delete_company_account", {"p_company_id": 42, "p_user_id": 7})]


def test_a_new_code_replaces_the_old_one_and_resets_attempts(fake):
    repo.upsert_deletion_code(7, "hash-one", "2026-10-17T09:10:00+00:00")
    for seen in range(3):
        assert repo.claim_deletion_code_attempt(7, "hash-one", seen)
    repo.upsert_deletion_code(7, "hash-two", "2026-10-17T09:20:00+00:00")

    row = repo.get_deletion_code(7)
    assert row["code_hash"] == "hash-two" and row["attempts"] == 0
    assert fake.log[0][3] == "user_id", "upsert on the primary key"
    assert len(fake.tables["account_deletion_codes"]) == 1


def test_codes_are_per_user(fake):
    repo.upsert_deletion_code(7, "seven", "2026-10-17T09:10:00+00:00")
    repo.upsert_deletion_code(8, "eight", "2026-10-17T09:10:00+00:00")

    repo.delete_deletion_code(7)

    assert repo.get_deletion_code(7) is None
    assert repo.get_deletion_code(8)["code_hash"] == "eight"


def test_an_attempt_claim_is_a_compare_and_swap_on_the_count_and_the_code(fake):
    repo.upsert_deletion_code(7, "a", "2026-10-17T09:10:00+00:00")
    repo.upsert_deletion_code(8, "b", "2026-10-17T09:10:00+00:00")

    assert repo.claim_deletion_code_attempt(8, "b", 0) is True
    assert repo.claim_deletion_code_attempt(8, "b", 0) is False, "a second guess that read the same count loses"
    assert repo.claim_deletion_code_attempt(8, "replaced-code", 1) is False, "a replaced code cannot be charged"

    assert repo.get_deletion_code(7)["attempts"] == 0, "only the named user's code is charged"
    assert repo.get_deletion_code(8)["attempts"] == 1


def test_storage_listing_pages_past_the_postgrest_row_cap_and_stays_in_the_company(fake, monkeypatch):
    monkeypatch.setattr(repo, "PAGE_SIZE", 3)
    monkeypatch.setattr(repo, "CHATBOT_ID_CHUNK", 2)
    fake.tables["chatbots"] = [{"id": i, "company_id": 42} for i in range(1, 6)] + [{"id": 99, "company_id": 7}]
    fake.tables["knowledge_files"] = (
        [{"id": 100 + i, "chatbot_id": 1 + i % 5, "file_name": f"f{i}.pdf", "file_path": f"data/f{i}.pdf"} for i in range(8)]
        + [{"id": 900, "chatbot_id": 99, "file_name": "other.pdf", "file_path": "data/other.pdf"}]
    )
    fake.tables["bot_media_attachments"] = (
        [{"id": 200 + i, "chatbot_id": 1 + i % 5, "media_url": f"https://x/media/m{i}.png"} for i in range(7)]
        + [{"id": 901, "chatbot_id": 99, "media_url": "https://x/media/other.png"}]
    )

    found = repo.list_company_storage_files(42)

    assert sorted(r["id"] for r in found["knowledge"]) == [100 + i for i in range(8)]
    assert sorted(r["id"] for r in found["media"]) == [200 + i for i in range(7)]
    assert all(r["chatbot_id"] != 99 for r in found["knowledge"] + found["media"])


def test_a_company_with_no_chatbots_lists_nothing_and_queries_nothing_else(fake):
    fake.tables["chatbots"] = []

    assert repo.list_company_storage_files(42) == {"knowledge": [], "media": []}
    assert {entry[0] for entry in fake.log} == {"chatbots"}
