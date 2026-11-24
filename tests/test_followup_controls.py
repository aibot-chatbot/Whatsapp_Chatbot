from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import httpx
from postgrest import SyncPostgrestClient


ROOT = Path(__file__).resolve().parents[1]


def test_followup_migration_and_rollback():
    sql = (ROOT / "data/087_followup_controls.sql").read_text().lower()
    rollback = (ROOT / "data/087_followup_controls_rollback.sql").read_text().lower()
    for column in ("followups_enabled_at", "followups_auto_stopped_at"):
        assert f"add column if not exists {column} timestamptz" in sql
        assert f"drop column if exists {column}" in rollback
    assert "drop column if exists followups_enabled;" not in rollback


@pytest.fixture
def account(monkeypatch):
    from app import create_app
    from app.services import bot_service, billing_guard
    from app.database import follow_up_repository

    user = {"id": 3, "company_id": 42, "role": "owner", "status": "active"}
    bot = {"id": 7, "company_id": 42, "followups_enabled": False}
    monkeypatch.setattr("app.decorators.auth_decorator.jwt.decode", lambda *a, **kw: {"user_id": 3})
    monkeypatch.setattr("app.database.user_repository.get_user_by_id", lambda _: user)
    monkeypatch.setattr(bot_service, "get_bot_by_id", lambda b, c: bot if (b, c) == (7, 42) else None)
    write = Mock(side_effect=lambda b, fields, c, **kw: {**bot, **fields})
    monkeypatch.setattr(bot_service, "update_bot", write)
    plan = Mock(return_value=True)
    monkeypatch.setattr(billing_guard, "can_use_plan_feature", plan)
    channel = Mock(return_value=True)
    monkeypatch.setattr(follow_up_repository, "has_connected_follow_up_channel", channel, raising=False)
    client = create_app().test_client()
    return SimpleNamespace(user=user, bot=bot, write=write, plan=plan, channel=channel,
                           client=client, put=lambda value: client.put("/api/bots/7", json={"followups_enabled": value},
                                                        headers={"Authorization": "Bearer test"}),
                           summary=lambda: client.get("/api/bots/7/follow-ups",
                                                      headers={"Authorization": "Bearer test"}))


def test_followup_switch(account):
    assert account.put("false").status_code == 400
    account.write.assert_not_called()
    before = datetime.now(timezone.utc)
    assert account.put(True).status_code == 200
    fields = account.write.call_args.args[1]
    assert before <= datetime.fromisoformat(fields["followups_enabled_at"]) <= datetime.now(timezone.utc)
    assert fields["followups_enabled"] and fields["followups_auto_stopped_at"] is None
    account.bot.update(fields)
    account.write.reset_mock()
    assert account.put(True).status_code == 200
    account.write.assert_not_called()
    assert account.put(False).status_code == 200
    assert account.write.call_args.args == (7, {"followups_enabled": False}, 42)


def test_followup_switch_refuses_linked_device_only(account):
    account.channel.return_value = False
    response = account.put(True)
    assert response.status_code == 400
    assert response.json["message"] == "Connect Telegram or official WhatsApp to enable follow-ups."
    account.write.assert_not_called()


def test_followup_template_save_rejects_foreign_template_and_allows_clearing(account, monkeypatch):
    from app.database import db

    def handle(request):
        params = request.url.params
        assert params["company_id"] == "eq.42"
        if request.url.path == "/whatsapp_channels":
            assert params["chatbot_id"] == "eq.7"
            return httpx.Response(200, json=[{"whatsapp_business_account_id": "waba-a"}])
        assert request.url.path == "/whatsapp_templates"
        assert params["category"] == "eq.MARKETING" and params["status"] == "eq.APPROVED"
        assert params["body_has_variables"].lower() == "eq.false"
        # ID 12 belongs to company 43 and is absent from the tenant's result.
        return httpx.Response(200, json=[{"id": 11, "name": "hello", "language": "en_US",
                                         "waba_id": "waba-a"}] if params["id"] == "eq.11" else [])

    with httpx.Client(base_url="https://mock.invalid", transport=httpx.MockTransport(handle)) as http:
        api = SyncPostgrestClient("https://mock.invalid", http_client=http)
        monkeypatch.setattr(db, "supabase", SimpleNamespace(table=api.from_))
        def save(template_id):
            return account.client.put("/api/bots/7", json={"followup_template_id": template_id},
                                      headers={"Authorization": "Bearer test"})

        assert save(11).status_code == 200
        assert account.write.call_args.args == (7, {"followup_template_id": 11}, 42)
        account.write.reset_mock()
        for invalid in (12, True, [], "11", -1):
            assert save(invalid).status_code == 400
        account.write.assert_not_called()
        assert save(None).status_code == 200
        assert account.write.call_args.args == (7, {"followup_template_id": None}, 42)


