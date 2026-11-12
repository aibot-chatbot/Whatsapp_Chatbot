"""Self-service workspace deletion: eligibility, confirmation code, deletion, cleanup.

Everything external is replaced: the repository (Supabase), the email sender and
the document store. The seams under test are the service's own decisions -
who may delete, how a code is issued and checked, how the database verdict is
mapped, and that storage cleanup can never fail the request.
"""

import datetime
import hashlib
import hmac
import logging
import os
import re
import threading
from pathlib import Path

import pytest

from app.services import account_deletion_service as svc
from app.services import document_storage_service as document_storage

REAL_START_BACKGROUND = svc._start_background
NOW = datetime.datetime(2026, 10, 17, 9, 0, 0, tzinfo=datetime.timezone.utc)
OWNER = {"id": 7, "company_id": 42, "email": "owner@example.test", "full_name": "Olivia Owner"}


class Wiring:
    """Records every outbound call so tests can assert order and absence."""

    def __init__(self):
        self.calls = []
        self.blocker = None
        self.code_row = None
        self.email_ok = True
        self.rpc_result = {"status": "success", "code": "deleted", "message": "ok",
                           "deleted_counts": {"users": 2, "chatbots": 1}}
        self.rpc_error = None
        self.storage = {"knowledge": [], "media": []}
        self.storage_error = None
        self.delete_errors = {}
        self.sent_codes = []
        self.claim_lost = False
        self.tree_errors = {}
        self.lock = threading.Lock()
        self.monkeypatch = None

    def log(self, name, *args):
        self.calls.append((name, *args))


@pytest.fixture
def wiring(monkeypatch):
    w = Wiring()
    w.monkeypatch = monkeypatch
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-for-account-deletion-codes")
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    # Cleanup runs on a daemon thread in production; tests run it inline so they can see it.
    monkeypatch.setattr(svc, "_start_background", lambda target: target())

    def blocker(company_id, user_id):
        w.log("blocker", company_id, user_id)
        return w.blocker

    def upsert(user_id, code_hash, expires_at):
        w.log("upsert", user_id, code_hash, expires_at)
        w.code_row = {"user_id": user_id, "code_hash": code_hash, "expires_at": expires_at, "attempts": 0}

    def get_code(user_id):
        w.log("get_code", user_id)
        return dict(w.code_row) if w.code_row else None

    def claim(user_id, code_hash, seen_attempts):
        # Atomic like the real conditional UPDATE: one winner per (code, count).
        with w.lock:
            w.log("claim", user_id, seen_attempts)
            row = w.code_row
            if w.claim_lost or not row or row["code_hash"] != code_hash or row["attempts"] != seen_attempts:
                return False
            w.code_row = {**row, "attempts": seen_attempts + 1}
            return True

    def delete_code(user_id):
        w.log("delete_code", user_id)
        w.code_row = None

    def list_files(company_id):
        w.log("list_files", company_id)
        if w.storage_error:
            raise w.storage_error
        return w.storage

    def rpc(company_id, user_id):
        w.log("rpc", company_id, user_id)
        if w.rpc_error:
            raise w.rpc_error
        return w.rpc_result

    def send(recipient_email, otp_code, recipient_name="User", company_name=None):
        w.log("email", recipient_email, otp_code, recipient_name, company_name)
        w.sent_codes.append(otp_code)
        return w.email_ok

    def delete_file(path, *, root, namespace):
        w.log("delete_file", path, root, namespace)
        error = w.delete_errors.get(os.path.basename(path))
        if error:
            raise error

    monkeypatch.setattr(svc, "get_deletion_blocker", blocker)
    monkeypatch.setattr(svc, "upsert_deletion_code", upsert)
    monkeypatch.setattr(svc, "get_deletion_code", get_code)
    monkeypatch.setattr(svc, "claim_deletion_code_attempt", claim)
    monkeypatch.setattr(svc, "delete_deletion_code", delete_code)
    monkeypatch.setattr(svc, "list_company_storage_files", list_files)
    monkeypatch.setattr(svc, "delete_company_account_rpc", rpc)
    monkeypatch.setattr(svc, "send_account_deletion_code_email", send)
    monkeypatch.setattr(svc, "get_company_by_id", lambda company_id: {"id": company_id, "company_name": "Acme Sdn Bhd"})
    def delete_tree(directory, *, root, namespace):
        w.log("delete_tree", Path(directory), Path(root), namespace)
        error = w.tree_errors.get(namespace)
        if error:
            raise error

    monkeypatch.setattr(svc.document_storage, "delete_file", delete_file)
    monkeypatch.setattr(svc.document_storage, "delete_tree", delete_tree)
    return w


