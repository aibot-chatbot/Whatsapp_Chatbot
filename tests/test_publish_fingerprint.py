from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.database import booking_availability_repository, knowledge_chunk_repository
from app.services import ai_access_policy, availability_service, test_scenario_service as publish_test_service


@pytest.fixture
def inputs(monkeypatch):
    service = import_module(publish_test_service.fingerprint.__module__)
    bot = {"id": 4, "company_id": 3, "temperature": 0.5, "model_name": "model",
           "booking_intake_enabled": True}
    profile = {"tone": "warm", "custom_prompt": "{context}"}
    policy = SimpleNamespace(api_route="openrouter", max_model_tier="premium")
    settings = {"enabled": True}
    knowledge = [{"id": 8, "is_active": True}, {"content": "tea"}]
    package = {"id": 9, "name": "Trial", "duration_minutes": 30, "seats_per_slot": 2, "enabled": True}
    hours = {"package_id": 9, "weekday": 2, "start_time": "08:00", "end_time": "10:00", "interval_minutes": 30}
    overrides = [{"package_id": 9, "closed_on": "2028-01-04"}]
    monkeypatch.setattr(service, "get_bot_by_id", lambda *args: bot)
    monkeypatch.setattr(service, "get_deployed_settings", lambda _: profile)
    monkeypatch.setattr(service, "get_active_published_flow", lambda *_, **kwargs: None)
    monkeypatch.setattr(service, "publish_knowledge_rows", lambda _: knowledge)
    monkeypatch.setattr(ai_access_policy, "resolve_ai_access", lambda _: policy)
    monkeypatch.setattr(availability_service, "is_enabled", lambda _, **kwargs: settings["enabled"])
    monkeypatch.setattr(booking_availability_repository, "list_packages", lambda *_: [package])
    monkeypatch.setattr(booking_availability_repository, "list_schedules_for_chatbot", lambda *_: [hours])
    monkeypatch.setattr(booking_availability_repository, "publish_booking_exceptions", lambda *_: overrides, raising=False)
    return SimpleNamespace(**locals(), digest=lambda: publish_test_service.fingerprint(4, 3))


def test_training_inputs_change_digest_but_unrelated_edits_do_not(inputs):
    original = inputs.digest()
    for row, field, value in [
        (inputs.bot, "temperature", 0.8), (inputs.bot, "model_name", "other"),
        (inputs.profile, "tone", "formal"), (inputs.profile, "custom_prompt", "different"),
        (inputs.knowledge[0], "id", 9), (inputs.knowledge[1], "content", "coffee"),
        (inputs.package, "seats_per_slot", 5), (inputs.hours, "start_time", "10:00"),
    ]:
        old = row[field]
        row[field] = value
        assert inputs.digest() != original, field
        row[field] = old
    inputs.bot["updated_at"] = "cosmetic"
    inputs.package["description"] = "internal note"
    inputs.hours["id"] = 54
    assert inputs.digest() == original


def test_model_entitlement_booking_entitlement_and_closures_change_digest(inputs):
    original = inputs.digest()
    inputs.policy.api_route = "deepseek"
    assert inputs.digest() != original
    inputs.policy.api_route = "openrouter"
    inputs.overrides.clear()
    assert inputs.digest() != original
    inputs.overrides.append({"package_id": 9, "closed_on": "2028-01-04"})
    inputs.settings["enabled"] = False
    assert inputs.digest() != original
    disabled = inputs.digest()
    inputs.package["name"] = "Hidden package"
    assert inputs.digest() == disabled


def test_graph_and_file_flags_are_part_of_knowledge_digest(monkeypatch):
    records = {
        "knowledge_files": [{"id": 1, "chatbot_id": 4, "is_active": False, "is_enabled": True}],
        "knowledge_chunks": [{"id": 2, "file_id": 1, "chatbot_id": 4, "content": "hours"}],
        "knowledge_graph_nodes": [{"id": 3, "chatbot_id": 4, "name": "clinic"}],
        "knowledge_graph_edges": [{"id": 4, "chatbot_id": 4, "source_name": "clinic",
                                   "target_name": "Monday", "rel_type": "OPEN_ON"}],
    }

    def table(name):
        query = Mock()
        fields = []
        def select(names):
            fields.extend(names.split(","))
            return query
        query.select.side_effect = select
        for method in ("eq", "or_", "in_", "order", "limit", "range", "gt"):
            getattr(query, method).return_value = query
        query.execute.side_effect = lambda: SimpleNamespace(
            data=[{k: row.get(k) for k in fields} for row in records[name]])
        return query

    monkeypatch.setattr(knowledge_chunk_repository, "supabase", SimpleNamespace(table=table))
    def snapshot():
        return list(knowledge_chunk_repository.publish_knowledge_rows(4))
    original = snapshot()
    for name, key, value in [("knowledge_graph_edges", "rel_type", "CLOSED_ON"),
                             ("knowledge_graph_nodes", "name", "shop"),
                             ("knowledge_files", "is_enabled", None)]:
        old = records[name][0][key]
        records[name][0][key] = value
        assert snapshot() != original, name
        records[name][0][key] = old


def test_large_document_hash_reads_new_query_for_each_page(monkeypatch):
    count = 237
    requests = []

    def table(name):
        query = Mock()
        rows = {
            "knowledge_files": [{"id": 1, "is_active": True, "is_enabled": True}],
            "knowledge_chunks": [{"id": i, "file_id": 1, "content": f"chunk-{i}"} for i in range(1, count + 1)],
        }.get(name, [])
        for method in ("select", "eq", "or_", "in_", "order"):
            getattr(query, method).return_value = query
        def page(start, end):
            # Installed PostgREST appends offset/limit on every range call on one builder.
            assert query.range.call_count == 1
            requests.append((name, start))
            query.execute.return_value = SimpleNamespace(data=rows[start:end + 1])
            return query
        query.range.side_effect = page
        return query

    monkeypatch.setattr(knowledge_chunk_repository, "supabase", SimpleNamespace(table=table))
    assert "chunk-237" in str(list(knowledge_chunk_repository.publish_knowledge_rows(4)))
    assert ("knowledge_chunks", 200) in requests


def test_unavailable_published_flow_cannot_reuse_a_flowless_pass(inputs, monkeypatch):
    from app.database import flow_repository

    query = Mock()
    for method in ("select", "eq", "in_", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.side_effect = TimeoutError("synthetic flow lookup timeout")
    monkeypatch.setattr(flow_repository, "supabase", SimpleNamespace(table=lambda _: query))
    monkeypatch.setattr(inputs.service, "get_active_published_flow", flow_repository.get_active_published_flow)
    with pytest.raises(TimeoutError):
        inputs.digest()


def test_booking_entitlement_read_errors_cannot_match_a_disabled_feature(monkeypatch):
    from app.services import billing_guard

    probe = Mock(side_effect=TimeoutError("synthetic plan lookup timeout"))
    monkeypatch.setattr(billing_guard, "can_use_plan_feature", probe)
    assert not availability_service.is_enabled(3)
    with pytest.raises(TimeoutError):
        availability_service.is_enabled(3, strict=True)
    probe.side_effect = billing_guard.BillingLimitError("unavailable on plan", code="feature_not_available")
    assert not availability_service.is_enabled(3, strict=True)
