import os
import logging
import uuid
from werkzeug.utils import secure_filename

from app.services.settings_service import update_chatbot_runtime
from app.database.knowledge_file_repository import save_knowledge_file
from app.database.knowledge_file_repository import update_knowledge_file_status
from app.database.knowledge_file_repository import delete_knowledge_file_by_id
from app.database.knowledge_file_repository import get_knowledge_file_by_name_or_id
from app.database.knowledge_file_repository import set_active_pdf_knowledge_file
from app.database.knowledge_file_repository import get_knowledge_files
from app.database.knowledge_file_repository import get_active_knowledge_file
from app.database.knowledge_file_repository import update_supporting_knowledge_enabled
from app.database.knowledge_chunk_repository import delete_chunks_by_file_for_chatbot
from app.services.billing_guard import can_upload_knowledge_storage, BillingLimitError
from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot

DATA_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data")
)


from app.services.document_ocr_service import OCR_PAGE_LIMIT


def save_uploaded_pdf(file, chatbot_id, target_role="primary", source_pdf_candidate_id=None):
    if not file:
        raise ValueError("No file provided")

    if file.filename == "":
        raise ValueError("No selected file")

    if not file.filename.lower().endswith(".pdf"):
        raise ValueError("Invalid file type")

    if target_role not in ("primary", "supporting"):
        raise ValueError("target_role must be 'primary' or 'supporting'")

    os.makedirs(DATA_FOLDER, exist_ok=True)

    original_name = secure_filename(file.filename) or "uploaded.pdf"
    safe_name = f"bot_{chatbot_id}_{uuid.uuid4().hex}_{original_name}"

    filepath = os.path.join(DATA_FOLDER, safe_name)
    file.save(filepath)

    relative_pdf_path = os.path.join("data", safe_name)
    file_size = os.path.getsize(filepath)

    file_record = save_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=safe_name,
        file_type="pdf",
        file_size=file_size,
        file_path=relative_pdf_path,
        upload_status="uploaded",
        # Deliberately not "completed": nothing has been parsed yet. Claiming
        # completion up front is what let an image-only or corrupt PDF report
        # "Ready" while holding zero searchable chunks.
        processing_status="processing",
        match_status="unchecked",
        is_enabled=True,
        is_active=False if target_role == "supporting" else None,
        source_pdf_candidate_id=source_pdf_candidate_id,
        original_file_name=original_name,
    )

    file_id = file_record["id"]

    chunk_count, extraction_error, extraction = _index_pdf_chunks(filepath, chatbot_id, file_id)

    if not chunk_count:
        # A document with no chunks can answer nothing. Promoting it would
        # demote a primary source that still works, so the upload is recorded
        # as failed and the existing primary is left exactly as it was.
        try:
            update_knowledge_file_status(file_id, processing_status="failed")
        except Exception as status_err:
            logging.error(
                "Failed to record failed processing status for chatbot_id=%s, file_id=%s: %s",
                chatbot_id,
                file_id,
                status_err,
            )

        logging.error(
            "No knowledge chunks were extracted for chatbot_id=%s, file_id=%s: %s",
            chatbot_id,
            file_id,
            extraction_error or "the document produced no readable text",
        )

        try:
            log_knowledge_modification(
                chatbot_id,
                file_id,
                "Document uploaded but no readable text was extracted. Primary knowledge unchanged.",
            )
        except Exception as log_err:
            logging.error(f"Failed to log history for failed PDF upload: {log_err}")

        role_label = "primary knowledge" if target_role == "primary" else "supporting knowledge"
        if extraction.ocr_used:
            reason = (
                "We scanned this PDF as images and still could not read any text from it, "
                f"so it was not set as {role_label}. Your current primary source is "
                "unchanged. Check that the pages are the right way up and in focus."
            )
        elif not extraction.ocr_available:
            reason = (
                "This PDF has no readable text layer and image scanning is not switched on "
                f"for this server, so it was not set as {role_label}. Your current "
                "primary source is unchanged. Upload a text-based PDF instead."
            )
        else:
            reason = (
                "No readable text could be extracted from this PDF, so it was not set as "
                f"{role_label}. Your current primary source is unchanged. Upload a "
                "text-based PDF, or review this source before using it."
            )

        return {
            "status": "failed",
            "processing_status": "failed",
            "chunk_count": 0,
            "file_id": file_id,
            "file_name": safe_name,
            "original_file_name": original_name,
            "file_path": filepath,
            "extraction": extraction.summary(),
            "message": reason,
        }

    try:
        update_knowledge_file_status(file_id, processing_status="completed")
    except Exception as status_err:
        logging.error(
            "Failed to record completed processing status for chatbot_id=%s, file_id=%s: %s",
            chatbot_id,
            file_id,
            status_err,
        )

    if target_role == "primary":
        set_active_pdf_knowledge_file(
            chatbot_id=chatbot_id,
            file_id=file_id
        )

    try:
        generate_and_save_knowledge_readme(chatbot_id, file_id)
    except Exception as readme_err:
        logging.error(f"Failed to generate README for PDF: {readme_err}")
    try:
        if target_role == "primary":
            history_message = "Document uploaded and chunks indexed."
        else:
            history_message = "Supporting document uploaded and chunks indexed."
        log_knowledge_modification(chatbot_id, file_id, history_message)
    except Exception as log_err:
        logging.error(f"Failed to log history for PDF upload: {log_err}")

    if target_role == "primary":
        update_chatbot_runtime({
            "draft_pdf_file_name": safe_name,
            "draft_pdf_path": relative_pdf_path,
            "last_match_result": None,
            "last_match_reason": "",
        }, chatbot_id)

    # Queue a tenant-scoped review event after a successful document ingest.
    # Automation is advisory and must never turn a successful upload into a
    # failed request when its optional table has not been migrated yet.
    try:
        from app.database.bot_repository import get_bot_by_id
        from app.services.automation_service import schedule_knowledge_document_follow_up

        bot = get_bot_by_id(chatbot_id) or {}
        company_id = bot.get("company_id")
        if company_id:
            schedule_knowledge_document_follow_up(
                company_id=company_id,
                chatbot_id=chatbot_id,
                file_id=file_id,
                display_name=original_name,
                chunk_count=chunk_count,
                target_role=target_role,
            )
    except Exception as automation_err:
        logging.warning(
            "Knowledge follow-up automation unavailable for chatbot_id=%s, file_id=%s: %s",
            chatbot_id,
            file_id,
            automation_err,
        )

    # "List out content": what we actually read, and how. The operator needs to
    # know a scan was involved, because OCR text is good but not perfect and it
    # is worth a glance before the bot starts answering from it.
    if extraction.ocr_used:
        message = (
            f"PDF uploaded and set as {target_role} knowledge. "
            f"{extraction.ocr_page_count} of {extraction.page_count} page(s) were scanned as "
            f"images, so please check the wording before relying on it."
        )
    else:
        if target_role == "primary":
            message = "PDF uploaded and set as primary knowledge."
        else:
            message = "PDF uploaded as supporting knowledge."

    if extraction.truncated:
        message += (
            f" Only the first {OCR_PAGE_LIMIT} scanned page(s) were read; "
            f"split the document if the rest matters."
        )

    return {
        "status": "completed",
        "processing_status": "completed",
        "chunk_count": chunk_count,
        "file_id": file_id,
        "file_name": safe_name,
        "original_file_name": original_name,
        "file_path": filepath,
        "extraction": extraction.summary(),
        "message": message,
    }


