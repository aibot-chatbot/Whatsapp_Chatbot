"""Preflight validation for supporting PDF candidates.

Validation deliberately avoids normal knowledge ingestion, graph extraction,
persona derivation, README generation, and permanent knowledge chunk writes. The
V2 scorer may use bounded temporary candidate embeddings, while reusing already
stored Primary chunk embeddings, to produce an application relevance score that
still needs real-document calibration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median

from werkzeug.utils import secure_filename

from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
from app.database.knowledge_file_repository import get_active_knowledge_file
from app.database.knowledge_file_repository import get_knowledge_file_by_source_candidate
from app.database.knowledge_pdf_candidate_repository import (
    claim_candidate_for_confirmation,
    create_candidate,
    get_candidate,
    mark_candidate_cancelled,
    mark_candidate_expired,
    mark_candidate_ingest_failed,
    mark_candidate_ingested,
    mark_candidate_validated,
    recover_candidate_ingested,
)
from app.services.document_ocr_service import extract_pdf_markdown
from app.services import document_storage_service as document_storage
from app.services.knowledge_service import DATA_FOLDER, save_uploaded_pdf
from app.services.upload_validation_service import MAX_UPLOAD_BYTES, validate_saved_pdf
from werkzeug.exceptions import RequestEntityTooLarge
from app.services.billing_guard import can_upload_knowledge_file, can_upload_knowledge_storage
from app.services.rag_service import EMBEDDING_DIMENSION, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

CANDIDATE_DATA_FOLDER = os.path.join(DATA_FOLDER, "_pdf_candidates")
CANDIDATE_EXPIRY_HOURS = 24
MAX_DOCUMENT_CHUNKS = 120
MAX_CHARS_PER_CHUNK = 2500
MAX_TOTAL_CHARS = 250000
MIN_TEXT_CHARACTERS = 20
SCORING_VERSION = "semantic_hybrid_v2"
VALIDATION_EMBEDDING_MODEL = EMBEDDING_MODEL
VALIDATION_EMBEDDING_DIMENSION = EMBEDDING_DIMENSION
VALIDATION_MAX_EMBEDDED_CHUNKS = 48
VALIDATION_MAX_EMBEDDED_CHARS = 60000
SEMANTIC_STRONG_MATCH_THRESHOLD = 0.72
SEMANTIC_WEAK_MATCH_THRESHOLD = 0.50
NEAR_DUPLICATE_CANDIDATE_COVERAGE_THRESHOLD = 0.94
NEAR_DUPLICATE_PRIMARY_ALIGNMENT_THRESHOLD = 0.88
V2_WEIGHT_SEMANTIC_COVERAGE = 0.82
V2_WEIGHT_SEMANTIC_MEDIAN = 0.08
V2_WEIGHT_STRONG_MATCH_RATIO = 0.05
V2_WEIGHT_DOMAIN_ANCHOR = 0.03
V2_WEIGHT_LEXICAL = 0.02
V2_WEIGHT_WEAK_RATIO_PENALTY = 0.05

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "if", "in", "into", "is", "it", "its", "of", "on", "or", "our",
    "that", "the", "their", "this", "to", "was", "we", "were", "will", "with",
    "you", "your", "can", "not", "all", "any", "per", "may", "should", "shall",
    "about", "after", "also", "before", "between", "but", "each", "more",
    "than", "then", "there", "these", "they", "those", "through", "using",
    "where", "which", "while",
}

BOILERPLATE_TERMS = {
    "section", "sections", "page", "pages", "document", "documents", "pdf",
    "file", "files", "question", "questions", "answer", "answers", "trigger",
    "triggers", "chatbot", "bot", "faq", "faqs", "supplementary", "supporting",
    "primary", "source", "sources", "http", "https", "www", "com", "net",
    "org", "edu", "my", "html", "php", "email", "phone", "telephone",
    "whatsapp", "sdn", "bhd", "ltd", "llc", "inc", "corp", "co", "company",
}
ANCHOR_BOILERPLATE_TERMS = BOILERPLATE_TERMS - {"edu"}


class CandidateStateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _StoredCandidateUpload:
    def __init__(self, source_path: str, filename: str):
        self.source_path = source_path
        self.filename = filename

    def save(self, destination: str):
        shutil.copyfile(self.source_path, destination)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def normalize_text(text: str) -> str:
    pieces = []
    for char in (text or "").casefold():
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            pieces.append(char)
        else:
            pieces.append(" ")
    return " ".join("".join(pieces).split())


def content_sha256(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    tokens = re.findall(r"\w{2,}", normalized, flags=re.UNICODE)
    filtered = [
        token for token in tokens
        if token not in STOPWORDS and token not in BOILERPLATE_TERMS and not token.isdigit()
    ]
    if filtered:
        return filtered

    compact = "".join(re.findall(r"\w", normalized, flags=re.UNICODE))
    if len(compact) >= 3:
        return [compact[index:index + 3] for index in range(0, len(compact) - 2)]
    return filtered


def _clean_topic_text(text: str) -> str:
    text = re.sub(r"(?im)^\s*section\s*:\s*", " ", text or "")
    text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[\w.-]+\.(?:com|net|org|edu|my|io|ai|co)\b\S*", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?im)^\s*(?:page|p\.)\s*\d+(?:\s*/\s*\d+)?\s*$", " ", text)
    return text


def _topic_tokens(text: str) -> list[str]:
    return _tokenize(_clean_topic_text(text))


def _top_terms_from_texts(texts: list[str], limit: int = 12) -> list[str]:
    total = Counter()
    for text in texts:
        total.update(_topic_tokens(text))
    return [term for term, _count in total.most_common(limit)]


def _normalize_anchor(anchor: str) -> str:
    words = [
        word.casefold()
        for word in re.findall(r"[\w&+-]+", anchor, flags=re.UNICODE)
        if word.casefold() not in STOPWORDS and word.casefold() not in ANCHOR_BOILERPLATE_TERMS
    ]
    return " ".join(words)


def _extract_domain_anchors(text: str, limit: int = 60) -> list[str]:
    """Extract lightweight entity/product anchors without an LLM."""
    cleaned = _clean_topic_text(text or "")
    anchors = Counter()

    phrase_pattern = re.compile(
        r"\b(?:[A-Z][A-Za-z0-9&+-]{2,}|[A-Z]{2,}|[A-Za-z]+[A-Z][A-Za-z0-9&+-]*)"
        r"(?:\s+(?:[A-Z][A-Za-z0-9&+-]{2,}|[A-Z]{2,}|[A-Za-z]+[A-Z][A-Za-z0-9&+-]*)){0,3}\b"
    )
    for match in phrase_pattern.finditer(cleaned):
        anchor = _normalize_anchor(match.group(0))
        if anchor and len(anchor) >= 3:
            anchors[anchor] += 2 if " " in anchor else 1

    tokens = _topic_tokens(cleaned)
    for first, second in zip(tokens, tokens[1:]):
        if first in BOILERPLATE_TERMS or second in BOILERPLATE_TERMS:
            continue
        if len(first) >= 4 and len(second) >= 4:
            anchors[f"{first} {second}"] += 1

    return [anchor for anchor, _count in anchors.most_common(limit)]


def _domain_anchor_score(candidate_texts: list[str], primary_texts: list[str]) -> tuple[float, list[str]]:
    candidate_anchors = set(_extract_domain_anchors("\n".join(candidate_texts)))
    primary_anchors = set(_extract_domain_anchors("\n".join(primary_texts)))
    if not candidate_anchors:
        return 0.0, []
    shared = sorted(candidate_anchors & primary_anchors)
    score = len(shared) / max(1, min(len(candidate_anchors), 20))
    return max(0.0, min(1.0, score)), shared[:8]


def _coerce_numeric_vector(value, expected_dimension: int) -> list[float] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if not isinstance(value, (list, tuple)) or len(value) != expected_dimension:
        return None
    vector = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        if not math.isfinite(float(item)):
            return None
        vector.append(float(item))
    return vector


def _dense_cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _select_representative_chunks(
    chunks: list[str],
    max_chunks: int = VALIDATION_MAX_EMBEDDED_CHUNKS,
    max_chars: int = VALIDATION_MAX_EMBEDDED_CHARS,
) -> tuple[list[str], dict]:
    meaningful = [chunk for chunk in chunks if len(_topic_tokens(chunk)) >= 3]
    candidates = meaningful or chunks
    considered = len(candidates)
    if not candidates:
        return [], {
            "candidate_chunks_considered": 0,
            "candidate_embedded_chunk_count": 0,
            "candidate_embedded_character_count": 0,
            "representation_truncated": False,
        }

    if len(candidates) <= max_chunks:
        ordered_indexes = list(range(len(candidates)))
    elif max_chunks <= 1:
        ordered_indexes = [0]
    else:
        ordered_indexes = sorted({
            round(index * (len(candidates) - 1) / (max_chunks - 1))
            for index in range(max_chunks)
        })

    selected = []
    total_chars = 0
    truncated = len(ordered_indexes) < len(candidates)
    for index in ordered_indexes:
        chunk = candidates[index][:MAX_CHARS_PER_CHUNK]
        if total_chars + len(chunk) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 0:
                selected.append(chunk[:remaining])
                total_chars += remaining
            truncated = True
            break
        selected.append(chunk)
        total_chars += len(chunk)

    return selected, {
        "candidate_chunks_considered": considered,
        "candidate_embedded_chunk_count": len(selected),
        "candidate_embedded_character_count": total_chars,
        "representation_truncated": truncated,
    }


def embed_validation_chunks(
    texts: list[str],
    expected_dimension: int = VALIDATION_EMBEDDING_DIMENSION,
) -> tuple[list[list[float]], dict]:
    """Generate temporary candidate embeddings without persisting chunks."""
    from app.services.rag_service import generate_embedding

    vectors = []
    request_count = 0
    for text in texts:
        request_count += 1
        vector = _coerce_numeric_vector(generate_embedding(text), expected_dimension)
        if vector is None:
            raise CandidateStateError(
                "validation_embedding_failed",
                "Could not complete semantic validation for this PDF. Please try again.",
            )
        vectors.append(vector)
    return vectors, {"embedding_request_count": request_count}


def _trim_chunks(chunks: list[str]) -> tuple[list[str], bool]:
    trimmed = []
    consumed = 0
    truncated = False
    for chunk in chunks:
        text = (chunk or "").strip()
        if not text:
            continue
        if len(text) > MAX_CHARS_PER_CHUNK:
            text = text[:MAX_CHARS_PER_CHUNK]
            truncated = True
        if consumed + len(text) > MAX_TOTAL_CHARS:
            remaining = MAX_TOTAL_CHARS - consumed
            if remaining > 0:
                trimmed.append(text[:remaining])
            truncated = True
            break
        trimmed.append(text)
        consumed += len(text)
        if len(trimmed) >= MAX_DOCUMENT_CHUNKS:
            truncated = True
            break
    return trimmed, truncated


def _split_candidate_text(markdown: str) -> list[str]:
    try:
        from app.services.rag_service import split_text_into_sections

        chunks = split_text_into_sections(markdown)
    except Exception:
        chunks = re.split(r"\n\s*\n+", markdown or "")
    return [chunk for chunk in chunks if chunk and chunk.strip()]


def _canonical_candidate_chunks(markdown: str) -> list[str]:
    return [(chunk or "").strip() for chunk in _split_candidate_text(markdown) if (chunk or "").strip()]


def _build_vectors(documents: list[str]):
    counters = [Counter(_tokenize(doc)) for doc in documents]
    doc_count = len(counters)
    df = Counter()
    for counts in counters:
        df.update(counts.keys())

    vectors = []
    norms = []
    for counts in counters:
        vector = {}
        total = sum(counts.values()) or 1
        for token, count in counts.items():
            tf = count / total
            idf = math.log((doc_count + 1) / (df[token] + 1)) + 1.0
            vector[token] = tf * idf
        norm = math.sqrt(sum(value * value for value in vector.values()))
        vectors.append(vector)
        norms.append(norm)
    return vectors, norms, counters


def _cosine(left: dict, left_norm: float, right: dict, right_norm: float) -> float:
    if not left_norm or not right_norm:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _top_terms(counters: list[Counter], limit: int = 12) -> list[str]:
    total = Counter()
    for counts in counters:
        total.update(counts)
    return [term for term, _count in total.most_common(limit)]


def _primary_texts_and_embeddings(
    primary_chunks: list,
    expected_dimension: int,
) -> tuple[list[str], list[list[float]] | None, str | None]:
    texts = []
    embeddings = []
    for chunk in primary_chunks:
        if isinstance(chunk, dict):
            text = chunk.get("content", "")
            raw_embedding = chunk.get("embedding")
        else:
            text = str(chunk or "")
            raw_embedding = None
        texts.append(text)
        vector = _coerce_numeric_vector(raw_embedding, expected_dimension)
        if vector is None:
            return texts, None, "primary_embeddings_unavailable"
        embeddings.append(vector)
    return texts, embeddings, None


def _lexical_overlap(candidate_chunks: list[str], primary_chunks: list[str]) -> tuple[float, list[str], list[str], list[str]]:
    candidate_counters = [Counter(_topic_tokens(chunk)) for chunk in candidate_chunks]
    primary_counters = [Counter(_topic_tokens(chunk)) for chunk in primary_chunks]
    candidate_terms = set().union(*(counter.keys() for counter in candidate_counters)) if candidate_counters else set()
    primary_terms = set().union(*(counter.keys() for counter in primary_counters)) if primary_counters else set()
    overlap = len(candidate_terms & primary_terms) / max(1, len(candidate_terms))
    candidate_topics = _top_terms_from_texts(candidate_chunks)
    primary_topics = _top_terms_from_texts(primary_chunks)
    matched_topics = [term for term in candidate_topics if term in primary_terms][:8]
    unrelated_topics = [term for term in candidate_topics if term not in primary_terms][:8]
    return max(0.0, min(1.0, overlap)), matched_topics, unrelated_topics, primary_topics


def _weighted_mean(values: list[float], weights: list[int]) -> float:
    denominator = sum(weights)
    if not values or not denominator:
        return 0.0
    return sum(value * weight for value, weight in zip(values, weights)) / denominator


def _semantic_failure_result(code: str, reason: str, threshold: float, candidate_hash: str | None, primary_hash: str | None, truncated: bool) -> dict:
    result = _failed_comparison(code, reason, threshold, truncated=truncated)
    result["content_sha256"] = candidate_hash
    result["primary_content_sha256"] = primary_hash
    result["features"].update({
        "scoring_version": SCORING_VERSION,
        "error_code": code,
        "embedding_model": VALIDATION_EMBEDDING_MODEL,
        "embedding_dimension": VALIDATION_EMBEDDING_DIMENSION,
    })
    return result


def _validation_system_error_message(code: str) -> str:
    if code == "primary_embeddings_unavailable":
        return "The current Primary source is missing compatible semantic validation data. Please reprocess the Primary PDF before validating Supporting PDFs."
    return "We could not complete document validation. Please try again."


def compare_candidate_to_primary(
    candidate_text: str,
    primary_chunks_or_texts: list,
    threshold: float,
    *,
    embedder=None,
    embedding_dimension: int = VALIDATION_EMBEDDING_DIMENSION,
    max_embedded_chunks: int = VALIDATION_MAX_EMBEDDED_CHUNKS,
    max_embedded_chars: int = VALIDATION_MAX_EMBEDDED_CHARS,
    canonical_primary_hash: str | None = None,
) -> dict:
    embedder = embedder or embed_validation_chunks
    all_candidate_chunks = _canonical_candidate_chunks(candidate_text)
    candidate_chunks, candidate_lexical_truncated = _trim_chunks(all_candidate_chunks)
    primary_texts, primary_embeddings, primary_embedding_error = _primary_texts_and_embeddings(
        primary_chunks_or_texts,
        embedding_dimension,
    )
    primary_chunks, primary_truncated = _trim_chunks(primary_texts)

    if not all_candidate_chunks:
        return _failed_comparison(
            "zero_text",
            "No readable text could be extracted from this PDF.",
            threshold,
            truncated=candidate_lexical_truncated or primary_truncated,
        )
    if not primary_chunks:
        return _failed_comparison(
            "primary_has_no_chunks",
            "The current Primary source has no searchable chunks to compare against.",
            threshold,
            truncated=candidate_lexical_truncated or primary_truncated,
        )

    candidate_hash = content_sha256("\n".join(all_candidate_chunks))
    primary_hash = canonical_primary_hash or content_sha256("\n".join(primary_texts))
    lexical_overlap, matched_topics, unrelated_topics, primary_topics = _lexical_overlap(candidate_chunks, primary_chunks)
    domain_anchor_score, shared_anchors = _domain_anchor_score(candidate_chunks, primary_chunks)

    duplicate_status = "none"
    if candidate_hash == primary_hash:
        candidate_topics = _top_terms_from_texts(candidate_chunks)
        reason = "This PDF appears to contain the same normalized text as the current Primary source."
        return {
            "score": 1.0,
            "threshold": threshold,
            "passed": False,
            "duplicate_status": "exact_content_duplicate",
            "content_sha256": candidate_hash,
            "primary_content_sha256": primary_hash,
            "candidate_summary": _summary_from_terms(candidate_topics),
            "primary_topic_summary": _summary_from_terms(primary_topics),
            "matched_topics": matched_topics,
            "unrelated_topics": [],
            "reason": reason,
            "suggestions": [
                "Upload a document that adds new policies, procedures, catalog details, or other supporting content.",
                "If this document should replace the Primary source, use the Primary upload workflow instead.",
            ],
            "truncated": candidate_lexical_truncated or primary_truncated,
            "features": {
                "scoring_version": SCORING_VERSION,
                "duplicate_status": "exact_content_duplicate",
                "embedding_model": VALIDATION_EMBEDDING_MODEL,
                "embedding_dimension": embedding_dimension,
                "candidate_total_chunk_count": len(all_candidate_chunks),
                "candidate_chunk_count": len(candidate_chunks),
                "candidate_lexical_chunk_count": len(candidate_chunks),
                "primary_chunk_count": len(primary_chunks),
                "candidate_embedded_chunk_count": 0,
                "embedding_request_count": 0,
                "lexical_overlap_score": round(lexical_overlap, 5),
                "domain_anchor_score": round(domain_anchor_score, 5),
                "final_relevance_score": 1.0,
            },
        }

    if primary_embedding_error or primary_embeddings is None:
        return _semantic_failure_result(
            primary_embedding_error or "primary_embeddings_unavailable",
            _validation_system_error_message(primary_embedding_error or "primary_embeddings_unavailable"),
            threshold,
            candidate_hash,
            primary_hash,
            candidate_lexical_truncated or primary_truncated,
        )

    representative_chunks, representation = _select_representative_chunks(
        all_candidate_chunks,
        max_chunks=max_embedded_chunks,
        max_chars=max_embedded_chars,
    )
    if not representative_chunks:
        return _semantic_failure_result(
            "zero_text",
            "No meaningful text could be selected from this PDF for semantic validation.",
            threshold,
            candidate_hash,
            primary_hash,
            candidate_lexical_truncated or primary_truncated,
        )

    try:
        candidate_embeddings, embedding_diag = embedder(representative_chunks, expected_dimension=embedding_dimension)
    except CandidateStateError as exc:
        return _semantic_failure_result(
            exc.code,
            str(exc),
            threshold,
            candidate_hash,
            primary_hash,
            candidate_lexical_truncated or primary_truncated or representation.get("representation_truncated", False),
        )
    except Exception:
        logger.exception("Temporary validation embedding failed")
        return _semantic_failure_result(
            "validation_embedding_failed",
            _validation_system_error_message("validation_embedding_failed"),
            threshold,
            candidate_hash,
            primary_hash,
            candidate_lexical_truncated or primary_truncated or representation.get("representation_truncated", False),
        )

    if len(candidate_embeddings or []) != len(representative_chunks):
        return _semantic_failure_result(
            "validation_embedding_cardinality_mismatch",
            _validation_system_error_message("validation_embedding_cardinality_mismatch"),
            threshold,
            candidate_hash,
            primary_hash,
            candidate_lexical_truncated or primary_truncated or representation.get("representation_truncated", False),
        )

    candidate_embeddings = [
        _coerce_numeric_vector(vector, embedding_dimension)
        for vector in candidate_embeddings
    ]
    if any(vector is None for vector in candidate_embeddings):
        return _semantic_failure_result(
            "validation_embedding_failed",
            _validation_system_error_message("validation_embedding_failed"),
            threshold,
            candidate_hash,
            primary_hash,
            candidate_lexical_truncated or primary_truncated or representation.get("representation_truncated", False),
        )

    best_candidate_matches = []
    best_primary_indexes = []
    weak_chunks = []
    for chunk, vector in zip(representative_chunks, candidate_embeddings):
        similarities = [_dense_cosine(vector, primary_vector) for primary_vector in primary_embeddings]
        best = max(similarities) if similarities else 0.0
        best_candidate_matches.append(best)
        best_primary_indexes.append(similarities.index(best) if similarities else None)
        if best < SEMANTIC_WEAK_MATCH_THRESHOLD:
            weak_chunks.append(chunk)

    primary_alignments = []
    for primary_vector in primary_embeddings:
        similarities = [_dense_cosine(primary_vector, candidate_vector) for candidate_vector in candidate_embeddings]
        primary_alignments.append(max(similarities) if similarities else 0.0)

    weights = [max(1, len(_topic_tokens(chunk))) for chunk in representative_chunks]
    semantic_candidate_coverage = _weighted_mean(best_candidate_matches, weights)
    semantic_median_match = median(best_candidate_matches) if best_candidate_matches else 0.0
    semantic_strong_match_ratio = (
        sum(1 for score in best_candidate_matches if score >= SEMANTIC_STRONG_MATCH_THRESHOLD)
        / len(best_candidate_matches)
        if best_candidate_matches else 0.0
    )
    semantic_weak_match_ratio = (
        sum(1 for score in best_candidate_matches if score < SEMANTIC_WEAK_MATCH_THRESHOLD)
        / len(best_candidate_matches)
        if best_candidate_matches else 0.0
    )
    primary_alignment = sum(primary_alignments) / len(primary_alignments) if primary_alignments else 0.0
    lower_tail = sorted(best_candidate_matches)[max(0, math.floor(len(best_candidate_matches) * 0.25) - 1)] if best_candidate_matches else 0.0

    raw_score = (
        (V2_WEIGHT_SEMANTIC_COVERAGE * semantic_candidate_coverage)
        + (V2_WEIGHT_SEMANTIC_MEDIAN * semantic_median_match)
        + (V2_WEIGHT_STRONG_MATCH_RATIO * semantic_strong_match_ratio)
        + (V2_WEIGHT_DOMAIN_ANCHOR * domain_anchor_score)
        + (V2_WEIGHT_LEXICAL * lexical_overlap)
        - (V2_WEIGHT_WEAK_RATIO_PENALTY * semantic_weak_match_ratio)
    )
    score = max(0.0, min(1.0, raw_score))

    if (
        semantic_candidate_coverage >= NEAR_DUPLICATE_CANDIDATE_COVERAGE_THRESHOLD
        and primary_alignment >= NEAR_DUPLICATE_PRIMARY_ALIGNMENT_THRESHOLD
        and lexical_overlap >= 0.65
    ):
        duplicate_status = "possible_near_duplicate"

    passed = score >= threshold and duplicate_status != "exact_content_duplicate"
    candidate_topics = _top_terms_from_texts(candidate_chunks)
    semantic_unrelated_topics = [
        term for term in _top_terms_from_texts(weak_chunks, limit=8)
        if term not in set(_topic_tokens("\n".join(primary_chunks)))
    ]
    if shared_anchors:
        matched_topics = list(dict.fromkeys(shared_anchors + matched_topics))[:8]
    unrelated_topics = semantic_unrelated_topics or unrelated_topics

    if passed:
        reason = "The candidate has strong semantic coverage against the current Primary knowledge domain."
        suggestions = []
    else:
        reason = "The candidate does not have enough semantic coverage against the current Primary knowledge domain."
        suggestions = [
            "Upload a PDF that supports the same products, services, policies, procedures, or operating domain as the Primary source.",
            "Remove unrelated appendices or combine only the relevant supporting sections into a smaller PDF.",
        ]

    features = {
        "scoring_version": SCORING_VERSION,
        "embedding_model": VALIDATION_EMBEDDING_MODEL,
        "embedding_dimension": embedding_dimension,
        "candidate_total_chunk_count": len(all_candidate_chunks),
        "candidate_chunk_count": len(candidate_chunks),
        "candidate_lexical_chunk_count": len(candidate_chunks),
        "candidate_lexical_truncated": candidate_lexical_truncated,
        "primary_chunk_count": len(primary_chunks),
        "candidate_chunks_considered": representation.get("candidate_chunks_considered", len(candidate_chunks)),
        "candidate_embedded_chunk_count": representation.get("candidate_embedded_chunk_count", len(representative_chunks)),
        "candidate_embedded_character_count": representation.get("candidate_embedded_character_count", sum(len(chunk) for chunk in representative_chunks)),
        "embedding_request_count": embedding_diag.get("embedding_request_count", len(representative_chunks)),
        "semantic_candidate_coverage": round(semantic_candidate_coverage, 5),
        "semantic_median_match": round(semantic_median_match, 5),
        "semantic_strong_match_ratio": round(semantic_strong_match_ratio, 5),
        "semantic_weak_match_ratio": round(semantic_weak_match_ratio, 5),
        "semantic_lower_tail_match": round(lower_tail, 5),
        "domain_anchor_score": round(domain_anchor_score, 5),
        "lexical_overlap_score": round(lexical_overlap, 5),
        "primary_alignment": round(primary_alignment, 5),
        "final_relevance_score": round(score, 5),
        "representation_truncated": bool(
            candidate_lexical_truncated or primary_truncated or representation.get("representation_truncated", False)
        ),
        "weights": {
            "semantic_candidate_coverage": V2_WEIGHT_SEMANTIC_COVERAGE,
            "semantic_median_match": V2_WEIGHT_SEMANTIC_MEDIAN,
            "semantic_strong_match_ratio": V2_WEIGHT_STRONG_MATCH_RATIO,
            "domain_anchor_score": V2_WEIGHT_DOMAIN_ANCHOR,
            "lexical_overlap_score": V2_WEIGHT_LEXICAL,
            "semantic_weak_match_ratio_penalty": V2_WEIGHT_WEAK_RATIO_PENALTY,
        },
    }

    return {
        "score": round(score, 5),
        "threshold": threshold,
        "passed": passed,
        "duplicate_status": duplicate_status,
        "content_sha256": candidate_hash,
        "primary_content_sha256": primary_hash,
        "candidate_summary": _summary_from_terms(candidate_topics),
        "primary_topic_summary": _summary_from_terms(primary_topics),
        "matched_topics": matched_topics,
        "unrelated_topics": unrelated_topics,
        "reason": reason,
        "suggestions": suggestions,
        "truncated": bool(features["representation_truncated"]),
        "features": features,
    }


def _is_pdf_primary(primary_file: dict | None) -> bool:
    if not primary_file:
        return False
    file_type = (primary_file.get("file_type") or "").strip().lower()
    if file_type:
        return file_type == "pdf"

    file_name = (primary_file.get("file_name") or "").lower()
    original_file_name = (primary_file.get("original_file_name") or "").lower()
    file_path = (primary_file.get("file_path") or "").lower()
    return (
        file_name.endswith(".pdf")
        or original_file_name.endswith(".pdf")
        or file_path.endswith(".pdf")
    )


def _chunk_sort_key(chunk: dict):
    metadata = chunk.get("metadata") or {}
    chunk_index = metadata.get("chunk_index")
    if isinstance(chunk_index, int) and not isinstance(chunk_index, bool):
        return (0, chunk_index, "")
    if isinstance(chunk_index, str) and chunk_index.isdigit():
        return (0, int(chunk_index), "")
    return (1, str(chunk.get("id") or ""), chunk.get("content", ""))


def _load_primary_snapshot(chatbot_id: int, primary_file: dict) -> tuple[list[str], str]:
    primary_chunks = get_chunks_by_file_for_chatbot(chatbot_id, primary_file["id"])
    primary_chunks = sorted(primary_chunks, key=_chunk_sort_key)
    primary_texts = [chunk.get("content", "") for chunk in primary_chunks]
    return primary_texts, content_sha256("\n".join(primary_texts))


def _load_primary_chunks(chatbot_id: int, primary_file: dict) -> tuple[list[dict], str]:
    primary_chunks = get_chunks_by_file_for_chatbot(chatbot_id, primary_file["id"])
    primary_chunks = sorted(primary_chunks, key=_chunk_sort_key)
    primary_texts = [chunk.get("content", "") for chunk in primary_chunks]
    return primary_chunks, content_sha256("\n".join(primary_texts))


def _primary_changed_error() -> CandidateStateError:
    return CandidateStateError(
        "primary_changed_revalidation_required",
        "The Primary PDF has changed since this candidate was validated. Please validate the PDF again.",
    )


def _failed_comparison(code: str, reason: str, threshold: float, truncated: bool = False) -> dict:
    return {
        "score": 0.0,
        "threshold": threshold,
        "passed": False,
        "duplicate_status": "none",
        "content_sha256": None,
        "primary_content_sha256": None,
        "candidate_summary": "",
        "primary_topic_summary": "",
        "matched_topics": [],
        "unrelated_topics": [],
        "reason": reason,
        "suggestions": ["Upload a readable text-based PDF and try again."],
        "truncated": truncated,
        "features": {"error_code": code},
    }


def _summary_from_terms(terms: list[str]) -> str:
    if not terms:
        return ""
    return "Main detected terms: " + ", ".join(terms[:8])


def _safe_candidate_path(company_id: int, chatbot_id: int, candidate_id: str) -> str:
    folder = os.path.abspath(os.path.join(CANDIDATE_DATA_FOLDER, str(company_id), str(chatbot_id)))
    os.makedirs(folder, exist_ok=True)
    path = os.path.abspath(os.path.join(folder, f"{candidate_id}.pdf"))
    if not path.startswith(folder + os.sep):
        raise ValueError("Unsafe candidate storage path")
    return path


def _save_candidate_file(file, destination: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with open(destination, "wb") as handle:
        while True:
            chunk = file.stream.read(1024 * 1024) if hasattr(file, "stream") else file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise RequestEntityTooLarge()
            handle.write(chunk)
    try:
        file.seek(0)
    except Exception:
        pass
    return digest.hexdigest(), total


def cleanup_candidate_file(candidate: dict) -> bool:
    path = candidate.get("temp_file_path")
    if not path:
        return True
    try:
        abs_path = os.path.realpath(os.path.abspath(path))
        root = os.path.realpath(os.path.abspath(CANDIDATE_DATA_FOLDER))
        if not abs_path.startswith(root + os.sep):
            if document_storage.r2_enabled():
                raise document_storage.DocumentStorageError("Invalid candidate storage path.")
            logger.warning("Refusing to delete candidate file outside candidate storage")
            return False
        if document_storage.r2_enabled():
            document_storage.delete_file(abs_path, root=DATA_FOLDER, namespace="knowledge")
        elif os.path.exists(abs_path):
            os.remove(abs_path)
        return True
    except document_storage.DocumentStorageError:
        # All lifecycle callers must report failure until authoritative deletion succeeds.
        raise
    except Exception as exc:
        logger.warning("Failed to delete candidate file (%s)", type(exc).__name__)
        if document_storage.r2_enabled():
            raise document_storage.DocumentStorageError("Unable to delete candidate file.") from None
        return False


def validate_supporting_pdf_candidate(
    file,
    chatbot_id: int,
    company_id: int,
    created_by_user_id: int | None,
    threshold: float,
    primary_file: dict | None = None,
) -> dict:
    if not file:
        raise ValueError("No file provided")
    if not getattr(file, "filename", ""):
        raise ValueError("No selected file")
    if not file.filename.lower().endswith(".pdf"):
        raise ValueError("Invalid file type")
    if threshold < 0 or threshold > 1:
        raise ValueError("Relevance threshold must be between 0 and 1")

    primary_file = primary_file or get_active_knowledge_file(chatbot_id)
    if not primary_file:
        return {
            "validation_status": "no_primary_source",
            "passed": False,
            "can_confirm": False,
            "reason": "No Primary source exists for this chatbot yet.",
        }
    if not _is_pdf_primary(primary_file):
        return {
            "validation_status": "primary_not_pdf",
            "passed": False,
            "can_confirm": False,
            "reason": "The active Primary source is not a PDF, so PDF-to-PDF relevance validation cannot run.",
        }

    candidate_id = str(uuid.uuid4())
    safe_original = secure_filename(file.filename) or "candidate.pdf"
    temp_path = _safe_candidate_path(company_id, chatbot_id, candidate_id)
    candidate = None
    try:
        file_hash, size = _save_candidate_file(file, temp_path)
        validate_saved_pdf(temp_path)
    except Exception:
        # This fresh file has not reached remote storage or metadata yet.
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    expires_at = utc_now() + timedelta(hours=CANDIDATE_EXPIRY_HOURS)

    try:
        if document_storage.r2_enabled():
            document_storage.persist_file(temp_path, root=DATA_FOLDER, namespace="knowledge", chatbot_id=chatbot_id, company_id=company_id)
        candidate = create_candidate({
            "id": candidate_id,
            "company_id": company_id,
            "chatbot_id": chatbot_id,
            "primary_file_id": primary_file["id"],
            "original_file_name": file.filename,
            "safe_file_name": safe_original,
            "temp_file_path": temp_path,
            "file_size": size,
            "file_sha256": file_hash,
            "threshold": threshold,
            "validation_status": "validating",
            "passed": False,
            "duplicate_status": "none",
            "result_metadata": {},
            "created_by_user_id": created_by_user_id,
            "expires_at": isoformat(expires_at),
        })
    except Exception:
        try:
            cleanup_candidate_file({"temp_file_path": temp_path})
        finally:
            # No metadata was saved; remove the newly-created local copy even if
            # compensation cannot establish that the remote object was deleted.
            if os.path.exists(temp_path):
                os.remove(temp_path)
        raise

    try:
        extraction = extract_pdf_markdown(temp_path)
        if extraction.error or not extraction.has_text or len(normalize_text(extraction.markdown)) < MIN_TEXT_CHARACTERS:
            reason = extraction.error or "No readable text could be extracted from this PDF."
            result = _failed_comparison("pdf_unreadable", reason, threshold, truncated=extraction.truncated)
            updated = _mark_validation_result_or_raise(
                candidate_id,
                chatbot_id,
                company_id,
                {
                    "validation_status": "validated_failed",
                    "relevance_score": 0.0,
                    "passed": False,
                    "content_sha256": content_sha256(extraction.markdown),
                    "result_metadata": _metadata_payload(result, extraction.summary()),
                    "error_code": "pdf_unreadable",
                    "error_message": reason,
                },
            )
            cleanup_candidate_file({**candidate, **updated})
            return _response_from_candidate({**candidate, **updated}, result, primary_file)

        primary_chunks, primary_hash = _load_primary_chunks(chatbot_id, primary_file)
        result = compare_candidate_to_primary(
            extraction.markdown,
            primary_chunks,
            threshold,
            canonical_primary_hash=primary_hash,
        )
        status = "validated_passed" if result["passed"] else "validated_failed"
        result_error_code = (result.get("features") or {}).get("error_code")
        updated = _mark_validation_result_or_raise(
            candidate_id,
            chatbot_id,
            company_id,
            {
                "validation_status": status,
                "relevance_score": result["score"],
                "passed": result["passed"],
                "content_sha256": result["content_sha256"],
                "primary_content_sha256": primary_hash,
                "duplicate_status": result["duplicate_status"],
                "result_metadata": _metadata_payload(result, extraction.summary()),
                "error_code": None if result["passed"] else (result_error_code or "relevance_failed"),
                "error_message": None if result["passed"] else result["reason"],
            },
        )
        if not result["passed"]:
            cleanup_candidate_file({**candidate, **updated})
        return _response_from_candidate({**candidate, **updated}, result, primary_file)
    except Exception:
        if candidate:
            try:
                mark_candidate_validated(
                    candidate_id,
                    chatbot_id,
                    company_id,
                    {
                        "validation_status": "validated_failed",
                        "passed": False,
                        "error_code": "validation_error",
                        "error_message": "Candidate validation failed before a result could be saved.",
                    },
                )
            except Exception:
                logger.exception("Failed to persist candidate validation failure for candidate_id=%s", candidate_id)
        cleanup_candidate_file(candidate or {"temp_file_path": temp_path})
        raise


def confirm_supporting_pdf_candidate(candidate_id: str, chatbot_id: int, company_id: int) -> dict:
    existing = get_candidate(candidate_id, chatbot_id, company_id)
    if not existing:
        raise CandidateStateError("candidate_not_found", "Candidate was not found.")
    if existing.get("validation_status") == "ingested_supporting":
        if document_storage.r2_enabled():
            cleanup_candidate_file(existing)
        return {
            "candidate_id": candidate_id,
            "validation_status": "ingested_supporting",
            "ingested_knowledge_file_id": existing.get("ingested_knowledge_file_id"),
            "message": "Candidate has already been ingested as Supporting knowledge.",
        }
    recovered = _recover_ingested_candidate(existing, chatbot_id, company_id)
    if recovered:
        return recovered
    if _is_expired(existing):
        mark_candidate_expired(candidate_id, chatbot_id, company_id)
        cleanup_candidate_file(existing)
        raise CandidateStateError("candidate_expired", "Candidate has expired.")
    _assert_current_primary_matches_candidate(existing, chatbot_id)
    can_upload_knowledge_file(company_id)
    can_upload_knowledge_storage(company_id, int(existing.get("file_size") or 0))

    claimed = claim_candidate_for_confirmation(candidate_id, chatbot_id, company_id, isoformat(utc_now()))
    if not claimed:
        current = get_candidate(candidate_id, chatbot_id, company_id)
        if current and current.get("validation_status") == "ingested_supporting":
            if document_storage.r2_enabled():
                cleanup_candidate_file(current)
            return {
                "candidate_id": candidate_id,
                "validation_status": "ingested_supporting",
                "ingested_knowledge_file_id": current.get("ingested_knowledge_file_id"),
                "message": "Candidate has already been ingested as Supporting knowledge.",
            }
        recovered = _recover_ingested_candidate(current or existing, chatbot_id, company_id)
        if recovered:
            return recovered
        raise CandidateStateError("candidate_not_confirmable", "Candidate is not in a confirmable passed state.")

    temp_path = claimed.get("temp_file_path")
    if temp_path and document_storage.r2_enabled():
        try:
            temp_path = document_storage.materialize_file(temp_path, root=DATA_FOLDER, namespace="knowledge")
        except FileNotFoundError:
            mark_candidate_ingest_failed(candidate_id, chatbot_id, company_id, "candidate_file_missing", "Candidate file is missing.")
            raise CandidateStateError("candidate_file_missing", "Candidate file is missing.") from None
        except document_storage.DocumentStorageError:
            mark_candidate_ingest_failed(
                candidate_id, chatbot_id, company_id,
                "candidate_storage_unavailable", "Candidate storage is temporarily unavailable.",
            )
            raise
    if not temp_path or not os.path.exists(temp_path):
        mark_candidate_ingest_failed(candidate_id, chatbot_id, company_id, "candidate_file_missing", "Candidate file is missing.")
        raise CandidateStateError("candidate_file_missing", "Candidate file is missing.")

    ingestion_recorded = False
    try:
        upload = _StoredCandidateUpload(temp_path, claimed.get("safe_file_name") or claimed.get("original_file_name") or "candidate.pdf")
        ingest_result = save_uploaded_pdf(
            upload,
            chatbot_id,
            target_role="supporting",
            source_pdf_candidate_id=candidate_id,
        )
        if ingest_result.get("status") != "completed":
            raise RuntimeError(ingest_result.get("message") or "Supporting PDF ingestion failed.")
        ingested_file_id = ingest_result.get("file_id")
        if not ingested_file_id:
            raise RuntimeError("Supporting PDF ingestion did not return a knowledge file id.")
        updated = mark_candidate_ingested(candidate_id, chatbot_id, company_id, ingested_file_id)
        if not updated:
            raise RuntimeError("Candidate was not in confirming state when marking ingestion complete.")
        ingestion_recorded = True
        cleanup_candidate_file(claimed)
        return {
            "candidate_id": candidate_id,
            "validation_status": "ingested_supporting",
            "ingested_knowledge_file_id": ingested_file_id,
            "knowledge_file": {
                "id": ingested_file_id,
                "role": "supporting",
                "is_active": False,
                "is_enabled": True,
                "file_name": ingest_result.get("file_name"),
            },
            "message": ingest_result.get("message"),
            "candidate": updated or claimed,
        }
    except Exception as exc:
        logger.error("Supporting candidate ingestion failed for candidate_id=%s (%s)", candidate_id, type(exc).__name__)
        if not ingestion_recorded:
            mark_candidate_ingest_failed(candidate_id, chatbot_id, company_id, "ingest_failed", "Supporting PDF ingestion failed.")
        raise


def cancel_pdf_candidate(candidate_id: str, chatbot_id: int, company_id: int) -> dict:
    candidate = get_candidate(candidate_id, chatbot_id, company_id)
    if not candidate:
        raise CandidateStateError("candidate_not_found", "Candidate was not found.")
    if candidate.get("validation_status") == "ingested_supporting":
        if document_storage.r2_enabled():
            cleanup_candidate_file(candidate)
        return {"candidate_id": candidate_id, "validation_status": "ingested_supporting", "cancelled": False}
    if candidate.get("validation_status") == "confirming":
        raise CandidateStateError("candidate_confirmation_in_progress", "Candidate is currently being ingested and cannot be cancelled.")
    if candidate.get("validation_status") == "cancelled":
        cleanup_candidate_file(candidate)
        return {"candidate_id": candidate_id, "validation_status": "cancelled", "cancelled": True}
    updated = mark_candidate_cancelled(candidate_id, chatbot_id, company_id) or candidate
    if updated.get("validation_status") != "cancelled":
        raise CandidateStateError("candidate_not_cancellable", "Candidate is not in a cancellable state.")
    cleanup_candidate_file(updated)
    return {"candidate_id": candidate_id, "validation_status": "cancelled", "cancelled": True, "candidate": updated}


def _mark_validation_result_or_raise(candidate_id: str, chatbot_id: int, company_id: int, fields: dict) -> dict:
    updated = mark_candidate_validated(candidate_id, chatbot_id, company_id, fields)
    if not updated:
        raise CandidateStateError("candidate_state_conflict", "Candidate state changed before validation could be saved.")
    return updated


def _assert_current_primary_matches_candidate(candidate: dict, chatbot_id: int):
    current_primary = get_active_knowledge_file(chatbot_id)
    if not current_primary or not _is_pdf_primary(current_primary):
        raise _primary_changed_error()
    if current_primary.get("id") != candidate.get("primary_file_id"):
        raise _primary_changed_error()
    stored_hash = candidate.get("primary_content_sha256")
    if stored_hash:
        _texts, current_hash = _load_primary_snapshot(chatbot_id, current_primary)
        if current_hash != stored_hash:
            raise _primary_changed_error()


def _recover_ingested_candidate(candidate: dict | None, chatbot_id: int, company_id: int) -> dict | None:
    if not candidate:
        return None
    file_record = get_knowledge_file_by_source_candidate(chatbot_id, candidate.get("id"))
    if not file_record:
        return None
    ingested_file_id = file_record.get("id")
    if candidate.get("validation_status") == "ingested_supporting":
        persisted_candidate = candidate
    else:
        persisted_candidate = recover_candidate_ingested(candidate["id"], chatbot_id, company_id, ingested_file_id)
        if not persisted_candidate:
            reloaded = get_candidate(candidate["id"], chatbot_id, company_id)
            if reloaded and reloaded.get("validation_status") == "ingested_supporting":
                persisted_candidate = reloaded
            else:
                raise CandidateStateError(
                    "candidate_recovery_state_conflict",
                    "A Supporting knowledge file exists for this candidate, but the candidate state could not be finalized.",
                )
    cleanup_candidate_file(candidate)
    return {
        "candidate_id": persisted_candidate.get("id"),
        "validation_status": "ingested_supporting",
        "ingested_knowledge_file_id": ingested_file_id,
        "knowledge_file": {
            "id": ingested_file_id,
            "role": "supporting",
            "is_active": bool(file_record.get("is_active")),
            "is_enabled": file_record.get("is_enabled", True) is not False,
            "file_name": file_record.get("file_name"),
            "original_file_name": file_record.get("original_file_name"),
            "display_name": file_record.get("original_file_name") or file_record.get("file_name"),
        },
        "message": "Candidate has already been ingested as Supporting knowledge.",
        "candidate": persisted_candidate,
    }


def _is_expired(candidate: dict) -> bool:
    expires = parse_datetime(candidate.get("expires_at"))
    return bool(expires and expires <= utc_now())


def _metadata_payload(result: dict, extraction_summary: dict) -> dict:
    return {
        "candidate_summary": result.get("candidate_summary", ""),
        "primary_topic_summary": result.get("primary_topic_summary", ""),
        "matched_topics": result.get("matched_topics", []),
        "unrelated_topics": result.get("unrelated_topics", []),
        "reason": result.get("reason", ""),
        "suggestions": result.get("suggestions", []),
        "truncated": result.get("truncated", False),
        "features": result.get("features", {}),
        "extraction": extraction_summary,
    }


def _response_from_candidate(candidate: dict, result: dict, primary_file: dict) -> dict:
    metadata = candidate.get("result_metadata") or _metadata_payload(result, {})
    status = candidate.get("validation_status") or ("validated_passed" if result.get("passed") else "validated_failed")
    duplicate_status = candidate.get("duplicate_status") or result.get("duplicate_status") or "none"
    error_code = candidate.get("error_code") or (metadata.get("features") or {}).get("error_code")
    can_confirm = status == "validated_passed" and duplicate_status != "exact_content_duplicate"
    return {
        "candidate_id": candidate.get("id"),
        "validation_status": status,
        "relevance_score": float(candidate.get("relevance_score") if candidate.get("relevance_score") is not None else result.get("score", 0.0)),
        "threshold": float(candidate.get("threshold") if candidate.get("threshold") is not None else result.get("threshold", 0.0)),
        "passed": bool(candidate.get("passed", result.get("passed", False))),
        "candidate_filename": candidate.get("original_file_name"),
        "candidate_summary": metadata.get("candidate_summary", ""),
        "primary": {
            "id": primary_file.get("id"),
            "file_name": primary_file.get("file_name"),
        },
        "primary_topic_summary": metadata.get("primary_topic_summary", ""),
        "matched_topics": metadata.get("matched_topics", []),
        "unrelated_topics": metadata.get("unrelated_topics", []),
        "reason": metadata.get("reason") or result.get("reason", ""),
        "suggestions": metadata.get("suggestions", []),
        "error_code": error_code,
        "error_message": candidate.get("error_message"),
        "duplicate_status": duplicate_status,
        "truncated": bool(metadata.get("truncated", result.get("truncated", False))),
        "expires_at": candidate.get("expires_at"),
        "can_confirm": can_confirm,
    }
