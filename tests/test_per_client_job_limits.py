"""Phase 5 items 8-10: one Client at its limit is refused (or its email suppressed)
while every other Client goes through. Every external service is mocked."""
from contextlib import ExitStack
from itertools import count
from unittest.mock import patch

import pytest

from app import create_app
from app.services import client_job_limits as limits

HEADERS = {"Authorization": "Bearer test-token"}
_company_ids = count(70_000)


@pytest.fixture()
def companies():
    # Fresh ids per test: the limits are process-wide, so no test inherits another's usage.
    return next(_company_ids), next(_company_ids)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("AGENT_ANALYSIS_ENABLED", "true")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _signed_in_as(company_id):
    user = {"id": 31, "company_id": company_id, "role": "owner", "status": "active"}
    stack = ExitStack()
    stack.enter_context(patch("app.decorators.auth_decorator.jwt.decode", return_value={"user_id": 31}))
    stack.enter_context(patch("app.database.user_repository.get_user_by_id", return_value=user))
    stack.enter_context(patch("app.services.company_status_service.get_company_status_by_id",
                              return_value={"status": "active"}))
    return stack


# ── Documents: at most DOCUMENT_JOBS_PER_CLIENT in flight per Client ─────────

def _documents_in_flight(busy_company):
    return patch("app.database.knowledge_file_repository.count_company_files_in_flight",
                 side_effect=lambda company_id, since: limits.DOCUMENT_JOBS_PER_CLIENT if company_id == busy_company else 0)


def _extract(client, company_id):
    with _signed_in_as(company_id), \
         patch("app.routes.knowledge_routes.verify_chatbot_access"), \
         patch("app.routes.knowledge_routes.can_use_plan_feature"), \
         patch("app.routes.knowledge_routes.can_upload_knowledge_file"), \
         patch("app.routes.knowledge_routes.get_active_knowledge_file",
               return_value={"file_type": "pdf", "is_active": True, "is_enabled": True}), \
         patch("app.routes.knowledge_routes.scrape_pages",
               return_value=([{"url": "https://a.test", "content": "text"}], [])), \
         patch("app.services.chat_pipeline_service.scan_client_page", side_effect=lambda text, *a, **k: text), \
         patch("app.routes.knowledge_routes.extract_business_knowledge", return_value="refined") as extract:
        response = client.post("/api/knowledge/scrape-extract?chatbot_id=9", headers=HEADERS,
                               json={"urls": ["https://a.test"]})
    return response, extract


def test_busy_client_document_extract_is_refused_while_another_client_goes_through(client, companies):
    busy, other = companies
    with _documents_in_flight(busy):
        refused, refused_extract = _extract(client, busy)
        accepted, accepted_extract = _extract(client, other)

    assert refused.status_code == 429
    assert refused.json["status"] == "error"
    assert refused.json["code"] == "client_job_limit"
    assert "wait" in refused.json["message"]
    refused_extract.assert_not_called()  # refused before the billed extraction
    assert accepted.status_code == 200
    accepted_extract.assert_called_once()


class _Upload:
    filename = "doc.pdf"

    def save(self, path):
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4")


def _accept_pdf(monkeypatch, tmp_path, company_id):
    from app.services import knowledge_service
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    with patch.object(knowledge_service, "validate_saved_pdf", return_value=10), \
         patch.object(knowledge_service.document_storage, "persist_file"), \
         patch.object(knowledge_service, "save_knowledge_file", return_value={"id": 5}) as saved, \
         patch("app.services.knowledge_ingest_job_service.start_pdf_ingest") as started:
        try:
            return (knowledge_service.save_uploaded_pdf(_Upload(), 9, defer_processing=True, company_id=company_id),
                    saved, started)
        except limits.ClientJobLimitError as exc:
            return exc, saved, started


