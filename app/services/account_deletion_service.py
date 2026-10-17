"""Self-service workspace deletion: who may delete, the emailed code, and the deletion.

Only the workspace owner may delete, and only a workspace with no payment
history, no platform protection and no retained support records. Those rules
live in the database (data/080) so the page, this service and the delete
function can never disagree; this module asks the database and explains the
answer. Confirmation is a 6-digit code emailed to the owner: it is stored only
as an HMAC, expires after ten minutes, and dies after five wrong guesses.

Stored documents (R2 or local disk) are removed after the database deletion has
committed and never decide its outcome.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from werkzeug.utils import secure_filename

from app.database.account_deletion_repository import (
    claim_deletion_code_attempt,
    delete_company_account_rpc,
    delete_deletion_code,
    get_deletion_blocker,
    get_deletion_code,
    list_company_storage_files,
    upsert_deletion_code,
)
from app.database.company_repository import get_company_by_id
from app.services import document_storage_service as document_storage
from app.services.email_service import send_account_deletion_code_email
from app.services.knowledge_service import DATA_FOLDER
from app.services.pdf_relevance_validation_service import CANDIDATE_DATA_FOLDER
from app.storage_paths import MEDIA_FOLDER
from app.utils.jwt_utils import get_jwt_secret

logger = logging.getLogger(__name__)

CODE_DIGITS = 6
CODE_TTL = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 5

_CODE_FORMAT = re.compile(r"[0-9]{%d}" % CODE_DIGITS)  # ASCII digits only: \d also matches other scripts

# code -> (what the person is told, HTTP status). The database's own wording is never shown.
_SUPPORT = "Please contact support from the Support page."
_REFUSALS = {
    "not_owner": ("Only the workspace owner can delete this workspace.", 403),
    "payment_history": ("This workspace has payment history that we have to keep, so it cannot be deleted here. " + _SUPPORT, 409),
    "protected": ("This workspace is protected and cannot be deleted here. " + _SUPPORT, 409),
    "support_records": ("This workspace has support records that we have to keep, so it cannot be deleted here. " + _SUPPORT, 409),
    "not_found": ("Workspace not found.", 404),
}
_MESSAGES = {
    **_REFUSALS,
    "code_invalid": ("That code is not correct.", 400),
    "code_expired": ("This code has expired or was never requested. Request a new one.", 400),
    "too_many_attempts": ("Too many incorrect codes. Request a new code to try again.", 429),
    "email_unavailable": ("We could not send the confirmation email. Please try again in a moment.", 503),
    "deletion_failed": ("We could not delete the workspace. Nothing was changed. Please try again or contact support.", 500),
}
_UNKNOWN_REFUSAL = ("This workspace cannot be deleted here. " + _SUPPORT, 409)


class AccountDeletionError(Exception):
    """A refusal with a stable machine code the Profile page can explain."""

    def __init__(self, code):
        self.message, self.status_code = _MESSAGES.get(code, _UNKNOWN_REFUSAL)
        super().__init__(self.message)
        self.code = code

    @property
    def is_refusal(self):
        """True when the workspace itself is the reason, as opposed to the code or the mail."""
        return self.code in _REFUSALS or self.code not in _MESSAGES


def _now():
    return datetime.now(timezone.utc)


def hash_code(user_id, code):
    """HMAC-SHA256 of the code under the server secret, bound to one user and this purpose.

    A 6-digit code has a million values, so a bare hash of a leaked row could be
    reversed instantly; without the secret this cannot.
    """
    message = f"account-deletion-code:v1:{int(user_id)}:{code}".encode("utf-8")
    return hmac.new(get_jwt_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()


def _require_eligible(user):
    reason = get_deletion_blocker(user["company_id"], user["id"])
    if reason:
        raise AccountDeletionError(reason)


def get_deletion_status(user):
    """What the Profile page needs to choose between its four states."""
    reason = get_deletion_blocker(user["company_id"], user["id"])
    if reason == "not_found":
        raise AccountDeletionError("not_found")
    company = get_company_by_id(user["company_id"]) or {}
    return {
        "eligible": reason is None,
        "reason_code": reason,
        "is_owner": reason != "not_owner",
        "company_name": company.get("company_name") or "",
    }


def request_deletion_code(user):
    """Issue a fresh code (replacing any earlier one) and email it to the owner."""
    _require_eligible(user)
    code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
    upsert_deletion_code(user["id"], hash_code(user["id"], code), (_now() + CODE_TTL).isoformat())

    company = get_company_by_id(user["company_id"]) or {}
    sent = send_account_deletion_code_email(
        user.get("email"),
        code,
        recipient_name=user.get("full_name") or "there",
        company_name=company.get("company_name"),
    )
    if not sent:
        # A code the owner never received must not stay guessable.
        delete_deletion_code(user["id"])
        raise AccountDeletionError("email_unavailable")
    return {"expires_in_minutes": int(CODE_TTL.total_seconds() // 60)}


def _is_expired(row):
    try:
        expires_at = datetime.fromisoformat(str(row.get("expires_at")))
    except ValueError:
        return True  # an unreadable expiry is treated as expired
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return _now() >= expires_at


def _check_code(user, code):
    """Raise unless `code` is the live code for this user; count and cap wrong guesses."""
    row = get_deletion_code(user["id"])
    if not row:
        raise AccountDeletionError("code_expired")
    if _is_expired(row):
        delete_deletion_code(user["id"])
        raise AccountDeletionError("code_expired")

    attempts = int(row.get("attempts") or 0)
    if attempts >= MAX_CODE_ATTEMPTS:
        _lock_out(user)
    stored_hash = str(row.get("code_hash") or "")

    # Spend the guess before comparing. The claim is a compare-and-swap, so of several concurrent
    # guesses that read the same count only one is compared: the cap holds without the rate limit.
    if not claim_deletion_code_attempt(user["id"], stored_hash, attempts):
        raise AccountDeletionError("code_invalid")
    if hmac.compare_digest(stored_hash, hash_code(user["id"], code)):
        return
    if attempts + 1 >= MAX_CODE_ATTEMPTS:
        _lock_out(user)
    raise AccountDeletionError("code_invalid")


def _lock_out(user):
    delete_deletion_code(user["id"])
    logger.warning("Workspace deletion code locked out after %d wrong guesses (company %s, user %s)",
                   MAX_CODE_ATTEMPTS, user["company_id"], user["id"])
    raise AccountDeletionError("too_many_attempts")


def _check_verdict(result):
    """Turn the database's answer into success or a coded error."""
    if isinstance(result, dict) and result.get("status") == "success":
        return
    code = result.get("code") if isinstance(result, dict) else None
    if code in _REFUSALS:
        raise AccountDeletionError(code)
    logger.error("Workspace deletion returned an unrecognised verdict (%s)", code)
    raise AccountDeletionError("deletion_failed")