def _index_pdf_chunks(filepath: str, chatbot_id: int, file_id: int):
    """Parse a PDF and store one embedded knowledge chunk per section.

    Returns ``(saved_chunk_count, error_message, extraction)``. The count is of
    chunks that actually reached the database, because that is what retrieval
    can search later: a chunk whose embedding call returned nothing is invisible
    to the bot and must not count towards a successful ingest. An empty error
    message means parsing ran to the end.

    Reading the document is delegated to ``document_ocr_service``, which takes
    the text layer when there is one and falls back to PaddleOCR per page when
    there is not. That is what lets a scanned menu or a photographed price list
    become knowledge instead of a zero-chunk failure.
    """
    from app.services.document_ocr_service import extract_pdf_markdown

    saved_chunks = 0
    extraction = extract_pdf_markdown(filepath)

    if extraction.error:
        return saved_chunks, extraction.error, extraction

    try:
        from app.services.rag_service import split_text_into_sections, generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk

        logging.info(
            "Read %s characters from %s page(s) for file_id=%s (%s OCR page(s), truncated=%s)",
            extraction.character_count,
            extraction.page_count,
            file_id,
            extraction.ocr_page_count,
            extraction.truncated,
        )

        chunks = split_text_into_sections(extraction.markdown)

        logging.info(f"Processing {len(chunks)} chunks for database insertion...")

        for idx, chunk in enumerate(chunks):
            embedding = generate_embedding(chunk)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk,
                    embedding=embedding,
                    metadata={"chunk_index": idx}
                )
                saved_chunks += 1
        logging.info(f"Successfully saved {saved_chunks} chunks to Supabase.")

        try:
            extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
        except Exception as graph_err:
            logging.error(f"Failed to generate and store knowledge graph for PDF: {graph_err}")
    except Exception as e:
        logging.error(f"Failed to process PDF chunks: {e}")
        return saved_chunks, str(e), extraction

    return saved_chunks, "", extraction


def resolve_knowledge_role(knowledge_file: dict) -> str:
    """Name the retrieval role of one ``knowledge_files`` row.

    The frontend used to guess this from ``is_active`` plus ``file_type``,
    which labelled every non-primary document "Inactive" even when it was
    enabled. The rule lives here now so the API and retrieval agree.
    """
    if knowledge_file.get("is_active"):
        return "primary"

    return "supporting" if knowledge_file.get("is_enabled", True) is not False else "inactive"