def issue_code(w, code="123456"):
    """Request a code with a fixed random draw and return the plain code."""
    w.monkeypatch.setattr(svc.secrets, "randbelow", lambda n: int(code))
    svc.request_deletion_code(OWNER)
    return code


def names(w):
    return [call[0] for call in w.calls]


# ---------------------------------------------------------------- eligibility

def test_owner_of_an_unblocked_workspace_is_eligible(wiring):
    status = svc.get_deletion_status(OWNER)

    assert status == {"eligible": True, "reason_code": None, "is_owner": True, "company_name": "Acme Sdn Bhd"}
    assert ("blocker", 42, 7) in wiring.calls


def test_a_non_owner_is_not_eligible_and_not_the_owner(wiring):
    wiring.blocker = "not_owner"

    status = svc.get_deletion_status(OWNER)

    assert status["eligible"] is False
    assert status["is_owner"] is False
    assert status["reason_code"] == "not_owner"


@pytest.mark.parametrize("reason", ["payment_history", "protected", "support_records"])
def test_each_block_reason_is_reported_to_the_owner_with_a_stable_code(wiring, reason):
    wiring.blocker = reason

    status = svc.get_deletion_status(OWNER)

    assert status["eligible"] is False
    assert status["is_owner"] is True
    assert status["reason_code"] == reason


def test_a_user_who_no_longer_belongs_to_the_company_is_not_found(wiring):
    wiring.blocker = "not_found"

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.get_deletion_status(OWNER)

    assert caught.value.code == "not_found"
    assert caught.value.status_code == 404


def test_an_unknown_blocker_fails_closed(wiring):
    wiring.blocker = "something_new"

    status = svc.get_deletion_status(OWNER)

    assert status["eligible"] is False
    assert status["reason_code"] == "something_new"


# ------------------------------------------------------------------ request code

def test_requesting_a_code_stores_only_a_hash_and_emails_the_plain_code(wiring):
    code = issue_code(wiring, "123456")

    stored = wiring.code_row
    assert stored["code_hash"] != code
    assert code not in repr(stored)
    assert re.fullmatch(r"[0-9a-f]{64}", stored["code_hash"])
    assert stored["code_hash"] == svc.hash_code(7, code)
    assert wiring.sent_codes == ["123456"]
    assert ("email", "owner@example.test", "123456", "Olivia Owner", "Acme Sdn Bhd") in wiring.calls


def test_code_is_six_digits_and_keeps_leading_zeros(wiring):
    code = issue_code(wiring, "000042")

    assert wiring.sent_codes == ["000042"]
    assert len(code) == 6


def test_code_comes_from_the_secrets_module_over_a_million_values(wiring, monkeypatch):
    draws = []
    monkeypatch.setattr(svc.secrets, "randbelow", lambda n: draws.append(n) or 5)

    svc.request_deletion_code(OWNER)

    assert draws == [1_000_000]
    assert wiring.sent_codes == ["000005"]


def test_code_expires_in_ten_minutes(wiring):
    issue_code(wiring)

    expires = datetime.datetime.fromisoformat(wiring.code_row["expires_at"])
    assert expires == NOW + datetime.timedelta(minutes=10)