def confirm_deletion(user, code):
    """Delete the workspace if `code` is right. Irreversible; the database re-checks every guard."""
    if not isinstance(code, str) or not _CODE_FORMAT.fullmatch(code):
        raise AccountDeletionError("code_invalid")
    _require_eligible(user)  # an ineligible user must not be able to probe codes
    _check_code(user, code)

    # The rows that name the files disappear with the workspace, so list them first.
    files = _list_storage_files(user["company_id"])
    result = delete_company_account_rpc(user["company_id"], user["id"])
    _check_verdict(result)
    # The only record left of an irreversible action: ids and counts, never names or emails.
    # The chatbot ids let ops sweep bot_<id>_* storage objects if the cleanup below is cut short.
    logger.info("Workspace %s permanently deleted by user %s (counts %s, chatbot ids %s)",
                user["company_id"], user["id"], result.get("deleted_counts"), result.get("chatbot_ids"))

    _start_background(lambda: _delete_stored_files(files, user["company_id"]))
    return {"status": "success", "deleted_counts": result.get("deleted_counts") or {}}


# ------------------------------------------------------------------- stored files

def _list_storage_files(company_id):
    try:
        return list_company_storage_files(company_id)
    except Exception as exc:
        logger.warning("Workspace storage listing failed (%s); stored documents will not be cleaned up",
                       type(exc).__name__)
        return {"knowledge": [], "media": []}