def list_uploaded_pdfs(chatbot_id):
    files = get_knowledge_files(chatbot_id=chatbot_id)

    return [
        {
            "id": file["id"],
            "file_name": file["file_name"],
            "name": file["file_name"],  # keep both for safety
            "original_file_name": file.get("original_file_name"),
            "display_name": file.get("original_file_name") or file["file_name"],
            "size": file.get("file_size"),
            "file_type": file.get("file_type") or "pdf",
            "is_enabled": file.get("is_enabled", True) is not False,
            "is_active": bool(file.get("is_active")),
            "status": "active" if file.get("is_active") else "available",
            # Exposed so the UI can tell a genuinely broken ingest apart from a
            # source the operator simply switched off.
            "processing_status": file.get("processing_status") or "",
            "role": resolve_knowledge_role(file),
        }
        for file in files
    ]


def get_active_pdf(chatbot_id):
    active = get_active_knowledge_file(chatbot_id=chatbot_id)

    if not active:
        return {
            "id": None,
            "file_name": "",
            "name": "",
            "original_file_name": None,
            "display_name": "",
            "file_path": ""
        }

    file_name = active.get("file_name", "")
    original_file_name = active.get("original_file_name")

    return {
        "id": active.get("id"),
        "file_name": file_name,
        "name": file_name,
        "original_file_name": original_file_name,
        "display_name": original_file_name or file_name,
        "file_path": active.get("file_path", ""),
        "file_type": active.get("file_type") or "pdf",
        "is_enabled": active.get("is_enabled", True) is not False,
        "is_active": bool(active.get("is_active")),
        "role": resolve_knowledge_role(active),
    }


def set_active_pdf(file_name, chatbot_id):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    knowledge_file = (
        get_knowledge_file_by_name_or_id(chatbot_id, file_name)
        or get_knowledge_file_by_name_or_id(chatbot_id, safe_name)
    )

    if not knowledge_file:
        raise ValueError("Knowledge file not found")

    file_id = knowledge_file.get("id")
    selected_name = knowledge_file.get("file_name") or file_name
    selected_path = knowledge_file.get("file_path") or ""
    file_type = (knowledge_file.get("file_type") or "").lower()

    if file_type == "url":
        raise ValueError("Website sources are supporting knowledge and cannot be set as the active PDF.")

    if file_type and file_type != "pdf":
        raise ValueError("Only PDF knowledge sources can be set as the active PDF.")

    chunks = get_chunks_by_file_for_chatbot(chatbot_id, file_id) if file_id else []

    if not chunks:
        logging.warning(
            "Setting active knowledge file with no chunks for chatbot_id=%s, file_id=%s",
            chatbot_id,
            file_id,
        )

    target_path = selected_path
    if not target_path or not os.path.isabs(target_path):
        target_path = os.path.join(DATA_FOLDER, secure_filename(selected_name))

    if not os.path.exists(target_path):
        logging.warning(
            "Local knowledge file missing while setting active: chatbot_id=%s, file_id=%s",
            chatbot_id,
            file_id,
        )

    set_active_pdf_knowledge_file(
        chatbot_id=chatbot_id,
        file_id=file_id
    )

    try:
        generate_and_save_knowledge_readme(chatbot_id, file_id)
    except Exception as readme_err:
        logging.error(f"Failed to generate README when setting active PDF: {readme_err}")
    try:
        log_knowledge_modification(chatbot_id, file_id, "Document set as the active primary knowledge source.")
    except Exception as log_err:
        logging.error(f"Failed to log history when setting active PDF: {log_err}")

    relative_pdf_path = selected_path or os.path.join("data", secure_filename(selected_name))

    update_chatbot_runtime({
        "draft_pdf_file_name": selected_name,
        "draft_pdf_path": relative_pdf_path,
        "last_match_result": None,
        "last_match_reason": "",
    }, chatbot_id)

    return {
        "file_name": selected_name,
        "file_path": relative_pdf_path,
        "message": f"Active primary knowledge set to {selected_name}"
    }


def toggle_supporting_knowledge(file_name, is_enabled, chatbot_id):
    if not file_name:
        raise ValueError("file_name is required")

    if not isinstance(is_enabled, bool):
        raise ValueError("is_enabled must be true or false")

    safe_name = secure_filename(file_name)
    knowledge_file = (
        get_knowledge_file_by_name_or_id(chatbot_id, file_name)
        or get_knowledge_file_by_name_or_id(chatbot_id, safe_name)
    )

    if not knowledge_file:
        raise ValueError("Knowledge source not found")

    # Documents are supporting sources too, so there is no file_type gate here.
    # The primary is the one exception: retrieval loads it on its own path and
    # never consults is_enabled, so accepting the toggle for it would report a
    # change the bot does not honour.
    if knowledge_file.get("is_active"):
        raise ValueError(
            "The primary source is always in use. Set another source as primary first."
        )

    updated = update_supporting_knowledge_enabled(
        chatbot_id=chatbot_id,
        file_id=knowledge_file.get("id"),
        is_enabled=is_enabled,
    )

    if not updated:
        raise ValueError("Supporting knowledge source was not updated.")

    return {
        "file_name": updated.get("file_name") or file_name,
        "is_enabled": updated.get("is_enabled", is_enabled) is not False,
        "role": resolve_knowledge_role(updated),
        "message": "Supporting source enabled." if is_enabled else "Supporting source disabled."
    }