def test_a_blocked_workspace_gets_no_code_and_no_email(wiring):
    wiring.blocker = "payment_history"

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.request_deletion_code(OWNER)

    assert caught.value.code == "payment_history"
    assert caught.value.status_code == 409
    assert "upsert" not in names(wiring)
    assert "email" not in names(wiring)


def test_a_non_owner_gets_forbidden_and_no_code(wiring):
    wiring.blocker = "not_owner"

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.request_deletion_code(OWNER)

    assert caught.value.code == "not_owner"
    assert caught.value.status_code == 403
    assert "email" not in names(wiring)


def test_a_failed_email_removes_the_code_so_it_cannot_be_guessed_later(wiring):
    wiring.email_ok = False

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.request_deletion_code(OWNER)

    assert caught.value.code == "email_unavailable"
    assert caught.value.status_code == 503
    assert wiring.code_row is None


# ----------------------------------------------------------------------- hashing

def test_hash_is_an_hmac_bound_to_the_user_and_the_server_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-one-for-hash-tests-0123456789")
    first = svc.hash_code(7, "123456")

    assert first == svc.hash_code(7, "123456")
    assert first != svc.hash_code(8, "123456"), "a code must not verify for another user"
    assert first != svc.hash_code(7, "123457")
    monkeypatch.setenv("JWT_SECRET", "secret-two-for-hash-tests-0123456789")
    assert first != svc.hash_code(7, "123456"), "without the server secret the hash cannot be recomputed"


def test_hash_is_not_a_bare_sha256_of_the_code(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "secret-one-for-hash-tests-0123456789")

    assert svc.hash_code(7, "123456") != hashlib.sha256(b"123456").hexdigest()


# --------------------------------------------------------------------- confirmation

def test_the_right_code_deletes_the_workspace(wiring):
    code = issue_code(wiring)

    result = svc.confirm_deletion(OWNER, code)

    assert result["status"] == "success"
    assert ("rpc", 42, 7) in wiring.calls


def test_the_code_is_compared_in_constant_time(wiring, monkeypatch):
    code = issue_code(wiring)
    stored = wiring.code_row["code_hash"]
    compared = []
    real = hmac.compare_digest
    monkeypatch.setattr(svc.hmac, "compare_digest", lambda a, b: compared.append((a, b)) or real(a, b))

    svc.confirm_deletion(OWNER, code)

    assert compared == [(stored, stored)], "the stored hash is compared once against the recomputed one"
    assert all(isinstance(a, str) and isinstance(b, str) for a, b in compared)


def test_a_wrong_code_is_rejected_counted_and_deletes_nothing(wiring):
    issue_code(wiring, "123456")

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "654321")

    assert caught.value.code == "code_invalid"
    assert caught.value.status_code == 400
    assert ("claim", 7, 0) in wiring.calls
    assert wiring.code_row["attempts"] == 1
    assert "rpc" not in names(wiring)


def test_the_guess_is_charged_before_it_is_compared(wiring, monkeypatch):
    code = issue_code(wiring)
    real = hmac.compare_digest
    monkeypatch.setattr(svc.hmac, "compare_digest",
                        lambda a, b: wiring.log("compare") or real(a, b))

    svc.confirm_deletion(OWNER, code)

    order = names(wiring)
    assert order.index("claim") < order.index("compare")


def test_a_guess_that_loses_the_attempt_claim_is_never_compared(wiring, monkeypatch):
    code = issue_code(wiring)
    wiring.claim_lost = True
    compared = []
    monkeypatch.setattr(svc.hmac, "compare_digest", lambda a, b: compared.append(1) or True)

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, code)

    assert caught.value.code == "code_invalid"
    assert compared == [], "even a right code is refused when another request spent this attempt"
    assert "rpc" not in names(wiring)


