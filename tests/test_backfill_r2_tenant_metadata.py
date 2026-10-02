"""Tests for scripts/backfill_r2_tenant_metadata.py.

The script decides which tenant each historical R2 object belongs to, so a
wrong or guessed answer here is a cross-tenant read. Every R2 seam is a stub:
these tests must never touch a real bucket or a real credential.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backfill_r2_tenant_metadata.py"


def load_script():
    spec = importlib.util.spec_from_file_location("backfill_r2_tenant_metadata", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backfill = load_script()


@pytest.mark.parametrize("key,expected", [
    ("knowledge/bot_7_abc123_report.pdf", "7"),
    ("knowledge/bot_412_deadbeef_a_b_c.pdf", "412"),
    ("knowledge/bot_7_42_readme.md", "7"),
    ("knowledge/bot_7_42_history.json", "7"),
])
def test_tenant_is_read_from_the_recorded_prefix(key, expected):
    assert backfill.resolve_chatbot_id(key) == expected


@pytest.mark.parametrize("key", [
    "knowledge/_pdf_candidates/3/7/abc.pdf",   # abandoned candidate, never indexed
    "knowledge/bot_7_",                        # no document part
    "knowledge/bot__abc.pdf",                  # no id
    "knowledge/bot_seven_abc.pdf",             # not a numeric id
    "knowledge/bot_7/nested/abc.pdf",          # a slash is a different key shape
    "knowledge/loose.pdf",                     # pre-dates the naming convention
    "media/bot_7_abc_photo.png",               # outside the knowledge prefix
])
def test_unresolvable_keys_are_refused_rather_than_guessed(key):
    assert backfill.resolve_chatbot_id(key) is None


def stub_client(objects):
    """An S3 stub whose head_object answers from ``objects``."""
    client = Mock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": key} for key in objects]}
    ]
    client.head_object.side_effect = lambda *, Bucket, Key: objects[Key]
    return client


def test_dry_run_writes_nothing_and_counts_what_it_would_change():
    client = stub_client({
        "knowledge/bot_7_abc_report.pdf": {"ContentType": "application/pdf", "Metadata": {}},
        "knowledge/_pdf_candidates/3/7/abc.pdf": {"ContentType": "application/pdf", "Metadata": {}},
    })
    assert backfill.backfill(client, "bucket", apply_changes=False) == (1, 1, 0)
    client.copy_object.assert_not_called()


def test_apply_replaces_metadata_in_place_and_preserves_system_headers():
    client = stub_client({"knowledge/bot_7_abc_report.pdf": {
        "ContentType": "application/pdf",
        "CacheControl": "private, no-store",
        "Metadata": {"existing": "kept"},
    }})
    assert backfill.backfill(client, "bucket", apply_changes=True) == (1, 0, 0)
    arguments = client.copy_object.call_args.kwargs
    assert arguments["Key"] == "knowledge/bot_7_abc_report.pdf"
    assert arguments["CopySource"] == {"Bucket": "bucket", "Key": "knowledge/bot_7_abc_report.pdf"}
    assert arguments["MetadataDirective"] == "REPLACE"
    assert arguments["Metadata"] == {"existing": "kept", "chatbot_id": "7"}
    # A REPLACE copy drops every header it is not given; losing ContentType
    # would make the object unindexable.
    assert arguments["ContentType"] == "application/pdf"
    assert arguments["CacheControl"] == "private, no-store"


def test_rerunning_changes_nothing():
    client = stub_client({"knowledge/bot_7_abc_report.pdf": {
        "ContentType": "application/pdf", "Metadata": {"chatbot_id": "7"},
    }})
    assert backfill.backfill(client, "bucket", apply_changes=True) == (0, 1, 0)
    client.copy_object.assert_not_called()


def test_one_failed_object_is_counted_without_stopping_the_walk():
    client = stub_client({
        "knowledge/bot_7_abc_report.pdf": {"ContentType": "application/pdf", "Metadata": {}},
        "knowledge/bot_8_def_report.pdf": {"ContentType": "application/pdf", "Metadata": {}},
    })
    client.copy_object.side_effect = [RuntimeError("private provider detail"), None]
    assert backfill.backfill(client, "bucket", apply_changes=True) == (1, 0, 1)
    assert client.copy_object.call_count == 2


def test_missing_configuration_reports_names_only(monkeypatch):
    for name in backfill.REQUIRED_ENV:
        monkeypatch.setenv(name, "")
    with pytest.raises(SystemExit) as caught:
        backfill.build_client()
    message = str(caught.value)
    assert "R2_SECRET_ACCESS_KEY" in message and "Missing R2 configuration" in message
