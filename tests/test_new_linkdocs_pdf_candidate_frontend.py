"""Static frontend regressions for Supporting PDF candidate validation."""

from pathlib import Path
import re
import unittest


class TestNewLinkdocsPdfCandidateFrontend(unittest.TestCase):
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

    def test_no_primary_uses_existing_primary_upload_path(self):
        handler = self._const_function("handleUpload")

        self.assertIn("if (hasPrimarySource)", handler)
        self.assertIn("await validatePdfCandidate();", handler)
        self.assertIn("await uploadPdfAsPrimary(originalFileName);", handler)

    def test_primary_exists_uses_candidate_validation_endpoint(self):
        validator = self._const_function("validatePdfCandidate")

        self.assertIn("/api/knowledge/pdf-candidates/validate", validator)
        self.assertIn('formData.append("pdf_file", file);', validator)
        self.assertNotIn("/upload-pdf", validator)

    def test_candidate_pass_requires_explicit_confirmation(self):
        validator = self._const_function("validatePdfCandidate")
        confirmer = self._const_function("handleConfirmPdfCandidate")

        self.assertNotIn("/confirm", validator)
        self.assertIn("/api/knowledge/pdf-candidates/", confirmer)
        self.assertIn("/confirm", confirmer)
        self.assertIn("Add as Supporting Knowledge", self.html)

    def test_pass_confirmation_refreshes_sources_and_closes_modal(self):
        confirmer = self._const_function("handleConfirmPdfCandidate")

        self.assertIn("await fetchFiles();", confirmer)
        self.assertIn("setIsModalOpen(false);", confirmer)
        self.assertIn("was added as Supporting knowledge.", confirmer)

    def test_failed_and_duplicate_candidates_cannot_confirm(self):
        self.assertIn('const pdfCandidatePassed = pdfCandidateStatus === "validated_passed" && pdfCandidateResult?.can_confirm === true;', self.html)
        self.assertIn('const pdfCandidateExactDuplicate = pdfCandidateDuplicate === "exact_content_duplicate";', self.html)
        self.assertIn("Choose another PDF", self.html)
        self.assertIn("This PDF appears to contain the same content as your current Primary source.", self.html)

    def test_threshold_display_uses_backend_value_without_frontend_decision_logic(self):
        self.assertIn("Relevance Score", self.html)
        self.assertIn("Required Score", self.html)
        self.assertIn("formatRelevanceScore(pdfCandidateResult.relevance_score)", self.html)
        self.assertIn("formatRelevanceScore(pdfCandidateResult.threshold)", self.html)
        self.assertNotIn("0.65", self.html)

    def test_display_name_is_used_for_source_list_and_primary_context(self):
        self.assertIn("getSourceDisplayName(f)", self.html)
        self.assertIn("primarySourceDisplayName || pdfCandidateResult.primary?.display_name || pdfCandidateResult.primary?.original_file_name", self.html)
        self.assertIn("triggerDeleteFile(source.actionName, source.name)", self.html)

    def test_candidate_primary_label_prefers_current_readable_source_name(self):
        self.assertIn('const primarySourceDisplayName = primarySource ? getSourceDisplayName(primarySource, "") : "";', self.html)
        self.assertLess(
            self.html.index("primarySourceDisplayName || pdfCandidateResult.primary?.display_name"),
            self.html.index("|| pdfCandidateResult.primary?.file_name || \"Current Primary\""),
        )

    def test_special_backend_errors_are_mapped_to_friendly_copy(self):
        self.assertIn("primary_changed_revalidation_required", self.html)
        self.assertIn("Your Primary knowledge source changed after this PDF was checked. Please validate the PDF again.", self.html)
        self.assertIn("candidate_expired", self.html)
        self.assertIn("This validation has expired. Please check the PDF again.", self.html)
        self.assertIn("candidate_recovery_state_conflict", self.html)
        self.assertIn("primary_embeddings_unavailable", self.html)
        self.assertIn("The current Primary source is missing validation data. Please reprocess the Primary PDF before checking Supporting PDFs.", self.html)
        self.assertIn("validation_embedding_failed", self.html)
        self.assertIn("validation_embedding_cardinality_mismatch", self.html)
        self.assertIn("We couldn't complete document validation. Please try again.", self.html)

    def test_semantic_system_failures_are_not_rendered_as_relevance_failures(self):
        validator = self._const_function("validatePdfCandidate")

        self.assertIn('data.error_code && ["primary_embeddings_unavailable", "validation_embedding_failed", "validation_embedding_cardinality_mismatch"].includes(data.error_code)', validator)
        self.assertIn("candidateFriendlyError(data.error_code, data.reason)", validator)
        self.assertIn("const pdfCandidateSystemError =", self.html)
        self.assertIn("Validation could not complete", self.html)
        self.assertIn("!pdfCandidatePassed && !pdfCandidateSystemError", self.html)

    def test_terminal_candidate_errors_clear_stale_pass_state(self):
        confirmer = self._const_function("handleConfirmPdfCandidate")

        self.assertIn('["primary_changed_revalidation_required", "candidate_expired", "candidate_not_confirmable"].includes(result.code)', confirmer)
        self.assertIn('if (result.code === "candidate_file_missing")', confirmer)
        self.assertIn("clearSelectedPdf();", confirmer)
        self.assertNotIn('result.code === "candidate_confirmation_in_progress"', confirmer)

    def test_primary_changed_and_expired_keep_file_available_for_revalidation(self):
        confirmer = self._const_function("handleConfirmPdfCandidate")

        reset_block = re.search(
            r'\["primary_changed_revalidation_required", "candidate_expired", "candidate_not_confirmable"\][\s\S]*?setPdfCandidateResult\(null\);[\s\S]*?\}',
            confirmer,
        )
        self.assertIsNotNone(reset_block)
        self.assertNotIn("clearSelectedPdf();", reset_block.group(0))

    def test_set_primary_uses_internal_name_but_visible_display_name(self):
        setter = self._const_function("handleSetActive")

        self.assertIn("const handleSetActive = async (fileName, displayName = fileName)", self.html)
        self.assertIn("body: JSON.stringify({ file_name: fileName })", setter)
        self.assertIn("`${displayName} is now the active primary knowledge.`", setter)
        self.assertIn("handleSetActive(source.actionName, source.name)", self.html)

    def test_delete_uses_internal_name_but_visible_display_name(self):
        deleter = self._const_function("confirmDeleteFile")

        self.assertIn("const fileName = fileToDelete.fileName;", deleter)
        self.assertIn("const displayName = fileToDelete.displayName || fileName;", deleter)
        self.assertIn("/api/knowledge/files/${encodeURIComponent(fileName)}", deleter)
        self.assertIn("`${displayName} deleted successfully.`", deleter)

    def test_refinement_receives_readable_primary_display_name(self):
        self.assertIn("function KnowledgeRefinement({ botId, activeFile, activeFileDisplayName })", self.html)
        self.assertIn("const primarySourceLabel = activeFileDisplayName || activeFile;", self.html)
        self.assertIn("activeFileDisplayName={primarySourceDisplayName}", self.html)

    def test_supporting_confirmation_loading_copy_uses_confirming_state(self):
        self.assertIn("{(isUploading || isValidatingPdf || isConfirmingPdf) && (", self.html)
        self.assertIn('isConfirmingPdf\n                                                        ? "Adding Supporting Knowledge. Knowledge processing is now occurring."', self.html)
        self.assertIn('isValidatingPdf\n                                                    ? "We are reading this PDF and checking whether it is related to your current Primary knowledge source."', self.html)

    def test_file_input_has_native_reset_helper(self):
        self.assertIn("const pdfFileInputRef = React.useRef(null);", self.html)
        self.assertIn("const clearSelectedPdf = () => {", self.html)
        self.assertIn("pdfFileInputRef.current.value = \"\";", self.html)
        self.assertIn("ref={pdfFileInputRef}", self.html)
        self.assertIn("pdfFileInputRef.current?.click()", self.html)

    def test_choose_another_pdf_resets_native_input(self):
        self.assertIn("Choose another PDF", self.html)
        self.assertIn("clearSelectedPdf();\n                                            setPdfCandidateResult(null);", self.html)

    def test_double_confirm_and_close_are_guarded(self):
        confirmer = self._const_function("handleConfirmPdfCandidate")

        self.assertIn("isConfirmingPdf", confirmer)
        self.assertIn("disabled={isConfirmingPdf || isValidatingPdf}", self.html)
        self.assertIn("disabled={busyAddingSource}", self.html)

    def test_candidate_cancel_endpoint_is_used_for_abandoned_pass(self):
        cancel = self._const_function("cancelCurrentCandidate")

        self.assertIn("/api/knowledge/pdf-candidates/", cancel)
        self.assertIn("/cancel", cancel)
        self.assertIn('method: "POST"', cancel)

    def test_website_workflow_stays_on_existing_endpoints(self):
        self.assertIn("/api/knowledge/scrape-analyze", self.html)
        self.assertIn("/api/knowledge/scrape-extract", self.html)
        self.assertIn("/api/knowledge/scrape-embed", self.html)
        self.assertIn("Save website", self.html)


if __name__ == "__main__":
    unittest.main()
