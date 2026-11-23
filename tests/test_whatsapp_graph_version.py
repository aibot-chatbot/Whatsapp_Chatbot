import inspect
from pathlib import Path

import pytest
from flask import Flask

from app.routes import whatsapp_routes


@pytest.mark.parametrize(("override", "expected"), [(None, "v25.0"), ("v26.0", "v26.0")])
def test_embedded_signup_config_uses_whatsapp_graph_version(monkeypatch, override, expected):
    monkeypatch.setenv("WHATSAPP_META_APP_ID", "123")
    monkeypatch.setenv("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "456")
    monkeypatch.setenv("VERSION", "unused-legacy-version")
    if override:
        monkeypatch.setenv("WHATSAPP_GRAPH_API_VERSION", override)
    else:
        monkeypatch.delenv("WHATSAPP_GRAPH_API_VERSION", raising=False)
    with Flask(__name__).app_context():
        response, status = inspect.unwrap(whatsapp_routes.get_embedded_signup_config)()
    assert status == 200
    assert response.get_json()["data"]["graph_api_version"] == expected


def test_no_obsolete_whatsapp_graph_version_in_runtime():
    root = Path(__file__).resolve().parents[1]
    paths = [*root.joinpath("app").rglob("*.py"), root / "web/public/assets/js/integration.js"]
    assert not [str(path.relative_to(root)) for path in paths if "v22.0" in path.read_text(encoding="utf-8")]