def test_concurrent_guesses_that_read_the_same_count_compare_only_once(wiring, monkeypatch):
    issue_code(wiring, "123456")
    racers = 8
    everyone_has_read = threading.Barrier(racers)
    read_code = svc.get_deletion_code

    def read_then_wait(user_id):
        row = read_code(user_id)
        everyone_has_read.wait(timeout=5)
        return row

    compared, outcomes = [], []
    real = hmac.compare_digest
    monkeypatch.setattr(svc, "get_deletion_code", read_then_wait)
    monkeypatch.setattr(svc.hmac, "compare_digest", lambda a, b: compared.append(1) or real(a, b))

    def guess():
        try:
            svc.confirm_deletion(OWNER, "000000")
        except svc.AccountDeletionError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=guess) for _ in range(racers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert outcomes == ["code_invalid"] * racers
    assert len(compared) == 1, "all eight saw attempts=0; a read-modify-write counter would compare all eight"
    assert wiring.code_row["attempts"] == 1


@pytest.mark.parametrize("bad", [None, "", "12345", "1234567", "abcdef", "12 456", 123456, ["123456"], "１２３４５６"])
def test_a_malformed_code_is_rejected_without_touching_the_database(wiring, bad):
    issue_code(wiring)
    wiring.calls.clear()

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, bad)

    assert caught.value.code == "code_invalid"
    assert names(wiring) == []


def test_the_fifth_wrong_attempt_invalidates_the_code(wiring):
    issue_code(wiring, "123456")
    for _ in range(4):
        with pytest.raises(svc.AccountDeletionError) as caught:
            svc.confirm_deletion(OWNER, "000000")
        assert caught.value.code == "code_invalid"

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "000000")

    assert caught.value.code == "too_many_attempts"
    assert caught.value.status_code == 429
    assert wiring.code_row is None

    with pytest.raises(svc.AccountDeletionError) as after:
        svc.confirm_deletion(OWNER, "123456")
    assert after.value.code == "code_expired", "the correct code no longer works once invalidated"
    assert "rpc" not in names(wiring)


def test_a_code_already_at_the_attempt_limit_is_dead_even_if_correct(wiring):
    issue_code(wiring, "123456")
    wiring.code_row = {**wiring.code_row, "attempts": 5}

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == "too_many_attempts"
    assert wiring.code_row is None
    assert "rpc" not in names(wiring)


def test_a_lockout_is_logged_with_ids_and_nothing_personal(wiring, caplog):
    issue_code(wiring, "123456")
    wiring.code_row = {**wiring.code_row, "attempts": 4}

    with caplog.at_level(logging.WARNING, logger=svc.logger.name), pytest.raises(svc.AccountDeletionError):
        svc.confirm_deletion(OWNER, "000000")

    assert "locked out" in caplog.text and "company 42" in caplog.text and "user 7" in caplog.text
    assert OWNER["email"] not in caplog.text and "000000" not in caplog.text and "123456" not in caplog.text


def test_an_expired_code_is_rejected_and_removed(wiring, monkeypatch):
    issue_code(wiring, "123456")
    monkeypatch.setattr(svc, "_now", lambda: NOW + datetime.timedelta(minutes=10, seconds=1))

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == "code_expired"
    assert wiring.code_row is None
    assert "rpc" not in names(wiring)


def test_a_code_is_still_valid_at_the_last_second(wiring, monkeypatch):
    issue_code(wiring, "123456")
    monkeypatch.setattr(svc, "_now", lambda: NOW + datetime.timedelta(minutes=9, seconds=59))

    assert svc.confirm_deletion(OWNER, "123456")["status"] == "success"


def test_confirming_without_ever_requesting_a_code_is_rejected(wiring):
    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == "code_expired"
    assert "rpc" not in names(wiring)


def test_a_postgrest_timestamp_with_z_suffix_and_microseconds_parses(wiring):
    issue_code(wiring, "123456")
    wiring.code_row = {**wiring.code_row, "expires_at": "2026-10-17T09:05:00.123456Z"}

    assert svc.confirm_deletion(OWNER, "123456")["status"] == "success"


