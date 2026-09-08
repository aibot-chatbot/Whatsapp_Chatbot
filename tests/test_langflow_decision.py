"""Tests for the advisory Langflow decision layer.

The contract these guard: Langflow may refuse a CRM stage transition that Flask
would allow, but it must never be able to permit one Flask rejects, and no
Langflow failure may block a user-facing action. Every failure mode below has
to leave ``blocked`` False.
"""

import json

import pytest

from app.services import langflow_decision
from app.services.langflow_decision import (
    ContractViolation,
    crm_stage_decision,
    extract_flow_output,
    knowledge_document_decision,
    validate_against_schema,
)


CONFORMING = {
    "decision": "apply_crm_stage",
    "company_id": 42,
    "chatbot_id": 7,
    "lead_id": 1234,
    "target_status": "contacted",
    "correlation_id": "corr-1",
}


def _schema():
    return langflow_decision._contract(langflow_decision.CRM_CONTRACT)["output_schema"]


def _configure(monkeypatch, flow_id="f755be84-2dd6-4412-8161-aa2e07cebf68"):
    monkeypatch.setenv("LANGFLOW_CRM_FLOW_ID", flow_id)


def _call(**overrides):
    kwargs = dict(
        company_id=42, chatbot_id=7, lead_id=1234,
        current_status="new", target_status="contacted", correlation_id="corr-1",
    )
    kwargs.update(overrides)
    return crm_stage_decision(**kwargs)


# --- schema validation -----------------------------------------------------

def test_conforming_output_validates():
    assert validate_against_schema(dict(CONFORMING), _schema()) == CONFORMING


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d.pop("company_id"), "required"),
    (lambda d: d.update(extra="x"), "not permitted"),
    (lambda d: d.update(lead_id="1234"), "must be an integer"),
    (lambda d: d.update(decision="delete_everything"), "must be one of"),
    (lambda d: d.update(target_status="new"), "must be one of"),
    (lambda d: d.update(company_id=0), "below minimum"),
    (lambda d: d.update(reason="x" * 501), "exceeds maxLength"),
])
def test_non_conforming_output_is_rejected(mutate, expected):
    payload = dict(CONFORMING)
    mutate(payload)
    with pytest.raises(ContractViolation) as exc:
        validate_against_schema(payload, _schema())
    assert expected in str(exc.value)


# --- envelope extraction ---------------------------------------------------

def test_bare_contract_object_is_accepted():
    assert extract_flow_output(dict(CONFORMING))["decision"] == "apply_crm_stage"


def test_decision_is_extracted_from_a_run_envelope():
    envelope = {"outputs": [{"outputs": [{"results": {"message": {
        "text": json.dumps(CONFORMING)}}}]}]}
    assert extract_flow_output(envelope)["lead_id"] == 1234


def test_prose_output_is_a_contract_violation():
    """The stub Webhook/Parser/TextOutput flow answers with a sentence."""
    envelope = {"outputs": [{"outputs": [{"results": {"message": {
        "text": "CRM lead may transition from new to contacted."}}}]}]}
    with pytest.raises(ContractViolation):
        extract_flow_output(envelope)


# --- fail-open contract ----------------------------------------------------

def test_missing_flow_id_skips_without_blocking(monkeypatch):
    monkeypatch.delenv("LANGFLOW_CRM_FLOW_ID", raising=False)
    result = _call()
    assert result["blocked"] is False
    assert result["consulted"] is False
    assert "not configured" in result["detail"]


def test_transport_failure_does_not_block(monkeypatch):
    _configure(monkeypatch)

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(langflow_decision, "run_langflow_automation", explode)
    result = _call()
    assert result["blocked"] is False
    assert result["consulted"] is False
    assert "RuntimeError" in result["detail"]