def test_busy_client_pdf_upload_is_refused_at_acceptance_while_another_client_is_queued(
        monkeypatch, tmp_path, companies):
    busy, other = companies
    with _documents_in_flight(busy):
        refused, refused_row, refused_start = _accept_pdf(monkeypatch, tmp_path, busy)
        accepted, _row, accepted_start = _accept_pdf(monkeypatch, tmp_path, other)

    assert isinstance(refused, limits.ClientJobLimitError) and refused.status_code == 429
    refused_row.assert_not_called()
    refused_start.assert_not_called()
    assert accepted["status"] == "processing"
    accepted_start.assert_called_once()


def test_a_finished_document_job_frees_its_slot(companies):
    busy, other = companies
    with patch("app.database.knowledge_file_repository.count_company_files_in_flight", return_value=0):
        with ExitStack() as held:
            for _ in range(limits.DOCUMENT_JOBS_PER_CLIENT):
                held.enter_context(limits.document_job(busy))
            with pytest.raises(limits.ClientJobLimitError):
                limits.document_job(busy).__enter__()
            with limits.document_job(other):
                pass
        with limits.document_job(busy):
            pass


# ── Reports: at most REPORT_JOBS_PER_CLIENT queued or running per Client ─────

class _ReportRows:
    """analysis_reports in flight, as count_company_reports_in_flight would read them."""

    def __init__(self, busy_company):
        keys = [f"in-flight-{index}" for index in range(limits.REPORT_JOBS_PER_CLIENT)]
        self.rows = {busy_company: keys}

    def count(self, company_id, *, exclude_client_message_id=None):
        return len([key for key in self.rows.get(company_id, []) if key != exclude_client_message_id])


def _request_report(client, company_id, key):
    with _signed_in_as(company_id), \
         patch("app.routes.analysis_routes.verify_chatbot_access", return_value={"id": 7, "company_id": company_id}), \
         patch("app.routes.analysis_routes.can_use_plan_feature", return_value=True), \
         patch("app.routes.analysis_routes.repo.create_report_request",
               return_value={"id": "r", "status": "queued"}) as create:
        response = client.post("/api/chatbots/7/analysis/messages", headers=HEADERS,
                               json={"text": "Last month's bookings", "client_message_id": key})
    return response, create


def test_busy_client_report_request_is_refused_while_another_client_is_queued(client, companies):
    busy, other = companies
    with patch("app.database.analysis_repository.count_company_reports_in_flight",
               side_effect=_ReportRows(busy).count):
        refused, refused_create = _request_report(client, busy, "new-one")
        retried, retried_create = _request_report(client, busy, "in-flight-0")
        accepted, accepted_create = _request_report(client, other, "new-one")

    assert refused.status_code == 429
    assert refused.json["code"] == "client_job_limit" and "wait" in refused.json["message"]
    refused_create.assert_not_called()
    # A retry of a request already in flight still gets its own row back.
    assert retried.status_code == 202
    retried_create.assert_called_once()
    assert accepted.status_code == 202
    accepted_create.assert_called_once()


def _schedule(index, company_id):
    return {"id": f"00000000-0000-4000-8000-{index:012d}", "company_id": company_id, "chatbot_id": 7,
            "actor_user_id": 31, "frequency": "weekly", "enabled": True,
            "run_weekday": 0, "run_day": None, "run_time": "09:00"}


def test_busy_clients_schedule_waits_while_another_clients_is_enqueued(client, companies, monkeypatch):
    busy, other = companies
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "x" * 40)
    due = [_schedule(1, busy), _schedule(2, other)]
    with patch("app.services.company_status_service.get_company_status_by_id", return_value={"status": "active"}), \
         patch("app.routes.analysis_routes.can_use_plan_feature", return_value=True), \
         patch("app.routes.analysis_routes.repo.list_due_schedules",
               side_effect=lambda *, limit, offset, now=None: due[offset:offset + limit]), \
         patch("app.database.analysis_repository.count_company_reports_in_flight",
               side_effect=_ReportRows(busy).count), \
         patch("app.routes.analysis_routes.repo.enqueue_schedule_report",
               return_value={"enqueued": True}) as enqueue:
        response = client.post("/internal/analysis/schedules/tick", json={},
                               headers={"Authorization": "Bearer " + "x" * 40})

    assert response.status_code == 200
    assert response.json["data"] == {"enqueued": 1, "skipped": 0}
    assert [call.args[0] for call in enqueue.call_args_list] == [other]


