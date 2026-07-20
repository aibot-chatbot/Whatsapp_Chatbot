"""Frontend regressions for long-running PDF upload recovery UX."""

from pathlib import Path
import re
import unittest


class TestNewLinkdocsPdfUploadRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("frontend/new_linkdocs.html").read_text(encoding="utf-8")

    def _const_function(self, name):
        match = re.search(
            rf"const {name} = .*?=> \{{(?P<body>.*?)\n            \}};",
            self.html,
            flags=re.S,
        )
        self.assertIsNotNone(match, f"{name} was not found")
        return match.group("body")

    def test_rejected_pdf_upload_starts_recovery_polling(self):
        handler = self._const_function("handleUpload")
        catch_body = re.search(r"\} catch \(error\) \{(?P<body>.*?)\n                \} finally \{", handler, flags=re.S)
        self.assertIsNotNone(catch_body)
        body = catch_body.group("body")

        self.assertIn(
            "Upload is taking longer than expected. The PDF may still be processing. Checking status...",
            body,
        )
        self.assertIn("findUploadedPdfAfterRejectedRequest(originalFileName)", body)
        self.assertNotIn("Network connection failed. Is the backend running?", body)
        self.assertNotIn('method: "POST"', body)

    def test_matching_uploaded_file_shows_success_and_refreshes_list(self):
        handler = self._const_function("handleUpload")

        self.assertIn(
            "PDF uploaded successfully. Processing completed or is available now.",
            handler,
        )
        self.assertIn("setFile(null);", handler)
        self.assertIn("setIsModalOpen(false);", handler)
        self.assertIn("await fetchFiles();", handler)

    def test_polling_timeout_shows_refresh_before_retry_warning(self):
        handler = self._const_function("handleUpload")

        self.assertIn(
            "Upload may still be processing. Please refresh this page before retrying to avoid duplicate uploads.",
            handler,
        )

    def test_upload_button_remains_disabled_during_recovery_polling(self):
        handler = self._const_function("handleUpload")

        self.assertIn("setIsUploading(true);", handler)
        self.assertIn("const recovered = await findUploadedPdfAfterRejectedRequest(originalFileName);", handler)
        self.assertIn("setIsUploading(false);", handler)
        self.assertLess(
            handler.index("setIsUploading(true);"),
            handler.index("const recovered = await findUploadedPdfAfterRejectedRequest(originalFileName);"),
        )
        self.assertLess(
            handler.index("const recovered = await findUploadedPdfAfterRejectedRequest(originalFileName);"),
            handler.rindex("setIsUploading(false);"),
        )
        self.assertIn("disabled={isUploading || !file}", self.html)

    def test_upload_training_reminder_is_shown_only_while_uploading(self):
        self.assertIn(
            "Uploading and training your PDF. This may take a few minutes. Please keep this page open and do not refresh.",
            self.html,
        )
        self.assertIn("{isUploading && (", self.html)
        reminder_index = self.html.index(
            "Uploading and training your PDF. This may take a few minutes. Please keep this page open and do not refresh."
        )
        gate_index = self.html.rfind("{isUploading && (", 0, reminder_index)
        self.assertNotEqual(gate_index, -1)
        self.assertLess(gate_index, reminder_index)

    def test_recovery_poll_uses_existing_endpoints_and_filename_matching(self):
        matcher = self._const_function("matchesUploadedPdfName")
        poller = self._const_function("findUploadedPdfAfterRejectedRequest")

        self.assertIn("candidateName === originalName", matcher)
        self.assertIn('candidateName.endsWith(`_${originalName}`)', matcher)
        self.assertIn("/api/knowledge/files", poller)
        self.assertIn("/api/knowledge/active", poller)
        self.assertIn("matchesUploadedPdfName(item.file_name || item.name || \"\", originalName)", poller)
        self.assertIn("matchesUploadedPdfName(activeName, originalName)", poller)


if __name__ == "__main__":
    unittest.main()