def test_non_conforming_response_does_not_block(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(langflow_decision, "run_langflow_automation",
                        lambda *a, **k: {"outputs": [{"outputs": [{"results": {
                            "message": {"text": "just prose"}}}]}]})
    result = _call()
    assert result["blocked"] is False
    assert result["consulted"] is False


def test_decision_about_another_lead_cannot_block(monkeypatch):
    """A verdict on a different transition is not a verdict on this one."""
    _configure(monkeypatch)
    other = dict(CONFORMING, decision="block_crm_stage", lead_id=9999)
    monkeypatch.setattr(langflow_decision, "run_langflow_automation", lambda *a, **k: other)
    result = _call()
    assert result["blocked"] is False
    assert "different transition" in result["detail"]


def test_decision_about_another_target_status_cannot_block(monkeypatch):
    _configure(monkeypatch)
    other = dict(CONFORMING, decision="block_crm_stage", target_status="lost")
    monkeypatch.setattr(langflow_decision, "run_langflow_automation", lambda *a, **k: other)
    result = _call()
    assert result["blocked"] is False


@pytest.mark.parametrize("field, value", [
    ("company_id", 99),
    ("chatbot_id", 99),
    ("lead_id", 9999),
    ("target_status", "lost"),
    ("correlation_id", "other-correlation"),
])
def test_crm_response_for_a_different_request_cannot_block(monkeypatch, field, value):
    _configure(monkeypatch)
    refusal = dict(CONFORMING, decision="block_crm_stage", reason="untrusted")
    refusal[field] = value
    monkeypatch.setattr(
        langflow_decision, "run_langflow_automation", lambda *a, **k: refusal
    )

    result = _call()

    assert result["consulted"] is False
    assert result["blocked"] is False


# --- the one case that may block -------------------------------------------

def test_conforming_refusal_blocks_and_carries_its_reason(monkeypatch):
    _configure(monkeypatch)
    refusal = dict(CONFORMING, decision="block_crm_stage", reason="duplicate lead")
    monkeypatch.setattr(langflow_decision, "run_langflow_automation", lambda *a, **k: refusal)
    result = _call()
    assert result["blocked"] is True
    assert result["consulted"] is True
    assert result["reason"] == "duplicate lead"


def test_conforming_approval_is_consulted_but_not_blocking(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(langflow_decision, "run_langflow_automation",
                        lambda *a, **k: dict(CONFORMING))
    result = _call()
    assert result["consulted"] is True
    assert result["blocked"] is False


def test_correlation_id_is_sent_and_returned(monkeypatch):
    _configure(monkeypatch)
    seen = {}

    def capture(flow_id, envelope):
        # The flow input travels as a JSON string under Langflow's run envelope.
        seen.update(envelope)
        seen["payload"] = json.loads(envelope["input_value"])
        return dict(CONFORMING, correlation_id=seen["payload"]["correlation_id"])

    monkeypatch.setattr(langflow_decision, "run_langflow_automation", capture)
    result = _call(correlation_id="fixed-corr")
    assert seen["input_type"] == "chat"
    assert seen["output_type"] == "chat"
    assert seen["payload"]["correlation_id"] == "fixed-corr"
    assert result["correlation_id"] == "fixed-corr"
    assert seen["payload"]["current_status"] == "new"
    assert seen["payload"]["target_status"] == "contacted"


def test_flow_id_with_unsafe_characters_is_refused(monkeypatch):
    monkeypatch.setenv("LANGFLOW_CRM_FLOW_ID", "../../etc/passwd")
    result = _call()
    assert result["consulted"] is False
    assert result["blocked"] is False


# --- knowledge document follow-up ------------------------------------------

KB_CONFORMING = {
    "decision": "review_document",
    "requires_approval": True,
    "correlation_id": "kb-corr",
    "summary": "Refund Policy v3 finished training with 17 chunk(s).",
}


def _kb_call(**overrides):
    kwargs = dict(company_id=42, chatbot_id=7, file_id=88,
                  display_name="Refund Policy v3", chunk_count=17,
                  target_role="primary", correlation_id="kb-corr")
    kwargs.update(overrides)
    return knowledge_document_decision(**kwargs)


def _kb_schema():
    return langflow_decision._contract(langflow_decision.KNOWLEDGE_CONTRACT)["output_schema"]


def test_knowledge_contract_pins_decision_and_approval():
    """Both are const, so the flow can never opt a document out of review."""
    validate_against_schema(dict(KB_CONFORMING), _kb_schema())
    for bad in ({"decision": "skip_document"}, {"requires_approval": False}):
        with pytest.raises(ContractViolation):
            validate_against_schema(dict(KB_CONFORMING, **bad), _kb_schema())


def test_knowledge_summary_is_returned(monkeypatch):
    monkeypatch.setenv("LANGFLOW_KNOWLEDGE_FLOW_ID", "3c0a6167-01f7-4ed1-9b8c-5842ef75b3d2")
    monkeypatch.setattr(langflow_decision, "run_langflow_automation",
                        lambda *a, **k: dict(KB_CONFORMING))
    result = _kb_call()
    assert result["consulted"] is True
    assert result["requires_approval"] is True
    assert "Refund Policy v3" in result["summary"]


def test_knowledge_response_with_a_different_correlation_fails_open(monkeypatch):
    monkeypatch.setenv("LANGFLOW_KNOWLEDGE_FLOW_ID", "3c0a6167-01f7-4ed1-9b8c-5842ef75b3d2")
    monkeypatch.setattr(
        langflow_decision,
        "run_langflow_automation",
        lambda *a, **k: dict(KB_CONFORMING, correlation_id="other-correlation"),
    )

    result = _kb_call()

    assert result["consulted"] is False
    assert result["blocked"] is False


def test_knowledge_never_blocks(monkeypatch):
    """There is no blocking path: enrichment only."""
    monkeypatch.setenv("LANGFLOW_KNOWLEDGE_FLOW_ID", "3c0a6167-01f7-4ed1-9b8c-5842ef75b3d2")

    def explode(*args, **kwargs):
        raise RuntimeError("langflow down")

    monkeypatch.setattr(langflow_decision, "run_langflow_automation", explode)
    result = _kb_call()
    assert result["blocked"] is False
    assert result["consulted"] is False
    assert "RuntimeError" in result["detail"]


def test_knowledge_missing_flow_id_skips(monkeypatch):
    monkeypatch.delenv("LANGFLOW_KNOWLEDGE_FLOW_ID", raising=False)
    result = _kb_call()
    assert result["consulted"] is False
    assert result["blocked"] is False


def test_knowledge_payload_carries_the_document_identity(monkeypatch):
    monkeypatch.setenv("LANGFLOW_KNOWLEDGE_FLOW_ID", "3c0a6167-01f7-4ed1-9b8c-5842ef75b3d2")
    seen = {}

    def capture(flow_id, envelope):
        seen.update(json.loads(envelope["input_value"]))
        return dict(KB_CONFORMING, correlation_id=seen["correlation_id"])

    monkeypatch.setattr(langflow_decision, "run_langflow_automation", capture)
    _kb_call()
    assert seen["file_id"] == 88
    assert seen["chunk_count"] == 17
    assert seen["target_role"] == "primary"
    assert seen["display_name"] == "Refund Policy v3"
