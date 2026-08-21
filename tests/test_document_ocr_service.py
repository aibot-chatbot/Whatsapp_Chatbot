"""Tests for app/services/document_ocr_service.py.

The point of this module is that a scanned PDF becomes knowledge instead of a
zero-chunk failure, and that a host without PaddleOCR still ingests text-layer
PDFs perfectly well. Both halves are covered here, and nothing below needs
paddle OR PyMuPDF installed: `tests/conftest.py:36` already stubs `fitz`, so
documents are faked at the seam the way the rest of this suite does it.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services import document_ocr_service as ocr


def span(text, size=10.0, bold=False):
    # PyMuPDF packs style into a bit field; bit 4 (16) is bold.
    return {"text": text, "size": size, "flags": 16 if bold else 0}


def text_page(lines):
    """A fake page whose get_text("dict") returns one block per line group."""
    page = MagicMock()
    page.get_text.return_value = {
        "blocks": [{"type": 0, "lines": [{"spans": spans} for spans in lines]}]
    }
    return page


def blank_page():
    """A page with no text layer at all, standing in for a scan."""
    page = MagicMock()
    page.get_text.return_value = {"blocks": []}
    return page


def fake_document(pages):
    document = MagicMock()
    document.page_count = len(pages)
    document.__iter__ = lambda self: iter(pages)
    return document


BODY = [span("Enough characters on this line to count as a real text layer.")]


class MarkdownShapingTests(unittest.TestCase):
    """The Markdown stage, measured line by line."""

    def test_large_short_line_becomes_a_heading(self):
        self.assertEqual(
            ocr._as_markdown_line("Opening Hours", size=20.0, body_size=10.0, bold=False),
            "# Opening Hours",
        )

    def test_heading_sizing_is_relative_not_absolute(self):
        # 20pt is a heading in a 10pt document and body text in a 20pt one.
        self.assertTrue(ocr._as_markdown_line("Title", 20.0, 10.0, False).startswith("#"))
        self.assertFalse(ocr._as_markdown_line("Title", 20.0, 20.0, False).startswith("#"))

    def test_a_long_line_stays_prose_however_large(self):
        long_line = "We are open every day of the week except public holidays " * 3
        self.assertFalse(
            ocr._as_markdown_line(long_line, size=24.0, body_size=10.0, bold=False).startswith("#")
        )

    def test_bold_short_line_is_a_minor_heading(self):
        self.assertEqual(
            ocr._as_markdown_line("Prices", size=10.0, body_size=10.0, bold=True),
            "### Prices",
        )

    def test_bullets_and_numbers_become_markdown_lists(self):
        self.assertEqual(ocr._as_markdown_line("\u2022 Nasi lemak", 10.0, 10.0, False), "- Nasi lemak")
        self.assertEqual(ocr._as_markdown_line("1. Nasi lemak", 10.0, 10.0, False), "1. Nasi lemak")

    def test_paragraph_lines_are_joined_and_structure_is_kept_apart(self):
        joined = ocr._join_blocks(["# Menu", "Nasi lemak", "with sambal", "", "- Teh tarik"])
        self.assertEqual(joined, "# Menu\n\nNasi lemak with sambal\n\n- Teh tarik")

    def test_blank_input_yields_nothing(self):
        self.assertEqual(ocr._as_markdown_line("   ", 10.0, 10.0, False), "")

    def test_body_size_is_the_most_common_size_by_characters(self):
        page = text_page([
            [span("A very long run of ordinary body copy at ten point.", 10.0)],
            [span("Title", 24.0)],
        ])
        self.assertEqual(ocr._body_font_size(page), 10.0)


class NativeExtractionTests(unittest.TestCase):
    """A PDF with a real text layer must never reach the OCR engine."""

    def test_text_layer_is_read_without_calling_ocr(self):
        document = fake_document([text_page([[span("Opening Hours", 22.0)], BODY, BODY])])

        with patch("fitz.open", return_value=document, create=True), \
             patch.object(ocr, "_ocr_page_markdown") as ocr_page:
            result = ocr.extract_pdf_markdown("any.pdf")

        ocr_page.assert_not_called()
        self.assertFalse(result.ocr_used)
        self.assertEqual(result.ocr_page_count, 0)
        self.assertIn("Opening Hours", result.markdown)
        self.assertGreater(result.character_count, 0)
        self.assertEqual(result.error, "")

    def test_the_largest_line_becomes_a_heading(self):
        document = fake_document([text_page([[span("Price List", 24.0)], BODY, BODY])])

        with patch("fitz.open", return_value=document, create=True):
            result = ocr.extract_pdf_markdown("any.pdf")

        self.assertIn("# Price List", result.markdown)
        self.assertIn("Price List", result.headings)

    def test_page_count_reflects_the_document(self):
        pages = [text_page([BODY, BODY]) for _ in range(3)]

        with patch("fitz.open", return_value=fake_document(pages), create=True):
            result = ocr.extract_pdf_markdown("any.pdf")

        self.assertEqual(result.page_count, 3)

    def test_an_unreadable_file_reports_an_error_instead_of_raising(self):
        with patch("fitz.open", side_effect=RuntimeError("not a PDF"), create=True):
            result = ocr.extract_pdf_markdown("broken.pdf")

        self.assertEqual(result.error, "not a PDF")
        self.assertFalse(result.has_text)

    def test_one_bad_page_does_not_lose_the_rest(self):
        good = text_page([[span("Opening Hours", 22.0)], BODY, BODY])
        bad = MagicMock()
        bad.get_text.side_effect = RuntimeError("corrupt page")

        with patch("fitz.open", return_value=fake_document([bad, good]), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=False):
            result = ocr.extract_pdf_markdown("any.pdf")

        self.assertIn("Opening Hours", result.markdown)
        self.assertEqual(result.error, "")

    def test_result_is_immutable(self):
        result = ocr.ExtractionResult(markdown="x", character_count=1)
        with self.assertRaises(Exception):
            result.markdown = "y"


class ScannedPdfTests(unittest.TestCase):
    """A PDF with no text layer is the whole reason this module exists."""

    def scan(self, pages=2):
        return fake_document([blank_page() for _ in range(pages)])

    def test_ocr_is_used_when_there_is_no_text_layer(self):
        with patch("fitz.open", return_value=self.scan(), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=True), \
             patch.object(ocr, "_ocr_page_markdown", return_value="# Menu\n\nNasi lemak 5.00"):
            result = ocr.extract_pdf_markdown("scan.pdf")

        self.assertTrue(result.ocr_used)
        self.assertEqual(result.ocr_page_count, 2)
        self.assertIn("Nasi lemak", result.markdown)

    def test_a_thin_text_layer_still_triggers_ocr(self):
        # Scanned pages often carry a page number or a header as real text
        # while the body is an image. That must not count as a text layer.
        thin = text_page([[span("3", 9.0)]])

        with patch("fitz.open", return_value=fake_document([thin]), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=True), \
             patch.object(ocr, "_ocr_page_markdown", return_value="Nasi lemak 5.00") as ocr_page:
            result = ocr.extract_pdf_markdown("scan.pdf")

        ocr_page.assert_called_once()
        self.assertEqual(result.ocr_page_count, 1)

    def test_without_paddle_the_scan_yields_nothing_and_says_so(self):
        with patch("fitz.open", return_value=self.scan(), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=False), \
             patch.object(ocr, "_ocr_page_markdown") as ocr_page:
            result = ocr.extract_pdf_markdown("scan.pdf")

        ocr_page.assert_not_called()
        self.assertFalse(result.ocr_available)
        self.assertFalse(result.has_text)
        # Not an error: the read completed, it just found nothing. Turning "no
        # text" into a failed upload is the caller's job, not this module's.
        self.assertEqual(result.error, "")

    def test_page_budget_stops_runaway_ocr_and_flags_it(self):
        with patch("fitz.open", return_value=self.scan(5), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=True), \
             patch.object(ocr, "OCR_PAGE_LIMIT", 2), \
             patch.object(ocr, "_ocr_page_markdown", return_value="recognised text"):
            result = ocr.extract_pdf_markdown("big.pdf")

        self.assertEqual(result.ocr_page_count, 2)
        self.assertTrue(result.truncated)

    def test_a_page_ocr_cannot_read_does_not_count_as_scanned(self):
        with patch("fitz.open", return_value=self.scan(), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=True), \
             patch.object(ocr, "_ocr_page_markdown", return_value=""):
            result = ocr.extract_pdf_markdown("scan.pdf")

        self.assertEqual(result.ocr_page_count, 0)
        self.assertFalse(result.has_text)

    def test_summary_reports_what_the_operator_needs(self):
        with patch("fitz.open", return_value=self.scan(), create=True), \
             patch.object(ocr, "is_ocr_available", return_value=True), \
             patch.object(ocr, "_ocr_page_markdown", return_value="# Menu\n\nNasi lemak"):
            summary = ocr.extract_pdf_markdown("scan.pdf").summary()

        self.assertEqual(summary["page_count"], 2)
        self.assertEqual(summary["ocr_page_count"], 2)
        self.assertTrue(summary["ocr_used"])
        self.assertFalse(summary["truncated"])
        self.assertIn("Menu", summary["headings"])


class EngineSeamTests(unittest.TestCase):
    """The paddle import must never be able to break the app."""

    def setUp(self):
        ocr._ocr_engine = None
        ocr._ocr_engine_failed = False

    tearDown = setUp

    def test_a_missing_paddle_degrades_instead_of_raising(self):
        import builtins

        real_import = builtins.__import__

        def no_paddle(name, *args, **kwargs):
            if name.startswith("paddleocr"):
                raise ImportError("No module named 'paddleocr'")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=no_paddle):
            self.assertIsNone(ocr._get_ocr_engine())
            self.assertFalse(ocr.is_ocr_available())

    def test_the_engine_is_built_once_and_reused(self):
        built = []

        class FakeEngine:
            def predict(self, image):
                return []

        def fake_paddle(**kwargs):
            built.append(kwargs)
            return FakeEngine()

        module = type("paddleocr", (), {"PaddleOCR": staticmethod(fake_paddle)})
        real_import = __import__

        def importer(name, *args, **kwargs):
            if name == "paddleocr":
                return module
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=importer):
            first = ocr._get_ocr_engine()
            second = ocr._get_ocr_engine()

        self.assertIs(first, second)
        self.assertEqual(len(built), 1, "PaddleOCR should be constructed once per process")

    def test_a_constructor_that_rejects_old_kwargs_still_builds(self):
        # PaddleOCR renamed use_angle_cls to use_textline_orientation between
        # 2.x and 3.x. Whichever the host has, one of the attempts must win.
        accepted = {}

        class FakeEngine:
            pass

        def picky(**kwargs):
            if "use_angle_cls" in kwargs:
                raise TypeError("unexpected keyword argument 'use_angle_cls'")
            accepted.update(kwargs)
            return FakeEngine()

        module = type("paddleocr", (), {"PaddleOCR": staticmethod(picky)})
        real_import = __import__

        def importer(name, *args, **kwargs):
            return module if name == "paddleocr" else real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=importer):
            engine = ocr._get_ocr_engine()

        self.assertIsNotNone(engine)
        self.assertIn("lang", accepted)


class OcrOutputNormalisationTests(unittest.TestCase):
    """Both PaddleOCR result shapes have to flatten to the same tuples."""

    def test_two_x_shape(self):
        raw = [[
            [[[0, 0], [50, 0], [50, 20], [0, 20]], ("Nasi lemak", 0.97)],
        ]]
        items = ocr._normalise_ocr_output(raw)
        self.assertEqual(len(items), 1)
        text, score, height, top = items[0]
        self.assertEqual(text, "Nasi lemak")
        self.assertAlmostEqual(score, 0.97)
        self.assertAlmostEqual(height, 20.0)
        self.assertAlmostEqual(top, 0.0)

    def test_three_x_shape(self):
        raw = [{
            "rec_texts": ["Teh tarik", "3.50"],
            "rec_scores": [0.99, 0.88],
            "rec_polys": [
                [[0, 10], [40, 10], [40, 28], [0, 28]],
                [[0, 40], [40, 40], [40, 55], [0, 55]],
            ],
        }]
        items = ocr._normalise_ocr_output(raw)
        self.assertEqual([item[0] for item in items], ["Teh tarik", "3.50"])
        self.assertAlmostEqual(items[0][2], 18.0)
        self.assertAlmostEqual(items[1][3], 40.0)

    def test_malformed_entries_are_skipped_not_fatal(self):
        self.assertEqual(ocr._normalise_ocr_output([[["broken"], None, 42]]), [])

    def test_empty_input(self):
        self.assertEqual(ocr._normalise_ocr_output(None), [])
        self.assertEqual(ocr._normalise_ocr_output([]), [])


if __name__ == "__main__":
    unittest.main()


class ChunkerUnderstandsMarkdownTests(unittest.TestCase):
    """Extraction emits Markdown now, so the chunker has to read it.

    Without this the reader's own headings would be demoted to body text the
    moment they gained a "#", which is worse than the plain text it replaced.
    """

    def test_markdown_headings_are_recognised(self):
        from app.services.rag_service import is_probable_heading

        for line in ("# Opening Hours", "## Payment methods", "###### Deep section"):
            self.assertTrue(is_probable_heading(line), line)

    def test_the_old_heading_shapes_still_work(self):
        from app.services.rag_service import is_probable_heading

        for line in ("PAYMENT METHODS", "3. ACCOMMODATION & BOOKING", "A. REFUND POLICY"):
            self.assertTrue(is_probable_heading(line), line)

    def test_prose_and_bare_hashes_are_not_headings(self):
        from app.services.rag_service import is_probable_heading

        for line in ("ordinary sentence here", "#NoSpace", "#", "   "):
            self.assertFalse(is_probable_heading(line), line)

    def test_section_titles_drop_their_markers(self):
        from app.services.rag_service import get_last_heading

        # "## Refunds" prepended to a chunk would read as literal hashes to the
        # model, so the markers come off before the title is used as prose.
        self.assertEqual(get_last_heading("## Refund Policy\nsome body text"), "Refund Policy")

    def test_a_markdown_document_still_chunks(self):
        from app.services.rag_service import split_text_into_sections

        markdown = (
            "# Opening Hours\n\n"
            "We open at nine every morning and close at six in the evening.\n\n"
            "## Payment methods\n\n"
            "- Cash\n- Card\n- QR transfer\n"
        )
        chunks = split_text_into_sections(markdown)

        self.assertTrue(chunks)
        self.assertTrue(any("Opening Hours" in chunk for chunk in chunks))