def test_an_unreadable_expiry_fails_closed(wiring):
    issue_code(wiring, "123456")
    wiring.code_row = {**wiring.code_row, "expires_at": "not a date"}

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == "code_expired"
    assert "rpc" not in names(wiring)


def test_a_non_owner_cannot_use_a_code_even_if_one_exists(wiring):
    issue_code(wiring)
    wiring.blocker = "not_owner"
    wiring.calls.clear()

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == "not_owner"
    assert "get_code" not in names(wiring), "an ineligible user must not be able to probe codes"
    assert "rpc" not in names(wiring)


# ------------------------------------------------------------------ rpc verdicts

@pytest.mark.parametrize("code,status", [
    ("not_owner", 403), ("payment_history", 409), ("protected", 409),
    ("support_records", 409), ("not_found", 404),
])
def test_database_refusals_become_errors_with_the_same_code(wiring, code, status):
    issue_code(wiring)
    wiring.rpc_result = {"status": "error", "code": code, "message": "database wording"}

    with pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == code
    assert caught.value.status_code == status
    assert "database wording" not in caught.value.message, "user text is ours, not the database's"


@pytest.mark.parametrize("result", [
    None, {}, {"status": "error"}, {"status": "error", "code": "brand_new_code"}, {"status": "weird"},
])
def test_an_unusable_database_answer_is_a_generic_failure(wiring, result, caplog):
    issue_code(wiring)
    wiring.rpc_result = result

    with caplog.at_level(logging.ERROR, logger=svc.logger.name), pytest.raises(svc.AccountDeletionError) as caught:
        svc.confirm_deletion(OWNER, "123456")

    assert caught.value.code == "deletion_failed"
    assert caught.value.status_code == 500
    assert any("unrecognised verdict" in record.getMessage() for record in caplog.records), \
        "ops must hear about a verdict this code does not know"


def test_a_completed_deletion_leaves_an_audit_line_with_ids_only(wiring, caplog):
    wiring.rpc_result = {**wiring.rpc_result, "chatbot_ids": [5, 9]}
    code = issue_code(wiring)

    with caplog.at_level(logging.INFO, logger=svc.logger.name):
        svc.confirm_deletion(OWNER, code)

    line = next(r.getMessage() for r in caplog.records if "permanently deleted" in r.getMessage())
    assert "Workspace 42" in line and "user 7" in line and "[5, 9]" in line
    assert OWNER["email"] not in caplog.text and OWNER["full_name"] not in caplog.text and code not in caplog.text


def test_a_database_exception_propagates_and_leaves_code_and_storage_alone(wiring):
    issue_code(wiring)
    wiring.storage = {"knowledge": [{"id": 1, "chatbot_id": 5, "file_name": "a.pdf",
                                     "file_path": "data/bot_5_x_a.pdf"}], "media": []}
    wiring.rpc_error = RuntimeError("account_deletion_incomplete: some_table")

    with pytest.raises(RuntimeError):
        svc.confirm_deletion(OWNER, "123456")

    assert "delete_file" not in names(wiring) and "delete_tree" not in names(wiring)
    assert wiring.code_row is not None, "a rolled-back deletion must stay retryable"


def test_a_refused_deletion_touches_no_storage(wiring):
    issue_code(wiring)
    wiring.storage = {"knowledge": [{"id": 1, "chatbot_id": 5, "file_name": "a.pdf",
                                     "file_path": "data/bot_5_x_a.pdf"}], "media": []}
    wiring.rpc_result = {"status": "error", "code": "payment_history", "message": "x"}

    with pytest.raises(svc.AccountDeletionError):
        svc.confirm_deletion(OWNER, "123456")

    assert "delete_file" not in names(wiring) and "delete_tree" not in names(wiring)


# ------------------------------------------------------------------ storage cleanup

def knowledge(file_id, chatbot_id, name, path=None):
    return {"id": file_id, "chatbot_id": chatbot_id, "file_name": name,
            "file_path": path if path is not None else f"data/{name}"}