def delete_pdf_file(file_name, chatbot_id):
    if not file_name:
        raise ValueError("File name is required")

    safe_name = secure_filename(file_name)
    knowledge_file = (
        get_knowledge_file_by_name_or_id(chatbot_id, file_name)
        or get_knowledge_file_by_name_or_id(chatbot_id, safe_name)
    )

    if not knowledge_file:
        raise ValueError("Knowledge file not found")

    file_id = knowledge_file.get("id")
    stored_name = knowledge_file.get("file_name") or file_name
    stored_path = knowledge_file.get("file_path") or ""
    active = get_active_knowledge_file(chatbot_id=chatbot_id)
    is_active_file = active and active.get("id") == file_id

    if not file_id:
        raise ValueError("Knowledge file id is missing")

    delete_chunks_by_file_for_chatbot(chatbot_id, file_id)
    try:
        from app.database.knowledge_graph_repository import delete_graph_by_file_id
        delete_graph_by_file_id(chatbot_id, file_id)
    except Exception as e:
        logging.error(f"Failed to delete graph data for file_id {file_id}: {e}")
    delete_knowledge_file_by_id(chatbot_id, file_id)

    target_paths = []
    if stored_path and not stored_path.startswith("http://") and not stored_path.startswith("https://"):
        target_paths.append(stored_path)
    target_paths.append(os.path.join(DATA_FOLDER, secure_filename(stored_name)))

    for target_path in dict.fromkeys(target_paths):
        if not target_path:
            continue

        if not os.path.isabs(target_path):
            target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", target_path))

        try:
            if os.path.exists(target_path):
                os.remove(target_path)
            else:
                logging.info(
                    "Local knowledge file already missing for chatbot_id=%s, file_id=%s",
                    chatbot_id,
                    file_id,
                )
        except Exception as e:
            logging.error(
                "Failed to remove local knowledge file for chatbot_id=%s, file_id=%s: %s",
                chatbot_id,
                file_id,
                e,
            )

    if is_active_file:
        update_chatbot_runtime({
            "draft_pdf_file_name": "",
            "draft_pdf_path": "",
            "deployed_pdf_file_name": "",
            "deployed_pdf_path": "",
            "last_match_result": None,
            "last_match_reason": "",
        }, chatbot_id)

    return {
        "file_name": stored_name,
        "message": f"Resource {stored_name} deleted successfully"
    }


from html.parser import HTMLParser
import re

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.ignore = False
        self.ignore_tags = {'script', 'style', 'header', 'footer', 'nav', 'noscript', 'head', 'iframe'}

    def handle_starttag(self, tag, attrs):
        if tag in self.ignore_tags:
            self.ignore = True

    def handle_endtag(self, tag):
        if tag in self.ignore_tags:
            self.ignore = False

    def handle_data(self, data):
        if not self.ignore:
            clean = data.strip()
            if clean:
                self.result.append(clean)

    def get_text(self):
        return "\n".join(self.result)


def fetch_and_parse_url(url):
    if not url:
        raise ValueError("URL is required")

    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("Invalid URL protocol. URL must start with http:// or https://")

    text_content = ""
    used_fallback = False

    # 1. Try Jina Reader API first (supports dynamic websites, returns clean markdown/text)
    try:
        import requests
        import logging
        reader_url = f"https://r.jina.ai/{url}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        logging.info(f"Attempting to scrape via Jina Reader: {reader_url}")
        response = requests.get(reader_url, headers=headers, timeout=25)
        response.raise_for_status()

        scraped_text = response.text.strip()
        if scraped_text and len(scraped_text) >= 50:
            text_content = scraped_text
            logging.info("Successfully scraped and parsed content using Jina Reader.")
        else:
            logging.warning("Jina Reader returned empty or too short content. Falling back to static scraping.")
            used_fallback = True
    except Exception as e:
        import logging
        logging.warning(f"Jina Reader scraping failed: {str(e)}. Falling back to static scraping.")
        used_fallback = True

    # 2. Fallback to static requests + HTMLTextExtractor if Jina failed
    if used_fallback or not text_content:
        try:
            import requests
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            html_content = response.text

            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            text_content = extractor.get_text()
        except Exception as fallback_err:
            raise ValueError(f"Failed to fetch and parse URL: {str(fallback_err)}")

    # Remove excessive blank lines
    text_content = re.sub(r'\n{3,}', '\n\n', text_content).strip()

    if not text_content or len(text_content) < 50:
        raise ValueError("The webpage does not contain enough extractable text.")

    return text_content


def scrape_pages(urls) -> tuple[list[dict], list[dict]]:
    """Fetch and parse each URL, tolerating per-page failures.

    Shared by the /api/knowledge/scrape-extract route and the unified
    ingestion service so the fetch-and-collect loop exists in one place.

    Returns:
        (pages, failures) where pages is a list of
        ``{"url": str, "content": str}`` for every page that parsed, and
        failures is a list of ``{"url": str, "error": str}`` for the pages
        that did not. A page that fails never aborts the pages around it.
    """
    pages: list[dict] = []
    failures: list[dict] = []

    for url in urls:
        try:
            pages.append({"url": url, "content": fetch_and_parse_url(url)})
        except Exception as e:
            logging.error(f"Failed to scrape URL {url}: {e}")
            failures.append({"url": url, "error": str(e)})

    return pages, failures


