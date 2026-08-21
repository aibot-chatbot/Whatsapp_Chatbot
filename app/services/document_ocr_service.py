"""document_ocr_service.py - PDF text extraction with a PaddleOCR fallback.

The pipeline the product asked for is: OCR scan -> convert to Markdown ->
check the source -> list the content. This module owns the first two stages
and reports the facts the other two need.

The order matters. Most PDFs carry a real text layer, and reading that layer is
exact, instant and free. OCR is the fallback for pages where the layer is
missing or too thin to be the whole page: a scanned contract, a photographed
menu, a price list exported as an image. Running OCR on a page that already has
text is slower AND less accurate, so it is never the first move.

PaddleOCR (https://github.com/PaddlePaddle/PaddleOCR, Apache-2.0) is imported
lazily and cached. The app must boot, and a text-layer PDF must still ingest,
on a machine where paddle is not installed at all -- so every entry point here
degrades to native extraction and says so in the result rather than raising.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass

#: Pages beyond this are not OCR'd. Upload is a synchronous HTTP request and
#: OCR costs roughly one to three seconds per page, so a 200-page scan would
#: sit behind a proxy timeout and fail with nothing to show. The cap keeps the
#: request bounded and the result honest: `truncated` says pages were skipped.
OCR_PAGE_LIMIT = int(os.getenv("OCR_PAGE_LIMIT", "30"))

#: Rasterisation resolution handed to OCR. 200 DPI is the point where small
#: print stops losing strokes; 300 roughly doubles the time for little gain on
#: business documents.
OCR_DPI = int(os.getenv("OCR_DPI", "200"))

#: Recognition below this confidence is dropped. PaddleOCR emits low-confidence
#: guesses for smudges and logos, and a wrong line in the knowledge base is
#: worse than a missing one: the bot will answer from it with full confidence.
OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.60"))

#: A page whose text layer holds fewer characters than this is treated as not
#: really having one. Scanned pages often carry a stray header or a page number
#: in real text while the body is an image.
MIN_NATIVE_CHARS_PER_PAGE = int(os.getenv("OCR_MIN_NATIVE_CHARS", "80"))

#: PaddleOCR language model. "en" is most accurate for Latin script (English and
#: Malay both). "ch" also reads Latin and adds Chinese, which matters for
#: Malaysian shop and restaurant documents. Configurable because the right
#: answer depends on the tenant's documents, not on us.
OCR_LANG = os.getenv("PADDLEOCR_LANG", "en")

#: oneDNN acceleration is OFF by default because paddle 3.x raises
#: "ConvertPirAttribute2RuntimeAttribute not support" at inference time on some
#: CPUs, and it fails at predict() rather than at construction, so there is no
#: way to detect it while building the engine. Correct-everywhere beats fast-
#: sometimes for a fallback path. Set OCR_ENABLE_MKLDNN=1 on a host where it is
#: known good.
OCR_ENABLE_MKLDNN = os.getenv("OCR_ENABLE_MKLDNN", "").strip().lower() in ("1", "true", "yes")

_BULLET_RE = re.compile(r"^\s*[\u2022\u25cf\u25aa\u00b7\-\*\u2013\u2014]\s+")
_NUMBERED_RE = re.compile(r"^\s*(\d{1,2}[.)]|\([a-z0-9]\))\s+")

#: Cached engine. PaddleOCR loads detection and recognition models on
#: construction, which takes seconds, so it is built once per process.
_ocr_engine = None
_ocr_engine_failed = False


@dataclass(frozen=True)
class ExtractionResult:
    """What one PDF yielded, and how it was read.

    Immutable: callers pass this straight into the ingest report and the API
    response, and a mutable result invites a caller to "fix up" a field the
    pipeline is supposed to own.
    """

    markdown: str = ""
    page_count: int = 0
    ocr_page_count: int = 0
    character_count: int = 0
    headings: tuple = ()
    ocr_available: bool = False
    truncated: bool = False
    error: str = ""

    @property
    def ocr_used(self) -> bool:
        return self.ocr_page_count > 0

    @property
    def has_text(self) -> bool:
        return self.character_count > 0

    def summary(self) -> dict:
        """The 'list out content' payload: what we read, and how."""
        return {
            "page_count": self.page_count,
            "ocr_page_count": self.ocr_page_count,
            "character_count": self.character_count,
            "heading_count": len(self.headings),
            "headings": list(self.headings[:20]),
            "ocr_used": self.ocr_used,
            "ocr_available": self.ocr_available,
            "truncated": self.truncated,
            "error": self.error,
        }


def is_ocr_available() -> bool:
    """True when PaddleOCR can actually be constructed in this process."""
    return _get_ocr_engine() is not None


def _get_ocr_engine():
    """Build the PaddleOCR engine once, or return None if it cannot be built.

    Import is deliberately inside the function. paddle pulls in a large native
    runtime, and a deployment that never uploads a scanned PDF should not pay
    that import cost at boot, nor crash if the wheel is absent.
    """
    global _ocr_engine, _ocr_engine_failed

    if _ocr_engine is not None or _ocr_engine_failed:
        return _ocr_engine

    try:
        from paddleocr import PaddleOCR
    except Exception as import_error:
        _ocr_engine_failed = True
        logging.info(
            "PaddleOCR is not installed; scanned PDFs will not be read. (%s)",
            import_error,
        )
        return None

    # The constructor signature moved between PaddleOCR 2.x and 3.x: 2.x takes
    # use_angle_cls, 3.x renamed it use_textline_orientation and rejects the old
    # name. Try newest first and fall back rather than pinning a version the
    # host may not have.
    # Skip the model-source connectivity probe: it adds a network round trip to
    # every engine build and the models still download on first use.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

    attempts = (
        {"lang": OCR_LANG, "use_textline_orientation": True, "enable_mkldnn": OCR_ENABLE_MKLDNN},
        {"lang": OCR_LANG, "enable_mkldnn": OCR_ENABLE_MKLDNN},
        {"lang": OCR_LANG, "use_angle_cls": True, "show_log": False},
        {"lang": OCR_LANG, "use_angle_cls": True},
        {"lang": OCR_LANG},
    )

    for kwargs in attempts:
        try:
            _ocr_engine = PaddleOCR(**kwargs)
            logging.info("PaddleOCR ready (lang=%s, options=%s)", OCR_LANG, sorted(kwargs))
            return _ocr_engine
        except Exception:
            continue

    _ocr_engine_failed = True
    logging.error("PaddleOCR is installed but could not be initialised; using native text only.")
    return None


# ── Markdown shaping ──────────────────────────────────────────────────

def _clean(text: str) -> str:
    return " ".join(str(text or "").split())


def _as_markdown_line(text: str, size: float, body_size: float, bold: bool) -> str:
    """Turn one measured line into Markdown.

    Heading level comes from size relative to the document's own body text, not
    from absolute points: a deck and a contract disagree about what 14pt means,
    but both agree that the biggest text on the page is the title.
    """
    clean = _clean(text)
    if not clean:
        return ""

    if _BULLET_RE.match(text):
        return "- " + _BULLET_RE.sub("", text).strip()

    if _NUMBERED_RE.match(text):
        return "1. " + _NUMBERED_RE.sub("", text).strip()

    if body_size > 0:
        ratio = size / body_size
        # A long line is prose however large it is set; headings are short.
        # Without the length guard, a large-print document becomes all headings.
        if ratio >= 1.5 and len(clean) <= 120:
            return "# " + clean
        if ratio >= 1.25 and len(clean) <= 120:
            return "## " + clean
        if (ratio >= 1.1 or bold) and len(clean) <= 90:
            return "### " + clean

    return clean


def _join_blocks(lines: list) -> str:
    """Collapse runs of plain lines into paragraphs, keep structure standalone."""
    out = []
    paragraph = []

    def flush():
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    for line in lines:
        if not line:
            flush()
            continue
        if line.startswith("#") or line.startswith("- ") or line.startswith("1. "):
            flush()
            out.append(line)
        else:
            paragraph.append(line)

    flush()
    return "\n\n".join(out)


def _body_font_size(page) -> float:
    """The most common span size on the page, weighted by characters set in it."""
    weights = Counter()

    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = _clean(span.get("text"))
                if text:
                    weights[round(float(span.get("size") or 0), 1)] += len(text)

    return weights.most_common(1)[0][0] if weights else 0.0


def _native_page_markdown(page) -> str:
    """Read the page's real text layer and shape it as Markdown."""
    body_size = _body_font_size(page)
    lines = []

    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:          # 0 is text; 1 is an image
            continue

        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans)
            if not _clean(text):
                continue

            size = max((float(span.get("size") or 0) for span in spans), default=0.0)
            # PyMuPDF packs style into a bit field; bit 4 (16) is bold.
            bold = any(int(span.get("flags") or 0) & 16 for span in spans)
            lines.append(_as_markdown_line(text, size, body_size, bold))

        lines.append("")                     # block break becomes a paragraph break

    return _join_blocks(lines)