def _media_name(url):
    """The file name inside a /media/<name> URL, or None for anything else."""
    path = urlparse(url).path if isinstance(url, str) else ""
    name = path[len("/media/"):] if path.startswith("/media/") else ""
    return name if name and secure_filename(name) == name else None


def _storage_targets(files):
    """(root, namespace, name) for every stored object that belongs to this workspace.

    Both kinds of file are written as bot_<chatbot_id>_<uuid>_<name>, and a row's
    chatbot is already known to be this workspace's. A name that does not start
    with that prefix is ignored, so a tenant-supplied media_url (or a corrupted
    row) can never aim the deletion at another tenant's file.
    """
    targets = {}

    def add(root, namespace, chatbot_id, name):
        if name and name.startswith(f"bot_{chatbot_id}_"):
            targets[(root, namespace, name)] = None

    for row in files.get("knowledge") or []:
        chatbot_id, file_id = row.get("chatbot_id"), row.get("id")
        if not isinstance(chatbot_id, int):
            continue
        for name in (
            os.path.basename(row.get("file_path") or ""),
            secure_filename(row.get("file_name") or ""),
            f"bot_{chatbot_id}_{file_id}_readme.md",
            f"bot_{chatbot_id}_{file_id}_history.json",
            f"bot_{chatbot_id}_readme.md",
        ):
            add(DATA_FOLDER, "knowledge", chatbot_id, name)
    for row in files.get("media") or []:
        if isinstance(row.get("chatbot_id"), int):
            add(MEDIA_FOLDER, "media", row["chatbot_id"], _media_name(row.get("media_url")))
    return list(targets)


def _company_folders(company_id):
    """(directory, root, namespace) of the folders that only ever hold this workspace's files.

    Reports and bookings CSVs live under <reports root>/<company_id>/ and PDF candidates under
    _pdf_candidates/<company_id>/. company_id is the signed-in user's integer id, never input.
    """
    reports_root = Path(os.getenv("REPORT_STORAGE_ROOT", str(Path(__file__).resolve().parents[2] / "data" / "reports")))
    return [
        (reports_root / str(int(company_id)), reports_root, "reports"),
        (Path(CANDIDATE_DATA_FOLDER) / str(int(company_id)), Path(DATA_FOLDER), "knowledge"),
    ]


def _delete_stored_files(files, company_id):
    """Best effort: the workspace is already gone, so a failure is logged, never raised."""
    try:
        targets = _storage_targets(files)
        failed = 0
        for root, namespace, name in targets:
            try:
                document_storage.delete_file(os.path.join(root, name), root=root, namespace=namespace)
            except Exception:
                failed += 1
        if failed:
            logger.warning("Workspace storage cleanup: %d of %d stored documents could not be deleted",
                           failed, len(targets))
    except Exception as exc:
        logger.warning("Workspace storage cleanup failed (%s)", type(exc).__name__)

    for directory, root, namespace in _company_folders(company_id):
        try:
            document_storage.delete_tree(directory, root=root, namespace=namespace)
        except Exception as exc:
            logger.warning("Workspace %s %s folder cleanup failed (%s)",
                           company_id, namespace, type(exc).__name__)


def _start_background(target):
    # shortcut: sequential deletes on a daemon thread, no retry or queue; a worker restart
    # mid-cleanup leaves orphaned objects. Upgrade to a queued job if tenants hold many documents.
    threading.Thread(target=target, name="account-deletion-storage", daemon=True).start()
