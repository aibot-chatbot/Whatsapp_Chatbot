"""Frontend regressions for the knowledge workspace source roles.

The Role column used to be derived in the browser from is_active plus
file_type, which labelled every non-primary document "Inactive / Needs
review". The backend names the role now; the page reads it and keeps the old
derivation only as a fallback.
"""

from pathlib import Path
import unittest


class TestNewLinkdocsSourceRoles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("web/src/legacy/new_linkdocs.jsx").read_text(encoding="utf-8")

    def test_role_comes_from_the_backend_field(self):
        self.assertIn('ROLE_LABELS[String(f.role || "").toLowerCase()]', self.html)
        self.assertIn("const ROLE_LABELS = {", self.html)

    def test_client_side_derivation_survives_as_a_fallback(self):
        # An API build without the role field must not blank the column.
        self.assertIn(
            '|| ((!isWebsite && Boolean(f.is_active)) ? "Primary" : (enabled ? "Supporting" : "Inactive"))',
            self.html,
        )

    def test_needs_review_now_means_a_failed_ingest(self):
        self.assertIn(
            'const failedIngest = String(f.processing_status || "").toLowerCase() === "failed";',
            self.html,
        )
        self.assertIn('statusKey: failedIngest ? "review" : (inUse ? "ready" : "off"),', self.html)
        self.assertNotIn('statusKey: inUse ? "ready" : (isWebsite ? "off" : "review"),', self.html)

    def test_documents_get_the_same_enable_toggle_as_websites(self):
        self.assertIn("{!source.isPrimary && (", self.html)
        self.assertIn("handleToggleSupport(source.actionName, !source.enabled)", self.html)
        self.assertNotIn("{source.isWebsite && (", self.html)

    def test_display_name_is_used_for_human_facing_source_labels(self):
        self.assertIn("const getSourceDisplayName = (item, fallback = \"Untitled source\") => item?.display_name || item?.original_file_name || item?.file_name", self.html)
        self.assertIn("name: getSourceDisplayName(f),", self.html)
        self.assertIn("actionName: getSourceActionName(f),", self.html)

    def test_supporting_count_follows_the_role(self):
        self.assertIn(
            'const supportingCount = sources.filter(s => s.role === "Supporting").length;',
            self.html,
        )

    def test_upload_banner_reports_a_failed_extraction(self):
        # `outcome` is the polled ingest result, falling back to the upload's own
        # reply: reading the document finishes after the response now, so the
        # upload reply alone can no longer say whether extraction succeeded.
        self.assertIn('const outcome = processed || uploadResult;', self.html)
        self.assertIn('const extractionFailed = outcome.status === "failed";', self.html)
        self.assertNotIn(
            'setStatus({ type: "success", text: "PDF uploaded and set as primary knowledge.", action: "upload" });',
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