def _weekly_report(company_id):
    from app.services import report_service
    with patch.object(report_service, "get_transcript_logs", return_value=[{"phone": None, "chat": "Hi"}]), \
         patch.object(report_service, "_safe_chat", side_effect=lambda chat, _bot: chat), \
         patch.object(report_service, "get_bot_by_id", return_value={"id": 7, "company_id": company_id}), \
         patch.object(report_service, "generate_system_response", return_value="Report body") as generate:
        try:
            return report_service.generate_weekly_report(chatbot_id=7), generate
        except limits.ClientJobLimitError as exc:
            return exc, generate


def test_busy_client_weekly_report_is_refused_while_another_client_gets_one(companies):
    busy, other = companies
    with patch("app.database.analysis_repository.count_company_reports_in_flight",
               side_effect=_ReportRows(busy).count):
        refused, refused_generate = _weekly_report(busy)
        accepted, accepted_generate = _weekly_report(other)

    assert isinstance(refused, limits.ClientJobLimitError) and refused.status_code == 429
    refused_generate.assert_not_called()
    assert "Report body" in accepted
    accepted_generate.assert_called_once()


# ── Email: at most EMAILS_PER_CLIENT_PER_HOUR per Client; exempt types never ──

class _FakeSMTP:
    sent = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self, *_args, **_kwargs):
        pass

    def login(self, *_args):
        pass

    def sendmail(self, _sender, recipients, _message):
        _FakeSMTP.sent.append(recipients)

    def quit(self):
        pass


@pytest.fixture()
def smtp(monkeypatch):
    monkeypatch.setenv("SMTP_SENDER_EMAIL", "platform@example.test")
    monkeypatch.setenv("SMTP_APP_PASSWORD", "app-password")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    _FakeSMTP.sent = []
    return _FakeSMTP


def _exhaust_email_budget(company_id):
    for _ in range(limits.EMAILS_PER_CLIENT_PER_HOUR):
        assert limits.allow_client_email(company_id, "test")


def _support_request(company_id):
    from app.services import email_service
    return email_service.send_tenant_support_request_notification_email(
        "support@example.test", request_id=1, company_id=company_id, category="faq",
        status="new", submitted_at="2026-11-14T00:00:00+00:00", redacted_description="help")


def test_busy_clients_support_email_is_suppressed_while_another_clients_is_sent(smtp, companies, caplog):
    busy, other = companies
    for _ in range(limits.EMAILS_PER_CLIENT_PER_HOUR):
        assert _support_request(busy) is True

    with caplog.at_level("WARNING"):
        suppressed = _support_request(busy)
    sent = _support_request(other)

    assert suppressed is False
    assert sent is True
    assert len(smtp.sent) == limits.EMAILS_PER_CLIENT_PER_HOUR + 1
    skip_logs = [record.getMessage() for record in caplog.records if "email skipped" in record.getMessage()]
    assert skip_logs == [f"[ClientLimits] support_request email skipped for company_id={busy}: hourly limit reached"]
    assert "@" not in skip_logs[0]