def test_followup_switch_requires_plan_and_access(account):
    from app.services.billing_guard import BillingLimitError

    account.plan.side_effect = BillingLimitError("Upgrade", code="feature_not_available",
                                                details={"feature_key": "automation_workflows"})
    response = account.put(True)
    assert response.status_code == 403
    assert response.json == {"status": "error", "code": "feature_not_available",
                             "message": "Follow-ups require a Pro plan.",
                             "details": {"feature_key": "automation_workflows"}}
    account.plan.assert_called_once_with(42, "automation_workflows")
    assert account.put(False).status_code == 200
    account.write.reset_mock()
    account.user["company_id"] = 43
    assert account.put(True).status_code in (400, 403, 404)
    account.user.update(company_id=42, role="member")
    assert account.put(False).status_code == 403
    account.write.assert_not_called()


@pytest.mark.parametrize("source,connected,waba,allowed", [
    ("whatsapp", True, "waba-a", True), ("telegram", True, None, True),
    ("whatsapp", False, "waba-a", False), ("whatsapp_link", True, None, False),
    ("whatsapp", True, None, True),
])
def test_followup_switch_accepts_only_connected_supported_channels(monkeypatch, source, connected, waba, allowed):
    from app.database import db, follow_up_repository as repo

    # Use the real scoped query against a fake PostgREST transport.
    def handle(request):
        table = request.url.path.lstrip("/")
        assert table in ("whatsapp_channels", "telegram_channels")
        params = request.url.params
        assert (params["company_id"], params["chatbot_id"]) == ("eq.42", "eq.7")
        assert (params["is_active"].lower(), params["connection_status"]) == ("eq.true", "eq.connected")
        rows = [{"id": 23, "whatsapp_business_account_id": waba}] if table == source + "_channels" and connected else []
        return httpx.Response(200, json=rows)

    with httpx.Client(base_url="https://mock.invalid", transport=httpx.MockTransport(handle)) as http:
        api = SyncPostgrestClient("https://mock.invalid", http_client=http)
        monkeypatch.setattr(db, "supabase", SimpleNamespace(table=api.from_))
        assert repo.has_connected_follow_up_channel(42, 7) is allowed


