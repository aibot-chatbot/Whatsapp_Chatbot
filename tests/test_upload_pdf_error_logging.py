"""Focused regression for PDF upload failure logging."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
VIEWS_PY = ROOT / "app" / "views.py"


class TestUploadPdfErrorLogging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = VIEWS_PY.read_text(encoding="utf-8")

    def test_upload_pdf_generic_exception_logs_traceback(self):
        self.assertIn("chatbot_id = None", self.source)
        self.assertIn(
            'logging.exception("PDF upload failed for chatbot_id=%s", chatbot_id)',
            self.source,
        )

    def test_upload_pdf_imports_flask_g_for_billing_guard(self):
        flask_import = re.search(
            r"from flask import (?P<imports>.*)",
            self.source,
        ).group("imports")

        self.assertIn("g", {item.strip() for item in flask_import.split(",")})
        self.assertIn("can_upload_knowledge_file(g.company_id)", self.source)
        self.assertIn("can_upload_knowledge_storage(g.company_id, incoming_size)", self.source)

    def test_upload_pdf_generic_exception_returns_user_friendly_message(self):
        generic_except = re.search(
            r"except Exception:\n(?P<body>.*?return jsonify\(\{.*?\}\), 500)",
            self.source,
            flags=re.S,
        ).group("body")

        self.assertIn(
            '"message": "PDF upload failed. Please check the server logs for details."',
            generic_except,
        )
        self.assertNotIn('"message": str(e)', generic_except)


if __name__ == "__main__":
    unittest.main()