def _exempt_senders():
    from app.services import email_service as mail
    from app.services import receipt_email_service as receipts
    conversation = {"id": 3, "customer_phone": "60120000000", "source_channel": "whatsapp"}
    return {
        "otp": lambda busy: mail.send_otp_email("user@example.test", "123456"),
        "password_reset": lambda busy: mail.send_reset_email("user@example.test", "123456"),
        "invite": lambda busy: mail.send_invite_email("user@example.test", "https://app.test/invite"),
        "account_deletion_code": lambda busy: mail.send_account_deletion_code_email("user@example.test", "123456"),
        "billing": lambda busy: mail.send_billing_notification_email("owner@example.test", title="Low credit",
                                                                     message="Top up"),
        "receipt": lambda busy: receipts.send_receipt_email(
            "owner@example.test", order_reference="OR-1", rows=[("Plan", "Pro")], recipient_name="Owner",
            summary="Paid", notice="Thanks"),
        "handoff": lambda busy: mail.send_handoff_notification_email(busy, conversation, 7, trigger="self_harm"),
        "moderation_alert": lambda busy: mail.send_moderation_alert_email(
            company_id=busy, reasons=["violence"], provider_name="openrouter", model_slug="m"),
        "child_content_owner_alert": lambda busy: mail.send_content_flag_alert_email(
            company_id=busy, category="child_sexual"),
        "openrouter_key_alert": lambda busy: mail.send_openrouter_key_alert_email(label="k1", problem="expired"),
        "ai_balance_alert": lambda busy: mail.send_ai_balance_alert_email(remaining_usd=4.0, spend_per_day_usd=1.0),
        "client_flag_warning": lambda busy: mail.send_client_flag_warning_email(company_id=busy, flag_count=5, days=7),
        "pause_request": lambda busy: mail.send_client_pause_request_email(company_id=busy, flag_count=9, days=7),
        "nightly_review": lambda busy: mail._send_platform_alert("Omnexa: nightly safety review", ["2 flags"]),
    }


@pytest.mark.parametrize("email_type", sorted(_exempt_senders()))
def test_exempt_email_is_never_suppressed_even_over_the_limit(smtp, companies, email_type):
    busy, _other = companies
    _exhaust_email_budget(busy)
    staff = [{"email": "staff@example.test", "status": "active"}]
    with patch("app.database.user_repository.get_users_by_company", return_value=staff), \
         patch("app.database.user_repository.get_company_billing_contact",
               return_value={"email": "owner@example.test", "full_name": "Owner"}):
        assert _exempt_senders()[email_type](busy) is True
    assert len(smtp.sent) == 1
    assert limits.allow_client_email(busy, "test") is False  # the Client really was over the limit


# ── Entry points owned by views.py, analytics_routes.py and booking_service.py ─

def _upload_pdf(client, monkeypatch, tmp_path, company_id):
    from io import BytesIO
    from app.services import knowledge_service
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    with _signed_in_as(company_id), \
         patch("app.views.verify_chatbot_access"), \
         patch("app.views.can_upload_knowledge_file"), \
         patch("app.views.can_upload_knowledge_storage"), \
         patch.object(knowledge_service, "validate_saved_pdf", return_value=10), \
         patch.object(knowledge_service.document_storage, "persist_file"), \
         patch.object(knowledge_service, "save_knowledge_file", return_value={"id": 5}) as saved, \
         patch("app.services.knowledge_ingest_job_service.start_pdf_ingest"):
        response = client.post("/upload-pdf?chatbot_id=9", headers=HEADERS, content_type="multipart/form-data",
                               data={"pdf_file": (BytesIO(b"%PDF-1.4"), "doc.pdf")})
    return response, saved


def test_busy_client_upload_pdf_route_answers_429_while_another_client_is_accepted(
        client, monkeypatch, tmp_path, companies):
    busy, other = companies
    with _documents_in_flight(busy):
        refused, refused_row = _upload_pdf(client, monkeypatch, tmp_path, busy)
        accepted, accepted_row = _upload_pdf(client, monkeypatch, tmp_path, other)

    assert refused.status_code == 429
    assert refused.json["status"] == "error" and refused.json["code"] == "client_job_limit"
    refused_row.assert_not_called()
    assert accepted.status_code == 200 and accepted.json["status"] == "processing"
    accepted_row.assert_called_once()


