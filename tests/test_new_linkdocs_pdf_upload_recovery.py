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
        handler = self._const_function("uploadPdfAsPrimary")
        catch_body = re.search(r"\} catch \(error\) \{(?P<body>.*)", handler, flags=re.S)
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
        handler = self._const_function("uploadPdfAsPrimary")

        self.assertIn(
            "PDF uploaded successfully. Processing completed or is available now.",
            handler,
        )
        self.assertIn("clearSelectedPdf();", handler)
        self.assertIn("setIsModalOpen(false);", handler)
        self.assertIn("await fetchFiles();", handler)

    def test_polling_timeout_shows_refresh_before_retry_warning(self):
        handler = self._const_function("uploadPdfAsPrimary")

        self.assertIn(
            "Upload may still be processing. Please refresh this page before retrying to avoid duplicate uploads.",
            handler,
        )

    def test_upload_button_remains_disabled_during_recovery_polling(self):
        handler = self._const_function("handleUpload")
        primary_uploader = self._const_function("uploadPdfAsPrimary")

        self.assertIn("setIsUploading(true);", handler)
        self.assertIn("await uploadPdfAsPrimary(originalFileName);", handler)
        self.assertIn("setIsUploading(false);", handler)
        self.assertIn("const recovered = await findUploadedPdfAfterRejectedRequest(originalFileName);", primary_uploader)
        self.assertLess(
            handler.index("setIsUploading(true);"),
            handler.index("await uploadPdfAsPrimary(originalFileName);"),
        )
        self.assertLess(
            handler.index("await uploadPdfAsPrimary(originalFileName);"),
            handler.rindex("setIsUploading(false);"),
        )
        self.assertIn("disabled={isUploading || !file}", self.html)

    def test_primary_upload_training_reminder_remains_in_loading_copy(self):
        self.assertIn(
            "Uploading and training your PDF. This may take a few minutes. Please keep this page open and do not refresh.",
            self.html,
        )
        self.assertIn("{isKnowledgeOperationInFlight && (", self.html)
        self.assertIn("kw-operation-panel", self.html)
        self.assertIn("Elapsed: {formatElapsedTime(elapsedSeconds)}", self.html)

    def test_recovery_poll_uses_existing_endpoints_and_filename_matching(self):
        matcher = self._const_function("matchesUploadedPdfName")
        poller = self._const_function("findUploadedPdfAfterRejectedRequest")

        self.assertIn("candidateName === originalName", matcher)
        self.assertIn('candidateName.endsWith(`_${originalName}`)', matcher)
        self.assertIn("/api/knowledge/files", poller)
        self.assertIn("/api/knowledge/active", poller)
        self.assertIn("matchesUploadedPdfName(item.display_name || item.original_file_name || item.file_name || item.name || \"\", originalName)", poller)
        self.assertIn("matchesUploadedPdfName(activeName, originalName)", poller)


if __name__ == "__main__":
    unittest.main()
