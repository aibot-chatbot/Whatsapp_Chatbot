"""Callers import generate_system_response inside functions, and tests replace it with a plain
mock that accepts any argument, so a wrong keyword only fails in production."""
import ast
import inspect
from pathlib import Path
from unittest.mock import patch

from app.services import ai_router, knowledge_service

APP_DIR = Path(__file__).resolve().parents[1] / "app"
GOOD_REPLY = '{"nodes": [], "relationships": []}'


def test_graph_extraction_reaches_the_ai_with_a_valid_call():
    with patch("app.services.ai_router.generate_system_response", autospec=True) as generate, patch("time.sleep"):
        generate.return_value = GOOD_REPLY

        knowledge_service._extract_and_store_graph_supabase(["some text"], 1, 1)

    generate.assert_called_once()


def test_every_caller_uses_arguments_the_function_accepts():
    accepted = set(inspect.signature(ai_router.generate_system_response).parameters)
    wrong = []
    for path in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", getattr(node.func, "id", "")) != "generate_system_response":
                continue
            wrong += [f"{path.name}:{node.lineno} {kw.arg}" for kw in node.keywords if kw.arg and kw.arg not in accepted]

    assert wrong == []