def _normalise_ocr_output(raw) -> list:
    """Flatten PaddleOCR 2.x and 3.x results into (text, score, height, top).

    2.x returns [[[box, (text, score)], ...]]; 3.x returns a list of dicts
    carrying rec_texts / rec_scores / rec_polys. Both shapes appear in the
    wild depending on the installed wheel, so both are handled here rather
    than pinning a version the host may not have.
    """
    items = []

    def box_metrics(box):
        try:
            ys = [float(point[1]) for point in box]
            return max(ys) - min(ys), min(ys)
        except Exception:
            return 0.0, 0.0

    for page in raw or []:
        if isinstance(page, dict):
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            polys = page.get("rec_polys") or page.get("dt_polys") or []
            for idx, text in enumerate(texts):
                score = float(scores[idx]) if idx < len(scores) else 1.0
                height, top = box_metrics(polys[idx]) if idx < len(polys) else (0.0, float(idx))
                items.append((text, score, height, top))
            continue

        for entry in page or []:
            try:
                box, (text, score) = entry[0], entry[1]
            except Exception:
                continue
            height, top = box_metrics(box)
            items.append((text, float(score), height, top))

    return items


def _ocr_page_markdown(page) -> str:
    """Rasterise one page and read it with PaddleOCR."""
    engine = _get_ocr_engine()
    if engine is None:
        return ""

    try:
        import numpy as np
    except Exception as e:
        logging.error("numpy is required to hand a page to PaddleOCR: %s", e)
        return ""

    try:
        pixmap = page.get_pixmap(dpi=OCR_DPI)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, pixmap.n
        )
        # PaddleOCR wants 3 channels. A pixmap can arrive as grayscale or RGBA.
        if pixmap.n == 1:
            image = np.repeat(image, 3, axis=2)
        elif pixmap.n == 4:
            image = image[:, :, :3]
    except Exception as e:
        logging.error("Could not rasterise a page for OCR: %s", e)
        return ""

    try:
        raw = engine.predict(image) if hasattr(engine, "predict") else engine.ocr(image)
    except Exception as e:
        logging.error("PaddleOCR failed on a page: %s", e)
        return ""

    items = [
        item for item in _normalise_ocr_output(raw)
        if _clean(item[0]) and item[1] >= OCR_MIN_CONFIDENCE
    ]
    if not items:
        return ""

    items.sort(key=lambda item: item[3])            # reading order, top to bottom

    heights = sorted(item[2] for item in items if item[2] > 0)
    # Median, not mean: one oversized title would drag a mean upward and leave
    # every real heading looking like body text.
    body_height = heights[len(heights) // 2] if heights else 0.0

    lines = [
        _as_markdown_line(text, height, body_height, bold=False)
        for text, _score, height, _top in items
    ]
    return _join_blocks(lines)


def extract_pdf_markdown(filepath: str) -> ExtractionResult:
    """Read a PDF to Markdown, using OCR only for pages that need it.

    Never raises for a document-level problem: the caller decides what a failed
    read means for the upload, and it needs the partial content and the reason
    to make that call.
    """
    try:
        import fitz
    except Exception as e:
        return ExtractionResult(error=f"PyMuPDF is unavailable: {e}")

    ocr_available = is_ocr_available()

    try:
        document = fitz.open(filepath)
    except Exception as e:
        return ExtractionResult(error=str(e), ocr_available=ocr_available)

    parts = []
    ocr_pages = 0
    truncated = False

    try:
        page_count = document.page_count

        for index, page in enumerate(document):
            try:
                native = _native_page_markdown(page)
            except Exception as e:
                logging.error("Native text extraction failed on page %s: %s", index + 1, e)
                native = ""

            # A page with a usable text layer is done. Anything thinner is
            # treated as a scan, because a scanned page often still carries a
            # header or a page number as real text.
            if len(_clean(native)) >= MIN_NATIVE_CHARS_PER_PAGE:
                parts.append(native)
                continue

            if not ocr_available:
                if native:
                    parts.append(native)
                continue

            if ocr_pages >= OCR_PAGE_LIMIT:
                truncated = True
                if native:
                    parts.append(native)
                continue

            recognised = _ocr_page_markdown(page)
            if recognised:
                ocr_pages += 1
                parts.append(recognised)
            elif native:
                parts.append(native)
    finally:
        try:
            document.close()
        except Exception:
            logging.debug("Closing the PDF after extraction failed; ignoring.")

    markdown = "\n\n".join(part for part in parts if part).strip()
    headings = tuple(
        line.lstrip("# ").strip()
        for line in markdown.splitlines()
        if line.startswith("#")
    )

    return ExtractionResult(
        markdown=markdown,
        page_count=page_count,
        ocr_page_count=ocr_pages,
        character_count=len(markdown),
        headings=headings,
        ocr_available=ocr_available,
        truncated=truncated,
    )
