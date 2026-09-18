"""Shared bounds and basic content checks for document uploads."""

import os

from werkzeug.exceptions import RequestEntityTooLarge


MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def validate_saved_pdf(path):
    """Reject oversized or disguised files before recording or parsing them.

    This signature check is not malware scanning. The existing PDF extractor
    still determines whether a document is readable.
    """
    size = os.path.getsize(path)
    if size > MAX_UPLOAD_BYTES:
        raise RequestEntityTooLarge()
    with open(path, "rb") as document:
        if not document.read(8).startswith(b"%PDF-"):
            raise ValueError("Invalid PDF content. Upload a PDF document.")
    return size