def test_followup_summary_scopes_activity_and_returns_only_public_fields(account, monkeypatch):
    from app.database import db
    from app.services import follow_up_service

    now = datetime.now(timezone.utc)
    at = (now - timedelta(hours=1)).isoformat()
    earlier = (now - timedelta(days=2)).isoformat()
    old = (now - timedelta(days=33)).isoformat()
    bot = {**account.bot, "deployed_profile_name": "Shop", "tone": "Legacy", "followup_template_id": 21,
           "followups_enabled_at": (now - timedelta(days=1)).isoformat()}
    reasons = ["customer_replied", "lead_won", "no_reply", "held_by_check", "needs_review",
               "delivery_failed", "customer_replied", None]
    touches = [[old, earlier, at], [at], [at], [], [], [], [], []]
    rows = [dict(id=i, conversation_id=i, mode="sales", kind="sales", status="stopped", stop_reason=reason,
                 sent_touch_times=times, touch_count=len(times), last_touch_at=times[-1] if times else None,
                 updated_at=at, created_at=earlier, withdrawn_at=now.isoformat() if i == 0 else None)
            for i, (reason, times) in enumerate(zip(reasons, touches))]
    rows[-1].update(conversation_id=1, kind="check_in", won_at=earlier)
    safe = {"conversation_id", "mode", "kind", "touch_count", "status", "stop_reason", "last_touch_at"}
    seen = set()

    def handle(request):
        params = request.url.params
        table = request.url.path[1:]
        seen.add(table)
        if table == "chatbots":
            assert params["company_id"] == "eq.42" and params["id"] == "eq.7"
            result = [bot]
        elif table == "bot_configs":
            assert params["chatbots.company_id"] == "eq.42" and params["chatbot_id"] == "eq.7"
            assert params["profile_name"] == "eq.Shop"
            result = [{"tone": "Warm and direct"}]
        elif table == "whatsapp_channels":
            assert params["company_id"] == "eq.42" and params["chatbot_id"] == "eq.7"
            result = [{"whatsapp_business_account_id": "waba-a"}]
        elif table == "whatsapp_templates":
            assert params["company_id"] == "eq.42" and "waba-a" in params["waba_id"]
            assert params["status"] == "eq.APPROVED" and params["category"] == "eq.MARKETING"
            assert params["body_has_variables"].lower() == "eq.false"
            result = [{"id": 21, "name": "check_in", "language": "ms", "waba_id": "waba-a"}]
        else:
            assert params["company_id"] == "eq.42" and params["chatbot_id"] == "eq.7"
            if table == "follow_up_receipts":
                assert all(bound.startswith(prefix) for bound, prefix in
                           zip(params.get_list("sent_at"), ("gte.", "lte."), strict=True))
                result = [dict(conversation_id=row["conversation_id"], sent_at=t, withdrawn_at=row["withdrawn_at"])
                          for row in rows for t in row["sent_touch_times"]]
            elif table == "follow_ups":
                if params.get("limit") == "20":
                    assert set(params["select"].split(",")) == safe
                    result = [{key: row.get(key) for key in safe} for row in rows]
                else:
                    assert params["updated_at"].startswith("gte.")
                    result = rows
            else:
                raise AssertionError(table)
            if int(params.get("offset", 0)) > 0:
                result = []
        return httpx.Response(200, json=result)

    with httpx.Client(base_url="https://mock.invalid", transport=httpx.MockTransport(handle)) as http:
        api = SyncPostgrestClient("https://mock.invalid", http_client=http)
        monkeypatch.setattr(db, "supabase", SimpleNamespace(table=api.from_))
        monkeypatch.setattr(follow_up_service, "can_use_plan_feature", account.plan)
        response = account.summary()
    assert response.status_code == 200
    summary = response.json["data"]
    assert seen == {"chatbots", "bot_configs", "follow_up_receipts", "follow_ups", "whatsapp_channels", "whatsapp_templates"}
    assert summary["has_official_whatsapp"] and summary["followup_template_id"] == 21
    assert summary["templates"] == [{"id": 21, "name": "check_in", "language": "ms"}]
    assert summary["tone"] == "Warm and direct" and summary["available"] and not summary["enabled"]
    assert summary["counts"] == {"followed": 3, "messages_sent": 4, "replied": 1, "opted_out": 1,
                                 "won": 1, "no_reply": 1, "held": 1, "delivery_failed": 2}
    assert summary["rate"]["percent"] == pytest.approx(100 / 3)
    assert summary["thresholds"] == {"percent": 5, "minimum_customers": 20, "window_days": 30}
    assert all(set(row) == safe for row in summary["recent"])
    for private in ("phone", "platform_user_id", "message_text", "withdrawn_at"):
        assert private not in response.get_data(as_text=True)


def test_followup_summary_denies_foreign_and_member(account, monkeypatch):
    from app.database import db

    def handle(request):
        assert request.url.path == "/chatbots"
        assert request.url.params["id"] == "eq.7" and request.url.params["company_id"] == "eq.43"
        return httpx.Response(200, json=[])

    with httpx.Client(base_url="https://mock.invalid", transport=httpx.MockTransport(handle)) as http:
        api = SyncPostgrestClient("https://mock.invalid", http_client=http)
        monkeypatch.setattr(db, "supabase", SimpleNamespace(table=api.from_))
        account.user["company_id"] = 43
        assert account.summary().status_code == 403
        account.user.update(company_id=42, role="member")
        assert account.summary().status_code == 403


def test_behaviour_frontend_followup_card_and_error():
    page = (ROOT / "web/src/pages/behaviour.astro").read_text(encoding="utf-8")
    js = (ROOT / "frontend/assets/js/behaviour.js").read_text(encoding="utf-8")
    for content in ('id="bh-followups"', 'id="bh-followup-stop"', 'id="bh-followup-recent"',
                    "Telegram", "YES", "at most 3 messages", "9am", "9pm", "Malaysia time", "STOP"):
        assert content in page
    assert "{ followups_enabled: toggle.checked }" in js
    assert 'body.message' in js and '$("bh-followup-status").textContent' in js
    assert 'new_prompt.html?bot_id=' in js and 'conversations.html?bot_id=' in js