def scrape_website_url(url, chatbot_id, company_id=None):
    text_content = fetch_and_parse_url(url)

    # Save to knowledge_files table
    file_size = len(text_content.encode('utf-8'))

    # Check storage limit before saving
    if company_id:
        can_upload_knowledge_storage(company_id, file_size)

    file_record = save_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=url,
        file_type="url",
        file_size=file_size,
        file_path=url,
        upload_status="uploaded",
        processing_status="completed",
        match_status="unchecked"
    )

    file_id = file_record["id"]

    # --- PROCESS AND CHUNK TEXT ---
    try:
        import logging
        from app.services.rag_service import split_text_into_sections, generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk

        chunks = split_text_into_sections(text_content)

        logging.info(f"Processing {len(chunks)} chunks for database insertion...")

        for idx, chunk in enumerate(chunks):
            embedding = generate_embedding(chunk)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk,
                    embedding=embedding,
                    metadata={"chunk_index": idx}
                )
        logging.info("Successfully saved web chunks to Supabase.")

        try:
            extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
        except Exception as graph_err:
            logging.error(f"Failed to generate and store knowledge graph for URL: {graph_err}")
    except Exception as e:
        import logging
        logging.error(f"Failed to process web chunks: {e}")

    return {
        "file_name": url,
        "message": "Website saved as supporting knowledge."
    }


from urllib.parse import urlparse, urljoin

def discover_website_links(url):
    if not url:
        raise ValueError("URL is required")

    # Fetch raw HTML directly for link discovery to ensure navigation links (headers, menus, footers) are not stripped by Jina
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        import logging
        logging.warning(f"Static request for link discovery failed: {e}. Falling back to fetch_and_parse_url.")
        html_content = fetch_and_parse_url(url)

    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc

    links = set()
    cleaned_base_url = url.split('?')[0].split('#')[0].rstrip('/')
    links.add(cleaned_base_url)

    # Extract raw HTML links in case of raw HTML content
    html_links = re.findall(r'href=["\'](https?://[^\s"\']+|/[^\s"\']*)["\']', html_content)
    # Extract Markdown links [text](url) in case fallback fetch_and_parse_url was used and returned markdown
    md_links = re.findall(r'\[.*?\]\(((?:https?://[^\s\)]+|/[^\s\)]+))\)', html_content)

    all_extracted = html_links + md_links

    for link in all_extracted:
        full_link = urljoin(url, link)
        # Clean query parameters and hash anchors
        full_link = full_link.split('?')[0].split('#')[0].rstrip('/')

        parsed_link = urlparse(full_link)
        if parsed_link.netloc == base_domain:
            # Exclude obvious asset files
            if not any(full_link.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.pdf', '.css', '.js', '.zip', '.tar']):
                links.add(full_link)

    # Return sorted list, capping at 20 pages
    return sorted(list(links))[:20]


def scrape_website_urls_batch(urls, chatbot_id, company_id=None):
    if not urls:
        raise ValueError("At least one URL must be selected.")

    combined_content_list = []
    failed_urls = []
    primary_url = urls[0]

    for url in urls:
        try:
            content = fetch_and_parse_url(url)
            combined_content_list.append(f"Source URL: {url}\n====================\n\n{content}")
        except Exception as e:
            import logging
            logging.error(f"Failed to scrape URL {url} in batch: {e}")
            failed_urls.append(url)

    if not combined_content_list:
        raise ValueError(f"Failed to scrape any of the selected URLs. Errors: {failed_urls}")

    combined_text = "\n\n\n\n".join(combined_content_list)

    file_name = primary_url
    if len(urls) > 1:
        file_name = f"{primary_url} (+{len(urls) - 1} pages)"

    file_size = len(combined_text.encode('utf-8'))

    # Check storage limit before saving
    if company_id:
        can_upload_knowledge_storage(company_id, file_size)

    file_record = save_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=file_name,
        file_type="url",
        file_size=file_size,
        file_path=primary_url,
        upload_status="uploaded",
        processing_status="completed",
        match_status="unchecked"
    )

    file_id = file_record["id"]

    try:
        import logging
        from app.services.rag_service import split_text_into_sections, generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk

        chunks = split_text_into_sections(combined_text)

        logging.info(f"Processing {len(chunks)} chunks for database insertion...")

        for idx, chunk in enumerate(chunks):
            embedding = generate_embedding(chunk)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk,
                    embedding=embedding,
                    metadata={"chunk_index": idx}
                )
        logging.info("Successfully saved batch web chunks to Supabase.")

        try:
            extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
        except Exception as graph_err:
            logging.error(f"Failed to generate and store knowledge graph for batch URL: {graph_err}")
    except Exception as e:
        import logging
        logging.error(f"Failed to process batch web chunks: {e}")

    msg = "Website saved as supporting knowledge."
    if failed_urls:
        msg += f" Note: Failed to scrape {len(failed_urls)} pages: {', '.join(failed_urls)}"

    return {
        "file_name": file_name,
        "message": msg
    }