def _analytics_report(client, company_id):
    from app.services import report_service
    with _signed_in_as(company_id), \
         patch("app.routes.analytics_routes.can_use_plan_feature"), \
         patch("app.routes.analytics_routes.verify_chatbot_access"), \
         patch.object(report_service, "get_transcript_logs", return_value=[{"phone": None, "chat": "Hi"}]), \
         patch.object(report_service, "_safe_chat", side_effect=lambda chat, _bot: chat), \
         patch.object(report_service, "get_bot_by_id", return_value={"id": 7, "company_id": company_id}), \
         patch.object(report_service, "generate_system_response", return_value="Report body") as generate:
        return client.get("/api/analytics/report?chatbot_id=7", headers=HEADERS), generate


def test_busy_client_analytics_report_route_answers_429_while_another_client_gets_one(client, companies):
    busy, other = companies
    with patch("app.database.analysis_repository.count_company_reports_in_flight",
               side_effect=_ReportRows(busy).count):
        refused, refused_generate = _analytics_report(client, busy)
        accepted, accepted_generate = _analytics_report(client, other)

    assert refused.status_code == 429
    assert refused.json["code"] == "client_job_limit" and "wait" in refused.json["message"]
    refused_generate.assert_not_called()
    assert accepted.status_code == 200 and "Report body" in accepted.json["data"]["report"]


def test_busy_clients_booking_notice_is_suppressed_while_another_clients_is_sent(companies, caplog):
    from app.services import booking_service
    busy, other = companies
    _exhaust_email_budget(busy)
    contact = {"email": "owner@example.test", "full_name": "Owner"}
    with patch.object(booking_service, "get_company_billing_contact", return_value=contact), \
         patch.object(booking_service, "send_notice_email", return_value=True) as send, \
         caplog.at_level("WARNING"):
        booking_service.notify_owner_of_new_request(busy)
        booking_service.notify_owner_of_new_request(other)

    assert send.call_count == 1  # only the other Client's notice left
    skip_logs = [record.getMessage() for record in caplog.records if "email skipped" in record.getMessage()]
    assert skip_logs == [f"[ClientLimits] booking_notice email skipped for company_id={busy}: hourly limit reached"]


def test_parallel_candidate_confirms_hold_their_slots_for_the_whole_ingest(client, companies):
    import threading
    busy, other = companies
    release = threading.Event()
    started = threading.Semaphore(0)

    def ingest(*, candidate_id, chatbot_id, company_id):
        if company_id == busy:
            started.release()
            assert release.wait(10)
        return {"candidate_id": candidate_id}

    def confirm(results, index):
        response = client.application.test_client().post(
            f"/api/knowledge/pdf-candidates/c{index}/confirm?chatbot_id=9", headers=HEADERS)
        results[index] = response.status_code

    results = {}
    with _signed_in_as(busy), \
         patch("app.routes.knowledge_routes.verify_chatbot_access"), \
         patch("app.database.knowledge_file_repository.count_company_files_in_flight", return_value=0), \
         patch("app.routes.knowledge_routes.confirm_supporting_pdf_candidate", side_effect=ingest) as confirmed:
        running = [threading.Thread(target=confirm, args=(results, index)) for index in range(3)]
        for thread in running:
            thread.start()
        for _ in running:
            assert started.acquire(timeout=10)  # three ingests are now in flight
        confirm(results, 3)  # the fourth arrives while they still run
        with _signed_in_as(other):
            confirm(results, 4)
        release.set()
        for thread in running:
            thread.join(10)

    assert sorted(results[index] for index in range(4)) == [200, 200, 200, 429]
    assert results[3] == 429
    assert results[4] == 200
    assert confirmed.call_count == 4  # three for the busy Client, one for the other