def test_behaviour_whatsapp_template_control_is_hidden_until_connected():
    page = (ROOT / "web/src/pages/behaviour.astro").read_text(encoding="utf-8")
    js = (ROOT / "frontend/assets/js/behaviour.js").read_text(encoding="utf-8")
    assert 'id="bh-followup-template-field" hidden' in page
    assert 'for="bh-followup-template">Template after 24 hours' in page
    assert 'class="kw-select" id="bh-followup-template"' in page
    assert 'hidden = !data.has_official_whatsapp' in js
    assert 'followup_template_id:' in js
    assert 'meta_templates.html?bot_id=' in js


def test_followup_summary_preserves_reason_after_window_moves(monkeypatch):
    from app.services import follow_up_service as service

    now = datetime.now(timezone.utc)
    bot = {"id": 7, "company_id": 42, "followups_enabled": True, "followups_enabled_at": None}
    rows = [dict(conversation_id=i, sent_at=now - timedelta(days=1), withdrawn_at=now if i < 2 else None)
            for i in range(20)]
    repo = Mock()
    repo.receipts.return_value = rows
    repo.window_outcomes.return_value = []
    repo.recent_follow_ups.return_value = []
    repo.deployed_persona.return_value = None
    repo.connected_whatsapp_accounts.return_value = False, set()
    repo.has_connected_follow_up_channel.return_value = False
    monkeypatch.setattr(service, "repo", repo)
    monkeypatch.setattr(service, "can_use_plan_feature", lambda *_: True)
    stopped = service.follow_up_summary(bot, now=now)
    assert not stopped["available"] and "Telegram" in stopped["reason"] and not stopped["enabled"]
    assert stopped["auto_stopped_at"] == now.isoformat() and stopped["tone"] == "Friendly"
    bot.update(followups_enabled=False, followups_auto_stopped_at=stopped["auto_stopped_at"],
               followups_auto_stop_counts=stopped["auto_stop_counts"])
    later = service.follow_up_summary(bot, now=now + timedelta(days=31))
    assert later["rate"]["followed"] == 0
    assert later["auto_stop_counts"] == {"followed": 20, "opted_out": 2, "percent": 10}
    repo.auto_stop.assert_called_once()


def test_followup_receipts_and_auto_stop_are_scoped_to_current_enable_period(monkeypatch):
    import json
    from app.database import follow_up_repository as repo

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)
    stamp = start.isoformat()
    seen = []
    # Simulate a server with a one-row page limit and data from several bots.
    records = [(42, 7, 11), (42, 8, 22), (43, 7, 33), (42, 7, 44)]
    bot = {"id": 7, "company_id": 42, "followups_enabled_at": stamp}
    counts = {"followed": 20, "opted_out": 2, "percent": 10}

    def handle(request):
        params = request.url.params
        if request.url.path == "/follow_up_receipts":
            selected = [dict(conversation_id=user) for company, chatbot, user in records
                        if (params["company_id"], params["chatbot_id"]) == (f"eq.{company}", f"eq.{chatbot}")]
            offset = int(params.get("offset", 0))
            return httpx.Response(200, json=selected[offset:offset + 1])
        assert request.url.path == "/chatbots" and request.method == "PATCH"
        assert (params["company_id"], params["id"], params["followups_enabled"].lower(),
                params["followups_enabled_at"]) == ("eq.42", "eq.7", "eq.true", "eq." + stamp)
        assert json.loads(request.content) == {"followups_enabled": False, "followups_auto_stopped_at": now.isoformat(),
                                               "followups_auto_stop_counts": counts}
        seen.append(True)
        return httpx.Response(200, json=[bot] if len(seen) == 1 else [])

    with httpx.Client(base_url="https://mock.invalid", transport=httpx.MockTransport(handle)) as http:
        api = SyncPostgrestClient("https://mock.invalid", http_client=http)
        monkeypatch.setattr(repo.db, "supabase", SimpleNamespace(table=api.from_))
        assert repo.receipts(42, 7, start, now) == [{"conversation_id": 11}, {"conversation_id": 44}]
        assert repo.auto_stop(bot, now, counts)
        assert not repo.auto_stop(bot, now, counts)
