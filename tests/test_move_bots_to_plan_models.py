"""The one-off lineup migration: dry run writes nothing, apply moves only stale paid bots."""

from unittest.mock import Mock

import pytest

from scripts import move_bots_to_plan_models as script

BOTS = {
    1: [{"id": 11, "ai_provider": "cloudflare", "model_name": "@cf/openai/gpt-oss-20b"}],   # retired model
    2: [{"id": 21, "ai_provider": "openai", "model_name": "openai/gpt-6.1-sol"}],          # already on Pro
    3: [{"id": 31, "ai_provider": "cloudflare", "model_name": "@cf/qwen/qwen3-30b-a3b-fp8"}],  # trial company
}
PLANS = {1: "essential", 2: "pro", 3: None}


@pytest.fixture
def world(monkeypatch):
    convert = Mock()
    monkeypatch.setattr(script, "company_ids_with_bots", lambda: [1, 2, 3])
    monkeypatch.setattr(script, "paid_plan_code", PLANS.get)
    monkeypatch.setattr(script, "get_all_bots", BOTS.get)
    monkeypatch.setattr(script, "convert_trial_ai_configuration", convert)
    return convert


def test_dry_run_reports_stale_bots_and_writes_nothing(world, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["move_bots_to_plan_models.py"])
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "company 1 (essential) bot 11" in out and "-> openai/openai/gpt-6-luna" in out
    assert "bot 21" not in out and "bot 31" not in out
    world.assert_not_called()


def test_apply_converts_only_companies_with_stale_paid_bots(world, monkeypatch):
    monkeypatch.setattr("sys.argv", ["move_bots_to_plan_models.py", "--apply"])
    assert script.main() == 0
    world.assert_called_once_with(1, "essential")
