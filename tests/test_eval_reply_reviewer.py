import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_eval_counts_errors_wrong_categories_and_filter_cases_separately():
    from scripts.eval_reply_reviewer import summarize

    def row(case, expected, category, verdict, predicted, latency):
        return dict(id=case, language="en", expected=expected, category=category, verdict=verdict,
                    predicted_category=predicted, latency_ms=latency, needs_review=False)

    summary = summarize([
        row("a", "hold", "leak", "error", None, 500),
        row("b", "hold", "facts", "pass", "none", 100),
        row("c", "hold", "promise", "hold", "facts", 200),
        row("d", "pass", "none", "hold", "leak", 300),
        row("e", "filter", "filtered", "pass", "none", 400),
    ])
    assert summary["calls"] == 5 and summary["returned_none"] == 1
    assert summary["misses"] == ["a", "b"] and summary["false_alarms"] == ["d"]
    assert summary["accuracy_by_language"]["en"] == {"scored": 4, "verdict_correct": 1, "category_correct": 0}
    assert summary["confusion"]["hold/promise"]["hold/facts"] == 1
    assert summary["confusion"]["filter/filtered"]["pass/none"] == 1
    assert (summary["median_ms"], summary["p95_ms"]) == (300, 500)


def test_offline_cli_reviews_all_fixtures_including_skips(tmp_path):
    output = tmp_path / "report.json"
    model = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    run = subprocess.run([sys.executable, str(ROOT / "scripts/eval_reply_reviewer.py"), "--dry-run",
                          "--out", str(output), "--model", model], cwd=tmp_path,
                         capture_output=True, text=True, timeout=30, check=True)
    report = json.loads(output.read_text(encoding="utf-8"))
    fixtures = json.loads((ROOT / "tests/fixtures/reply_check_chats.json").read_text(encoding="utf-8"))
    assert report["dry_run"] and report["model"] == model
    assert [row["id"] for row in report["rows"]] == [f["id"] for f in fixtures]
    summary = report["summary"]
    assert summary["calls"] == 60 and summary["returned_none"] == 0
    assert 0 < summary["needs_review"] < 60
    assert summary["false_alarms"] == []
    assert summary["misses"] == [f["id"] for f in fixtures if f["expected"] == "hold"]
    assert sum(c["scored"] for c in summary["accuracy_by_language"].values()) == 56
    for label in ("DRY RUN", "hold/facts", "filter/filtered", "en", "ms", "zh", "mixed",
                  "False alarms", "Misses", "median", "p95", "calls=60", "returned_none=0"):
        assert label in run.stdout


def test_eval_loads_only_workers_credentials_and_keeps_values_private(tmp_path, monkeypatch, capsys):
    from scripts import eval_reply_reviewer as cli

    names = ("CLOUDFLARE_AI_ACCOUNT_ID", "CLOUDFLARE_AI_API_TOKEN")
    values = ("a" * 32, "offline-" + "${LITERAL}")
    for name in (*names, "REPLY_REVIEW_MODEL", "UNRELATED_SETTING"):
        monkeypatch.setenv(name, "previous")
    env_file = tmp_path / ".env"
    env_file.write_text("\n".join([f"{k}='{v}'" for k, v in zip(names, values)] + ["UNRELATED_SETTING=unused"]),
                        encoding="utf-8")
    output = tmp_path / "results.json"
    monkeypatch.setattr(sys, "argv", ["eval", "--model", "@cf/example/chat", "--env-file", str(env_file),
                                      "--out", str(output)])
    calls = []

    def local_provider(*args, **kwargs):
        calls.append((tuple(os.environ.get(k) for k in names) == values,
                      os.environ["UNRELATED_SETTING"] == "previous", kwargs["model"] == "@cf/example/chat"))
        return {"choices": [{"message": {"content": "invalid response"}}]}

    monkeypatch.setattr(cli.cloudflare_service, "request", local_provider)
    cli.main()
    assert calls == [(True, True, True)] * 60
    report = json.loads(output.read_text(encoding="utf-8"))
    assert not report["dry_run"] and report["summary"]["returned_none"] == 60
    captured = capsys.readouterr()
    assert all(v not in captured.out + captured.err + output.read_text(encoding="utf-8") for v in values)


def test_offline_cli_accepts_live_cases_and_skips_review_gate_for_hidden_notes(tmp_path):
    output = tmp_path / "report.json"
    fixtures = ROOT / "tests/fixtures/reply_check_live_cases.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/eval_reply_reviewer.py"), "--dry-run",
                    "--fixtures", str(fixtures), "--out", str(output)], cwd=tmp_path,
                   capture_output=True, text=True, timeout=30, check=True)
    rows = json.loads(output.read_text(encoding="utf-8"))["rows"]
    assert [r["id"] for r in rows] == [c["id"] for c in json.loads(fixtures.read_text(encoding="utf-8"))]
    assert not next(r for r in rows if r["id"] == "notes-both")["needs_review"]