def extract_business_knowledge(raw_text, chatbot_id):
    """Extract key business info from raw scraped text using AI.

    chatbot_id is required and must be a valid chatbot identifier.
    Routes through ai_router.generate_system_response() for billing enforcement.
    Raises ValueError if chatbot_id is missing.
    """
    if not raw_text:
        return ""
    if not chatbot_id:
        raise ValueError("chatbot_id is required for AI knowledge extraction.")
    try:
        from app.services.ai_router import (
            OPERATION_WEBSITE_KNOWLEDGE_EXTRACTION,
            generate_system_response,
        )
        prompt = (
            "You are an expert Business Analyst. Extract only the key business information, "
            "services, packages, pricing, business hours, locations, policies, and FAQs from the "
            "following raw scraped web text.\n\n"
            "Rules:\n"
            "1. Ignore cookie warnings, header menus, footer links, privacy policies, advertisements, and layout formatting.\n"
            "2. Present the extracted information in clean, highly structured sections (e.g., SERVICES, PRICING, BUSINESS HOURS, FAQs).\n"
            "3. Keep the factual details (like price numbers, contact info, names) 100% exact as in the source.\n"
            "4. Respond with the clean facts only. Do not use Markdown heading tags (# or ##) to make the text clean for mobile messaging. Use bold capital letters instead.\n\n"
            f"Source Text:\n{raw_text}"
        )
        return generate_system_response(
            prompt=prompt,
            chatbot_id=chatbot_id,
            provider=None,
            model=None,
            temperature=0.3,
            operation_type=OPERATION_WEBSITE_KNOWLEDGE_EXTRACTION,
        )
    except Exception as e:
        logging.error(f"Error in extract_business_knowledge: {e}")
        return raw_text




def save_refined_knowledge_chunks(text_content, file_name, primary_url, chatbot_id, company_id=None):
    if not text_content:
        raise ValueError("Text content cannot be empty.")

    file_size = len(text_content.encode('utf-8'))
    # Check storage limit before saving
    if company_id:
        can_upload_knowledge_storage(company_id, file_size)

    # Save to knowledge_files table
    file_record = save_knowledge_file(
        chatbot_id=chatbot_id,
        file_name=file_name,
        file_type="url",
        file_size=file_size,
        file_path=primary_url,
        upload_status="uploaded",
        processing_status="completed",
        match_status="unchecked"
    )

    file_id = file_record["id"]

    try:
        import logging
        from app.services.rag_service import split_text_into_sections, generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk

        chunks = split_text_into_sections(text_content)

        logging.info(f"[KnowledgeService] Processing {len(chunks)} chunks for database insertion...")

        for idx, chunk in enumerate(chunks):
            embedding = generate_embedding(chunk)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk,
                    embedding=embedding,
                    metadata={"chunk_index": idx}
                )
        logging.info("[KnowledgeService] Successfully saved refined web chunks to Supabase.")

        try:
            extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
        except Exception as graph_err:
            logging.error(f"Failed to generate and store knowledge graph for refined web chunks: {graph_err}")
    except Exception as e:
        import logging
        logging.error(f"Failed to process refined web chunks: {e}")

    return {
        "file_name": file_name,
        "message": "Website saved as supporting knowledge."
    }