def media(chatbot_id, name, url=None):
    return {"chatbot_id": chatbot_id, "media_url": url or f"https://app.example.test/media/{name}"}


def deleted(w):
    return [(os.path.basename(c[1]), c[2], c[3]) for c in w.calls if c[0] == "delete_file"]


def test_storage_is_listed_before_and_deleted_after_the_database_deletion(wiring):
    wiring.storage = {"knowledge": [knowledge(1, 5, "bot_5_aaa_menu.pdf")], "media": [media(5, "bot_5_bbb_logo.png")]}
    code = issue_code(wiring)

    svc.confirm_deletion(OWNER, code)

    order = names(wiring)
    assert order.index("list_files") < order.index("rpc") < order.index("delete_file")


def test_knowledge_files_and_their_sidecars_are_removed_from_the_data_folder(wiring):
    wiring.storage = {"knowledge": [knowledge(9, 5, "bot_5_aaa_menu.pdf")], "media": []}
    code = issue_code(wiring)

    svc.confirm_deletion(OWNER, code)

    removed = deleted(wiring)
    assert ("bot_5_aaa_menu.pdf", svc.DATA_FOLDER, "knowledge") in removed
    assert ("bot_5_9_readme.md", svc.DATA_FOLDER, "knowledge") in removed
    assert ("bot_5_9_history.json", svc.DATA_FOLDER, "knowledge") in removed
    assert ("bot_5_readme.md", svc.DATA_FOLDER, "knowledge") in removed
    assert len(removed) == len(set(removed)), "each object is deleted once"


def test_media_files_are_removed_from_the_media_folder(wiring):
    wiring.storage = {"knowledge": [], "media": [media(5, "bot_5_bbb_logo.png")]}
    code = issue_code(wiring)

    svc.confirm_deletion(OWNER, code)

    assert deleted(wiring) == [("bot_5_bbb_logo.png", svc.MEDIA_FOLDER, "media")]


def test_a_media_url_cannot_point_the_cleanup_at_another_tenants_file(wiring):
    wiring.storage = {"knowledge": [], "media": [
        media(5, "x", url="https://app.example.test/media/bot_6_other_secret.png"),
        media(5, "x", url="https://app.example.test/media/../bot_5_up.png"),
        media(5, "x", url="https://app.example.test/static/bot_5_wrong_prefix.png"),
        media(5, "x", url="https://app.example.test/media/bot_55_prefix_trap.png"),
        # Right prefix, then a climb into another tenant's file: only secure_filename stops these.
        media(5, "x", url="https://app.example.test/media/bot_5_x/../bot_6_other_secret.png"),
        media(5, "x", url="https://app.example.test/media/bot_5_x\\..\\bot_6_other_secret.png"),
        media(5, "x", url="https://app.example.test/media/bot_5_x%2F..%2Fbot_6_other_secret.png"),
        media(5, "x", url=""),
        {"chatbot_id": 5, "media_url": None},
    ]}
    code = issue_code(wiring)

    svc.confirm_deletion(OWNER, code)

    assert deleted(wiring) == []


def test_the_workspaces_report_and_pdf_candidate_folders_go_after_the_database(wiring, monkeypatch, tmp_path):
    monkeypatch.setenv("REPORT_STORAGE_ROOT", str(tmp_path / "reports"))
    code = issue_code(wiring)

    svc.confirm_deletion(OWNER, code)

    trees = [call[1:] for call in wiring.calls if call[0] == "delete_tree"]
    assert trees == [
        (tmp_path / "reports" / "42", tmp_path / "reports", "reports"),
        (Path(svc.CANDIDATE_DATA_FOLDER) / "42", Path(svc.DATA_FOLDER), "knowledge"),
    ], "only this workspace's own folders (bookings CSV, analysis exports, PDF candidates)"
    order = names(wiring)
    assert order.index("rpc") < order.index("delete_tree")


