import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import types

# Mock standard broken imports
if "google" not in sys.modules:
    _g = types.ModuleType("google")
    _g.genai = types.ModuleType("google.genai")
    _g.genai.Client = MagicMock()
    sys.modules["google"] = _g
    sys.modules["google.genai"] = _g.genai
if "fitz" not in sys.modules:
    sys.modules["fitz"] = types.ModuleType("fitz")

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app


def test_default_knowledge_data_folder_remains_repository_data_folder():
    from app.services import knowledge_service

    assert Path(knowledge_service.DATA_FOLDER).name == "data"


MOCK_USER = {
    "id": 1,
    "company_id": 42,
    "full_name": "Test User",
    "email": "test@example.com",
    "role": "admin",
    "status": "active",
}

class TestKnowledgeGraphRoutes(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        from app.services import knowledge_service
        self.repo_data_dir = Path(__file__).resolve().parents[1] / "data"
        self.repo_media_dir = Path(__file__).resolve().parents[1] / "media_uploads"
        self.temp_data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_data_dir.cleanup)
        self.data_folder_patch = patch.object(
            knowledge_service, "DATA_FOLDER", self.temp_data_dir.name
        )
        self.data_folder_patch.start()
        self.addCleanup(self.data_folder_patch.stop)

    def _assert_no_repo_generated_artifact(self, chatbot_id=1, file_id=100):
        generated_names = {
            f"bot_{chatbot_id}_{file_id}_history.json",
            f"bot_{chatbot_id}_{file_id}_readme.md",
            f"bot_{chatbot_id}_readme.md",
        }
        for directory in (self.repo_data_dir, self.repo_media_dir):
            for name in generated_names:
                self.assertFalse(
                    (directory / name).exists(),
                    f"Generated test artifact leaked into repository: {directory / name}",
                )

    def test_temporary_data_folder_cleans_up_after_exception(self):
        from app.services import knowledge_service

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch.object(knowledge_service, "DATA_FOLDER", temp_dir):
                knowledge_service.log_knowledge_modification(
                    1, 100, "Saved entity 'test_node'.", "Graph Modifications"
                )
                self.assertTrue((temp_path / "bot_1_100_history.json").exists())
                with self.assertRaises(RuntimeError):
                    raise RuntimeError("simulated test failure")

        self.assertFalse(temp_path.exists())
        self._assert_no_repo_generated_artifact()

    def _patch_jwt_decode(self):
        return patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        )

    def _patch_user_repo(self, role="admin"):
        return patch(
            "app.database.user_repository.get_user_by_id",
            return_value={**MOCK_USER, "role": role},
        )

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file")
    @patch("app.database.knowledge_graph_repository.upsert_node")
    def test_save_graph_node_success(self, mock_upsert, mock_get_active, mock_verify):
        mock_get_active.return_value = {"id": 100, "file_name": "test.pdf"}
        mock_upsert.return_value = {"id": "test_node", "label": "Product", "properties": {}}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/node?chatbot_id=1",
                json={"name": "test_node", "label": "Product", "properties": {"description": "test"}},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["data"]["id"], "test_node")
            history_path = Path(self.temp_data_dir.name) / "bot_1_100_history.json"
            self.assertTrue(history_path.exists())
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(history[-1]["category"], "Graph Modifications")
            self.assertIn("Saved entity 'test_node'", history[-1]["action"])
            self._assert_no_repo_generated_artifact()

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file")
    @patch("app.database.knowledge_graph_repository.delete_node")
    @patch("app.database.knowledge_graph_repository.delete_edges_by_node")
    def test_delete_graph_node_success(self, mock_delete_edges, mock_delete_node, mock_get_active, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/node?chatbot_id=1&name=test_node",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            mock_delete_edges.assert_called_once()
            mock_delete_node.assert_called_once()

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_file_repository.get_active_pdf_knowledge_file")
    @patch("app.database.knowledge_graph_repository.upsert_edge")
    def test_save_graph_edge_success(self, mock_upsert_edge, mock_get_active, mock_verify):
        mock_get_active.return_value = {"id": 100, "file_name": "test.pdf"}
        mock_upsert_edge.return_value = {"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"}

        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_graph_repository.delete_edge")
    def test_delete_graph_edge_success(self, mock_delete_edge, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            mock_delete_edge.assert_called_once()




    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_graph_repository.delete_edge")
    def test_delete_graph_edge_lowercase_rel_type(self, mock_delete_edge, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "has_price"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            mock_delete_edge.assert_called_once_with(1, "src", "tgt", "has_price")

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_graph_repository.delete_edge")
    def test_delete_graph_edge_rel_type_with_spaces(self, mock_delete_edge, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "connected to"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data["status"], "success")
            mock_delete_edge.assert_called_once_with(1, "src", "tgt", "connected to")

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_delete_graph_edge_missing_source(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_delete_graph_edge_missing_target(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_delete_graph_edge_missing_rel_type(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    def test_delete_graph_edge_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_graph_repository.delete_edge")
    def test_delete_graph_edge_unauthorized_role(self, mock_delete_edge, mock_verify):
        mock_verify.return_value = {"id": 1, "company_id": 42}
        with patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 42, "user_id": 1, "role": "admin"},
        ), self._patch_user_repo(role="member"):
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 403)
            data = resp.get_json()
            self.assertIn("permission", data.get("message", "").lower())

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_graph_repository.delete_edge")
    def test_delete_graph_edge_cross_company_access(self, mock_delete_edge, mock_verify):
        mock_verify.side_effect = PermissionError("Cross-company access denied")
        with patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 99, "user_id": 1, "role": "admin"},
        ), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 403)




    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_save_graph_node_missing_name(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/node?chatbot_id=1",
                json={"label": "Product"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_save_graph_node_missing_label(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/node?chatbot_id=1",
                json={"name": "test_node"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    def test_save_graph_node_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/node",
                json={"name": "test_node", "label": "Product"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_delete_graph_node_missing_name(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/node?chatbot_id=1",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    def test_delete_graph_node_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/node?name=test_node",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    @patch("app.database.knowledge_graph_repository.delete_node")
    @patch("app.database.knowledge_graph_repository.delete_edges_by_node")
    def test_delete_graph_node_cross_company_access(self, mock_delete_edges, mock_delete_node, mock_verify):
        mock_verify.side_effect = PermissionError("Cross-company access denied")
        with patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": 99, "user_id": 1, "role": "admin"},
        ), self._patch_user_repo():
            resp = self.client.delete(
                "/api/knowledge/graph/node?chatbot_id=1&name=test_node",
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 403)

    def test_save_graph_edge_missing_chatbot_id(self):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/edge",
                json={"source_name": "src", "target_name": "tgt", "rel_type": "HAS_PRICE"},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)

    @patch("app.routes.knowledge_routes.verify_chatbot_access")
    def test_save_graph_edge_missing_all_fields(self, mock_verify):
        with self._patch_jwt_decode(), self._patch_user_repo():
            resp = self.client.post(
                "/api/knowledge/graph/edge?chatbot_id=1",
                json={},
                headers={"Authorization": "Bearer test-token"}
            )
            self.assertEqual(resp.status_code, 400)