def extract_and_store_graph_supabase(chunks: list, chatbot_id: int, file_id: int):
    """Extract knowledge graph nodes and relationships via the central AI router.

    Uses generate_system_response() so that subscription, provider, model-tier
    and AI-credit enforcement are applied.  No direct DeepSeek/OpenAI client
    is created here.
    """
    import json
    import logging
    import time
    from app.services.ai_router import (
        OPERATION_KNOWLEDGE_GRAPH_EXTRACTION,
        generate_system_response,
    )
    from app.database.knowledge_graph_repository import upsert_node, upsert_edge
    
    allowed_labels = {
        "Company", "Brand", "Category", "Product", "Service", "Package", "Accessory", 
        "Price", "Warranty", "Promotion", "Branch", "Supplier", "Customer Segment", 
        "Policy", "FAQ", "Staff", "Schedule", "Location", "Requirement", "Event"
    }
    
    prompt_template = """
Analyze the following text chunk and extract key entities and their relationships to construct a knowledge graph.

ALLOWED ENTITY LABELS (use ONLY these labels):
- Company (e.g. MegaCorp)
- Brand (e.g. Apple)
- Category (e.g. Electronics)
- Product (e.g. Titan Laptop)
- Service (e.g. Haircut, Screen Repair)
- Package (e.g. Student Starter Pack)
- Accessory (e.g. Phone Case)
- Price (e.g. $899, $50/hour)
- Warranty (e.g. 2-Year Damage Warranty)
- Promotion (e.g. Back to School Discount)
- Branch (e.g. Downtown Branch)
- Supplier (e.g. DHL, Local Farm)
- Customer Segment (e.g. Students, VIPs)
- Policy (e.g. 30-Day Return Policy)
- FAQ (e.g. Questions & Answers about a policy/product)
- Staff (e.g. Dr. Alice, Stylist Sarah)
- Schedule (e.g. Weekdays 9am-5pm)
- Location (e.g. West Side delivery zone, 123 Main Street)
- Requirement (e.g. Fasting 12 hours prior, 18+ age limit)
- Event (e.g. Yoga Flow class, Summer Seminar)

Return the output as a valid JSON object matching this structure:
{
   "nodes": [
      {"name": "Entity Name", "label": "One of the allowed labels", "description": "Short definition or value"}
   ],
   "relationships": [
      {"source": "Entity Name 1", "target": "Entity Name 2", "type": "Relationship verb or tag (uppercase)"}
   ]
}

Rules:
1. The 'label' in nodes MUST be exactly one of the ALLOWED ENTITY LABELS.
2. The node 'name' should be concise and normalized (e.g. "student" instead of "students", lowercase is fine but keep readable casing).
3. Do not invent entities or relationships not directly supported by the text.
4. Avoid self-referencing relationships where source and target are the same.
5. Return the raw JSON without markdown formatting backticks.
"""

    logging.info(f"[GraphRAG] Extracting entities and relations for file_id={file_id} from {len(chunks)} chunks...")
    
    for i, chunk in enumerate(chunks):
        try:
            time.sleep(0.1)
            
            prompt = prompt_template + f"\n\nText Chunk:\n{chunk}"
            res_text = generate_system_response(
                prompt=prompt,
                chatbot_id=chatbot_id,
                provider=None,
                model=None,
                temperature=0.1,
                json_response=True,
                operation_type=OPERATION_KNOWLEDGE_GRAPH_EXTRACTION,
            )
            if not res_text:
                continue

            data = json.loads(res_text)
            
            # 1. Store extracted nodes
            nodes_dict = {}
            for node in data.get("nodes", []):
                name = node.get("name", "").strip()
                label = node.get("label", "").strip()
                desc = node.get("description", "").strip()
                
                if not name or not label:
                    continue
                    
                matched_label = next((l for l in allowed_labels if l.lower() == label.lower()), None)
                if not matched_label:
                    logging.warning(f"[GraphRAG] Skipping node '{name}' with invalid label '{label}'")
                    continue
                    
                properties = {"description": desc} if desc else {}
                upserted = upsert_node(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    name=name,
                    label=matched_label,
                    properties=properties
                )
                if upserted:
                    nodes_dict[name.lower()] = name
                    
            # 2. Store extracted edges
            for edge in data.get("relationships", []):
                src = edge.get("source", "").strip()
                tgt = edge.get("target", "").strip()
                rtype = edge.get("type", "").strip().upper().replace(" ", "_")
                
                if not src or not tgt or not rtype:
                    continue
                    
                upsert_edge(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    source_name=src,
                    target_name=tgt,
                    rel_type=rtype
                )
                
        except Exception as e:
            logging.error(f"[GraphRAG] Failed processing chunk index {i}: {e}")
            err_msg = str(e)
            is_billing = "402" in err_msg or "billing" in err_msg.lower() or "payment" in err_msg.lower() or "credit" in err_msg.lower()
            if is_billing:
                raise e
            continue

    logging.info(f"[GraphRAG] Finished graph extraction for file_id={file_id}.")