def test_a_failed_folder_cleanup_is_logged_and_never_fails_the_request(wiring, caplog):
    wiring.tree_errors["reports"] = document_storage.DocumentStorageError("R2 is down")
    code = issue_code(wiring)

    with caplog.at_level(logging.WARNING, logger=svc.logger.name):
        result = svc.confirm_deletion(OWNER, code)

    assert result["status"] == "success"
    assert "reports folder cleanup failed" in caplog.text
    assert any(call[0] == "delete_tree" and call[3] == "knowledge" for call in wiring.calls), \
        "one failed folder does not stop the next"


def test_a_knowledge_row_cannot_point_the_cleanup_at_another_tenants_file(wiring):
    wiring.storage = {"knowledge": [knowledge(1, 5, "bot_6_other_secret.pdf", path="data/bot_6_other_secret.pdf"),
                                    knowledge(2, 5, "..", path="../../.env")], "media": []}
    code = issue_code(wiring)

    svc.confirm_deletion(OWNER, code)

    assert all(name.startswith("bot_5_") for name, _, _ in deleted(wiring))
    assert ("bot_6_other_secret.pdf", svc.DATA_FOLDER, "knowledge") not in deleted(wiring)


def test_one_failed_deletion_does_not_stop_the_rest_or_fail_the_request(wiring, caplog):
    wiring.storage = {"knowledge": [knowledge(1, 5, "bot_5_aaa_first.pdf"), knowledge(2, 5, "bot_5_bbb_second.pdf")],
                      "media": [media(5, "bot_5_ccc_logo.png")]}
    wiring.delete_errors["bot_5_aaa_first.pdf"] = document_storage.DocumentStorageError("R2 is down")
    code = issue_code(wiring)

    with caplog.at_level(logging.WARNING):
        result = svc.confirm_deletion(OWNER, code)

    assert result["status"] == "success"
    removed = [name for name, _, _ in deleted(wiring)]
    assert "bot_5_bbb_second.pdf" in removed and "bot_5_ccc_logo.png" in removed
    assert any("storage" in record.getMessage().lower() for record in caplog.records)
    assert "bot_5_aaa_first.pdf" not in caplog.text, "customer file names stay out of the log"


def test_cleanup_runs_on_a_daemon_thread_so_the_response_never_waits_for_storage(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, name, daemon):
            started.append((name, daemon))

        def start(self):
            started.append("started")

    monkeypatch.setattr(svc.threading, "Thread", FakeThread)

    svc._start_background(lambda: None)

    assert started == [("account-deletion-storage", True), "started"]


def test_confirming_answers_before_storage_cleanup_has_run(wiring, monkeypatch):
    monkeypatch.setattr(svc, "_start_background", REAL_START_BACKGROUND)
    recorded = []

    class RecordingThread:
        def __init__(self, target, name, daemon):
            recorded.append({"target": target, "name": name, "daemon": daemon})

        def start(self):
            pass  # deliberately never runs: the response must not depend on storage

    monkeypatch.setattr(svc.threading, "Thread", RecordingThread)
    wiring.storage = {"knowledge": [knowledge(1, 5, "bot_5_aaa_first.pdf")], "media": []}
    code = issue_code(wiring)

    result = svc.confirm_deletion(OWNER, code)

    assert result["status"] == "success"
    assert deleted(wiring) == [], "a synchronous cleanup in the request would already have deleted"
    assert [(r["name"], r["daemon"]) for r in recorded] == [("account-deletion-storage", True)]
    recorded[0]["target"]()
    assert ("bot_5_aaa_first.pdf", svc.DATA_FOLDER, "knowledge") in deleted(wiring)


def test_an_unexpected_storage_exception_is_also_swallowed(wiring):
    wiring.storage = {"knowledge": [knowledge(1, 5, "bot_5_aaa_first.pdf")], "media": []}
    wiring.delete_errors["bot_5_aaa_first.pdf"] = ValueError("anything")
    code = issue_code(wiring)

    assert svc.confirm_deletion(OWNER, code)["status"] == "success"


