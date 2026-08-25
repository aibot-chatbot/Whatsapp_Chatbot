from pathlib import Path


CRM_HTML = Path(__file__).resolve().parents[1] / "frontend" / "crm.html"


def test_legacy_crm_page_consumes_the_canonical_lead_stages():
    html = CRM_HTML.read_text(encoding="utf-8")

    for status in ("new", "contacted", "qualified", "won", "lost"):
        assert f'data-status-card="{status}"' in html
        assert f'option value="{status}"' in html

    assert "counts.new + counts.contacted + counts.qualified" in html
    assert "counts.won + counts.lost" in html
    assert 'option value="in_progress"' not in html
    assert 'option value="closed"' not in html


def test_legacy_crm_page_normalizes_retired_read_values():
    html = CRM_HTML.read_text(encoding="utf-8")

    assert 'in_progress: "contacted"' in html
    assert 'closed: "lost"' in html