def generate_and_save_knowledge_readme(chatbot_id: int, file_id: int = None):
    import os
    import logging
    from datetime import datetime
    from app.database.db import supabase
    from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
    from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot

    if file_id is None:
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            readme_path = os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_readme.md")
            if os.path.exists(readme_path):
                try:
                    os.remove(readme_path)
                except Exception:
                    pass
            return
        file_id = active_file["id"]
        file_name = active_file.get("file_name", "Primary Document")
        display_file_name = active_file.get("original_file_name") or file_name
    else:
        try:
            res = supabase.table("knowledge_files").select("*").eq("chatbot_id", chatbot_id).eq("id", file_id).limit(1).execute()
            file_record = res.data[0] if res.data else None
        except Exception as err:
            logging.error(f"Failed to fetch knowledge file record inside readme generation: {err}")
            file_record = None
        if not file_record:
            return
        file_name = file_record.get("file_name", "Primary Document")
        display_file_name = file_record.get("original_file_name") or file_name

    # 1. Fetch chunks (original document text chunks)
    chunks_data = get_chunks_by_file_for_chatbot(chatbot_id, file_id) or []
    pdf_chunks = []
    qa_list = []

    for c in chunks_data:
        meta = c.get("metadata") or {}
        content = c.get("content", "").strip()
        if meta.get("source_type") == "refinement":
            question = meta.get("question", "").strip()
            answer = ""
            if "Answer:" in content:
                parts = content.split("Answer:", 1)
                answer = parts[1].strip()
            if question and answer:
                qa_list.append({"question": question, "answer": answer})
        else:
            if content:
                pdf_chunks.append(content)

    # 2. Fetch Graph Nodes
    nodes = []
    try:
        nodes_res = (
            supabase.table("knowledge_graph_nodes")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        nodes = nodes_res.data or []
    except Exception as err:
        logging.error(f"Failed to fetch graph nodes for readme: {err}")

    # 3. Fetch Graph Edges
    edges = []
    try:
        edges_res = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )
        edges = edges_res.data or []
    except Exception as err:
        logging.error(f"Failed to fetch graph edges for readme: {err}")

    # Build the README contents
    md = []
    md.append(f"# Knowledge Base README: {display_file_name}")
    md.append(f"- **Generated Date**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    md.append(f"- **Chatbot ID**: {chatbot_id}")
    md.append("")

    md.append("## Document Overview")
    md.append(f"This document represents the compiled knowledge source for Chatbot #{chatbot_id}, extracted from the document `{display_file_name}`.")
    md.append(f"- Total Text Chunks: {len(pdf_chunks)}")
    md.append(f"- Total Graph Nodes: {len(nodes)}")
    md.append(f"- Total Graph Connections: {len(edges)}")
    md.append(f"- Total Refined Q&As: {len(qa_list)}")
    md.append("")

    md.append("## Knowledge Graph")
    md.append("### Entities (Nodes)")
    if nodes:
        md.append("| Name | Category | Description |")
        md.append("| --- | --- | --- |")
        for n in nodes:
            name = n.get("name", "").title()
            label = n.get("label", "")
            desc = n.get("properties", {}).get("description", "") if isinstance(n.get("properties"), dict) else ""
            md.append(f"| {name} | {label} | {desc} |")
    else:
        md.append("*No entities defined in the knowledge graph.*")
    md.append("")

    md.append("### Connections (Relationships)")
    if edges:
        for e in edges:
            src = e.get("source_name", "").title()
            tgt = e.get("target_name", "").title()
            rel = e.get("rel_type", "").replace("_", " ")
            md.append(f"- **{src}** [{rel}] -> **{tgt}**")
    else:
        md.append("*No connections defined in the knowledge graph.*")
    md.append("")

    md.append("## Knowledge Refinement Q&A")
    if qa_list:
        for idx, qa in enumerate(qa_list, 1):
            md.append(f"### Q{idx}. {qa['question']}")
            md.append(f"{qa['answer']}")
            md.append("")
    else:
        md.append("*No custom refined Q&A clarifications have been added yet.*")
    md.append("")

    md.append("## Document Text Chunks")
    if pdf_chunks:
        for idx, chunk in enumerate(pdf_chunks, 1):
            md.append(f"### Chunk {idx}")
            md.append(chunk)
            md.append("")
    else:
        md.append("*No raw document chunks available.*")

    # Save to disk
    readme_path = os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_{file_id}_readme.md")
    os.makedirs(DATA_FOLDER, exist_ok=True)
    try:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        logging.info(f"Successfully generated and saved knowledge README for chatbot_id={chatbot_id}, file_id={file_id} to {readme_path}")

        # Also copy/save to bot_{chatbot_id}_readme.md if this is the active file
        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        active = get_active_pdf_knowledge_file(chatbot_id)
        if active and active["id"] == file_id:
            active_readme_path = os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_readme.md")
            with open(active_readme_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md))
    except Exception as e:
        logging.error(f"Failed to save knowledge README to {readme_path}: {e}")


def get_or_generate_readme(chatbot_id: int, file_id: int = None, company_id: int = None) -> str:
    import os
    from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
    if file_id is None:
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            return "No active primary PDF or knowledge sources available to generate README."
        file_id = active_file["id"]

    readme_path = os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_{file_id}_readme.md")
    if not os.path.exists(readme_path):
        if company_id is not None:
            from app.services.company_status_service import ensure_company_operational
            ensure_company_operational(company_id)
        generate_and_save_knowledge_readme(chatbot_id, file_id)

    if os.path.exists(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading README file: {e}"
    else:
        return "No active primary PDF or knowledge sources available to generate README."


def log_knowledge_modification(chatbot_id: int, file_id: int, action: str, category: str = "Admin State Changes", details=None):
    import os
    import json
    from datetime import datetime

    if not file_id:
        return

    log_path = os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_{file_id}_history.json")
    os.makedirs(DATA_FOLDER, exist_ok=True)

    logs = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    entry = {
        "timestamp": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        "action": action,
        "category": category
    }
    if details is not None:
        entry["details"] = details
    logs.append(entry)

    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        import logging
        logging.error(f"Failed to write history log to {log_path}: {e}")


def get_knowledge_history_logs(chatbot_id: int, file_id: int) -> list:
    import os
    import json
    log_path = os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_{file_id}_history.json")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
            # Ensure every entry has a category
            for entry in logs:
                if "category" not in entry:
                    act = entry.get("action", "").lower()
                    if any(x in act for x in ("graph", "entity", "connection", "relationship", "node", "edge")):
                        entry["category"] = "Graph Modifications"
                    elif any(x in act for x in ("q&a", "refined", "clarification", "answers")):
                        entry["category"] = "Q&A Submissions"
                    else:
                        entry["category"] = "Admin State Changes"
            return logs
        except Exception:
            return []
    return []