def test_a_failed_storage_listing_still_deletes_the_workspace(wiring):
    wiring.storage_error = RuntimeError("PostgREST timeout")
    code = issue_code(wiring)

    result = svc.confirm_deletion(OWNER, code)

    assert result["status"] == "success"
    assert ("rpc", 42, 7) in wiring.calls
    assert "delete_file" not in names(wiring)


def test_a_failed_listing_is_logged_without_the_exception_text(wiring, caplog):
    wiring.storage_error = RuntimeError("secret-host.supabase.co refused")
    code = issue_code(wiring)

    with caplog.at_level(logging.WARNING):
        svc.confirm_deletion(OWNER, code)

    assert "secret-host" not in caplog.text


# ---------------------------------------------------------------------------- email

class FakeSMTP:
    sent = []
    timeouts = []
    tls_contexts = []

    def __init__(self, host, port, timeout=None):
        FakeSMTP.timeouts.append(timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSMTP.tls_contexts.append(context)

    def login(self, user, password):
        pass

    def sendmail(self, sender, recipients, message):
        FakeSMTP.sent.append((sender, recipients, message))

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.timeouts, FakeSMTP.tls_contexts = [], [], []
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "no-reply@omnexa.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "dummy")
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    return FakeSMTP


def sent_message():
    import email
    from email import policy
    raw = FakeSMTP.sent[0][2]
    message = email.message_from_string(raw, policy=policy.default)
    body = message.get_body(preferencelist=("html", "plain")).get_content()
    return message, body


def test_the_email_states_what_is_deleted_the_code_the_expiry_and_how_to_ignore_it(smtp):
    from app.services.email_service import send_account_deletion_code_email

    assert send_account_deletion_code_email("owner@example.test", "048213", "Olivia", "Acme") is True

    message, body = sent_message()
    assert message["To"] == "owner@example.test"
    assert "048213" in body
    assert "10 minutes" in body
    assert "permanent" in body.lower() or "permanently" in body.lower()
    for thing in ("chatbots", "conversations", "team"):
        assert thing in body.lower()
    assert "ignore" in body.lower()
    assert "Acme" in body


def test_the_email_verifies_the_mail_server_and_cannot_hang(smtp):
    import ssl

    from app.services.email_service import SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS, send_account_deletion_code_email

    send_account_deletion_code_email("owner@example.test", "048213")

    assert len(FakeSMTP.tls_contexts) == 1
    context = FakeSMTP.tls_contexts[0]
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED, \
        "bare starttls() does not verify the server certificate"
    assert FakeSMTP.timeouts == [SUPPORT_NOTIFICATION_SMTP_TIMEOUT_SECONDS]


def test_the_email_escapes_hostile_names(smtp):
    from app.services.email_service import send_account_deletion_code_email

    send_account_deletion_code_email("owner@example.test", "048213", "<script>x</script>", "<img src=x onerror=y>")

    _, body = sent_message()
    assert "<script>" not in body and "<img src=x" not in body


def test_the_email_refuses_an_address_that_could_inject_a_header(smtp):
    from app.services.email_service import send_account_deletion_code_email

    assert send_account_deletion_code_email("a@example.test\r\nBcc: evil@example.test", "048213") is False
    assert FakeSMTP.sent == []


def test_the_email_reports_failure_instead_of_raising(monkeypatch):
    from app.services.email_service import send_account_deletion_code_email

    monkeypatch.setenv("SMTP_SENDER_EMAIL", "no-reply@omnexa.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "dummy")

    def explode(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("smtplib.SMTP", explode)
    assert send_account_deletion_code_email("owner@example.test", "048213") is False


def test_the_email_is_not_sent_without_smtp_credentials(monkeypatch):
    from app.services.email_service import send_account_deletion_code_email

    monkeypatch.delenv("SMTP_SENDER_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_APP_PASSWORD", raising=False)

    assert send_account_deletion_code_email("owner@example.test", "048213") is False
