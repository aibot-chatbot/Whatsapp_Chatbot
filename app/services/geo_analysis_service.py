"""Validation, deterministic measurement and orchestration for GEO analysis."""
from concurrent.futures import ThreadPoolExecutor
import math
import re
from urllib.parse import urlparse

from app.database import geo_repository
from app.services.geo_provider_service import collect


PLATFORMS = ("chatgpt", "gemini", "perplexity")
LANGUAGES = ("en", "ms", "zh")
FORMULA = "40% mention rate + 30% citation rate + 20% recommendation rate + 10% position prominence"
MAX_EXECUTIONS = 12


def _strings(value, name, *, maximum_items, maximum_length):
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError(f"{name} must be a list of at most {maximum_items} items.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > maximum_length:
            raise ValueError(f"Each {name} item must contain 1 to {maximum_length} characters.")
        clean = item.strip()
        if clean.casefold() not in {existing.casefold() for existing in result}:
            result.append(clean)
    return result


def _normalise_domain(value):
    candidate = value.strip().lower()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def validate_spec(value, entitlement=None):
    if not isinstance(value, dict):
        raise ValueError("A JSON request body is required.")
    allowed = {"brand_name", "aliases", "competitors", "owned_domains", "country", "language",
               "platforms", "prompts", "samples_per_prompt"}
    if set(value) - allowed:
        raise ValueError("Invalid GEO analysis fields.")
    brand = str(value.get("brand_name") or "").strip()
    if not 1 <= len(brand) <= 120:
        raise ValueError("Brand name must contain 1 to 120 characters.")
    aliases = _strings(value.get("aliases") or [], "aliases", maximum_items=20, maximum_length=120)
    if brand.casefold() not in {item.casefold() for item in aliases}:
        aliases.insert(0, brand)
    competitors = _strings(value.get("competitors") or [], "competitors", maximum_items=20, maximum_length=120)
    raw_domains = _strings(value.get("owned_domains") or [], "owned domains", maximum_items=20, maximum_length=253)
    domains = []
    for raw in raw_domains:
        domain = _normalise_domain(raw)
        if not domain or "." not in domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise ValueError("Enter valid owned domains, such as example.com.")
        if domain not in domains:
            domains.append(domain)
    prompt_limit = (entitlement or {}).get("prompts_per_analysis", 10)
    prompts = _strings(value.get("prompts") or [], "prompts", maximum_items=prompt_limit, maximum_length=500)
    if not prompts:
        raise ValueError("Add at least one prompt.")
    platforms = _strings(value.get("platforms") or [], "platforms", maximum_items=3, maximum_length=20)
    if not platforms or any(item not in PLATFORMS for item in platforms):
        raise ValueError("Choose at least one supported GEO platform.")
    allowed_platforms = set((entitlement or {}).get("platforms") or PLATFORMS)
    denied_platforms = [item for item in platforms if item not in allowed_platforms]
    if denied_platforms:
        raise ValueError("One or more selected GEO platforms are not included in your plan.")
    country = str(value.get("country") or "MY").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("Country must be a two-letter ISO code.")
    language = str(value.get("language") or "en").strip().lower()
    if language not in LANGUAGES:
        raise ValueError("Language must be English, Bahasa Melayu or Chinese.")
    samples = value.get("samples_per_prompt", 1)
    sample_limit = (entitlement or {}).get("samples_per_prompt", 3)
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= sample_limit:
        raise ValueError(f"Your plan allows {sample_limit} sample per prompt.")
    execution_limit = min(MAX_EXECUTIONS, (entitlement or {}).get("executions_per_analysis", MAX_EXECUTIONS))
    if len(prompts) * len(platforms) * samples > execution_limit:
        raise ValueError(f"A single analysis may run at most {execution_limit} provider executions.")
    return {"brand_name": brand, "aliases": aliases, "competitors": competitors,
            "owned_domains": domains, "country": country, "language": language,
            "platforms": platforms, "prompts": prompts, "samples_per_prompt": samples}


def count_mentions(text, names):
    ranges = []
    for name in names:
        for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text, flags=re.IGNORECASE):
            ranges.append((match.start(), match.end()))
    accepted = []
    for start, end in sorted(ranges, key=lambda item: (item[0], -(item[1] - item[0]))):
        if not any(start < saved_end and end > saved_start for saved_start, saved_end in accepted):
            accepted.append((start, end))
    return len(accepted)


def _owned(domain, owned_domains):
    clean = _normalise_domain(domain or "")
    return any(clean == owned or clean.endswith("." + owned) for owned in owned_domains)


def _recommendation_position(text, aliases):
    position = 0
    for line in (item.strip() for item in text.splitlines() if item.strip()):
        listed = bool(re.match(r"^(?:[-*•]|\d+[.)])\s+", line))
        if listed:
            position += 1
        mentions = count_mentions(line, aliases) > 0
        recommendation = bool(re.search(r"\b(best|recommend(?:ed|ation)?|top|choose|consider|ideal)\b|推荐|首选|terbaik|disyorkan", line, re.I))
        if mentions and (listed or recommendation):
            return position or 1
    return None


def _sentiment(text, aliases):
    relevant = " ".join(sentence for sentence in re.split(r"(?<=[.!?。！？])\s+", text)
                        if count_mentions(sentence, aliases) > 0).casefold()
    if not relevant:
        return "neutral"
    positive = ("best", "recommended", "leading", "trusted", "excellent", "strong", "popular", "可靠", "推荐", "优秀", "terbaik", "disyorkan")
    negative = ("avoid", "poor", "weak", "problem", "complaint", "expensive", "差", "问题", "不推荐", "lemah", "masalah")
    positive_hits = sum(word in relevant for word in positive)
    negative_hits = sum(word in relevant for word in negative)
    return "positive" if positive_hits > negative_hits else "negative" if negative_hits > positive_hits else "neutral"


def enrich(result, spec, *, prompt, prompt_index, sample_index):
    text = result.get("raw_response") or ""
    successful = result.get("request_status") == "complete"
    brand_mentions = count_mentions(text, spec["aliases"]) if successful else 0
    competitor_mentions = {name: count_mentions(text, [name]) if successful else 0
                           for name in spec["competitors"]}
    owned_citations = sum(_owned(item.get("domain") or item.get("url"), spec["owned_domains"])
                          for item in result.get("citations") or [])
    return {**result, "prompt": prompt, "prompt_index": prompt_index, "sample_index": sample_index,
            "country": spec["country"], "language": spec["language"],
            "brand_mentioned": brand_mentions > 0, "brand_mention_count": brand_mentions,
            "competitor_mentions": competitor_mentions, "owned_citation_count": owned_citations,
            "recommendation_position": _recommendation_position(text, spec["aliases"]) if successful else None,
            "sentiment": _sentiment(text, spec["aliases"]) if successful else "neutral"}


def calculate_metrics(executions, prompt_count=None):
    successful = [row for row in executions if row.get("request_status") == "complete"]
    denominator = len(successful) or 1
    mentioned = [row for row in successful if row.get("brand_mentioned")]
    cited = [row for row in successful if row.get("citations")]
    owned_cited = [row for row in successful if (row.get("owned_citation_count") or 0) > 0]
    recommended = [row for row in successful if row.get("recommendation_position") is not None]
    mention_rate = len(mentioned) / denominator * 100
    citation_rate = len(cited) / denominator * 100
    owned_citation_rate = len(owned_cited) / denominator * 100
    recommendation_rate = len(recommended) / denominator * 100
    positions = [row["recommendation_position"] for row in recommended]
    average_position = sum(positions) / len(positions) if positions else 0
    citation_positions = [citation.get("citation_position") or citation.get("position")
                          for row in successful for citation in (row.get("citations") or [])
                          if citation.get("citation_position") or citation.get("position")]
    average_citation_position = (sum(citation_positions) / len(citation_positions)
                                 if citation_positions else 0)
    prominence = max(0, 100 - (average_position - 1) * 20) if positions else 0
    sentiment_counts = {name: sum(row["sentiment"] == name for row in mentioned)
                        for name in ("positive", "neutral", "negative")}
    sentiment_values = [{"positive": 100, "neutral": 50, "negative": 0}[row["sentiment"]] for row in mentioned]
    sentiment_score = sum(sentiment_values) / len(sentiment_values) if sentiment_values else 50
    competitor_total = sum(sum((row.get("competitor_mentions") or {}).values()) for row in successful)
    brand_total = sum(row.get("brand_mention_count") or 0 for row in successful)
    voice_total = brand_total + competitor_total
    covered_prompts = len({row["prompt_index"] for row in successful})
    total_prompts = prompt_count if prompt_count is not None else len({row["prompt_index"] for row in executions})
    proportion = len(mentioned) / denominator
    if successful:
        z = 1.96
        adjustment = z * z / len(successful)
        centre = (proportion + adjustment / 2) / (1 + adjustment)
        half_width = (z * math.sqrt(
            proportion * (1 - proportion) / len(successful) + adjustment / (4 * len(successful))
        ) / (1 + adjustment))
        interval = {"lower": round(max(0, centre - half_width) * 100, 2),
                    "upper": round(min(1, centre + half_width) * 100, 2)}
        margin = half_width * 100
    else:
        interval = {"lower": 0, "upper": 100}
        margin = 100
    platform_summary = {}
    for platform in PLATFORMS:
        platform_rows = [row for row in executions if row.get("platform") == platform]
        if not platform_rows:
            continue
        platform_success = [row for row in platform_rows if row.get("request_status") == "complete"]
        platform_denominator = len(platform_success) or 1
        platform_summary[platform] = {
            "samples": len(platform_rows),
            "successful_samples": len(platform_success),
            "mention_rate": round(sum(bool(row.get("brand_mentioned")) for row in platform_success) / platform_denominator * 100, 2),
            "citation_rate": round(sum(bool(row.get("citations")) for row in platform_success) / platform_denominator * 100, 2),
            "owned_citation_rate": round(sum((row.get("owned_citation_count") or 0) > 0 for row in platform_success) / platform_denominator * 100, 2),
            "recommendation_rate": round(sum(row.get("recommendation_position") is not None for row in platform_success) / platform_denominator * 100, 2),
        }
    cited_domains = {}
    for row in successful:
        for citation in row.get("citations") or []:
            domain = _normalise_domain(citation.get("domain") or citation.get("url") or "")
            if domain:
                cited_domains[domain] = cited_domains.get(domain, 0) + 1
    top_cited_domains = [{"domain": domain, "citations": count}
                         for domain, count in sorted(cited_domains.items(), key=lambda item: (-item[1], item[0]))[:8]]
    score_breakdown = {
        "mention": {"rate": round(mention_rate, 2), "weight": 40, "points": round(mention_rate * .4, 2)},
        "citation": {"rate": round(citation_rate, 2), "weight": 30, "points": round(citation_rate * .3, 2)},
        "recommendation": {"rate": round(recommendation_rate, 2), "weight": 20, "points": round(recommendation_rate * .2, 2)},
        "position": {"rate": round(prominence, 2), "weight": 10, "points": round(prominence * .1, 2)},
    }
    return {"geo_score": round(sum(item["points"] for item in score_breakdown.values()), 2),
            "mention_rate": round(mention_rate, 2), "citation_rate": round(citation_rate, 2),
            "owned_citation_rate": round(owned_citation_rate, 2),
            "recommendation_rate": round(recommendation_rate, 2),
            "average_recommendation_position": round(average_position, 2),
            "average_citation_position": round(average_citation_position, 2),
            "position_prominence": round(prominence, 2),
            "sentiment_score": round(sentiment_score, 2),
            "sentiment_distribution": sentiment_counts,
            "share_of_voice": round(brand_total / voice_total * 100, 2) if voice_total else 0,
            "prompt_coverage": round(covered_prompts / max(total_prompts, 1) * 100, 2),
            "sample_size": len(executions), "successful_samples": len(successful),
            "confidence_level": 95, "mention_rate_margin_of_error": round(margin, 2),
            "mention_rate_confidence_interval": interval,
            "platform_summary": platform_summary,
            "top_cited_domains": top_cited_domains,
            "score_breakdown": score_breakdown}


def _finding_evidence(row):
    evidence = {"prompt": row.get("prompt"), "platform": row.get("platform")}
    domains = sorted({_normalise_domain(item.get("domain") or item.get("url") or "")
                      for item in (row.get("citations") or [])} - {""})
    if domains:
        evidence["domains"] = domains[:3]
    return evidence


def build_findings(executions, spec=None):
    """Generate evidence-backed improvement actions without another LLM call."""
    successful = [row for row in executions if row.get("request_status") == "complete"]
    owned_domains = (spec or {}).get("owned_domains") or []
    findings = []
    gaps = [row for row in successful if not row.get("brand_mentioned")]
    if gaps:
        example_prompt = gaps[0].get("prompt") or "the missed buyer question"
        findings.append({
            "type": "visibility_gap", "priority": "high", "metric": "Mention rate",
            "title": "Build an answer for missed buyer questions",
            "summary": f"The brand was absent in {len(gaps)} of {len(successful)} successful checks.",
            "actions": [
                f"Create or update one crawlable page that directly answers: {example_prompt}",
                "Name the brand and relevant product in the opening answer, then support the claim with verifiable facts, examples and first-party evidence.",
                "Match the page title, H1 and internal-link anchor text to the buyer topic, then rerun this same prompt after the page is indexed.",
            ],
            "evidence": [_finding_evidence(row) for row in gaps[:5]],
        })
    citation_gaps = [row for row in successful if not row.get("citations")]
    if citation_gaps:
        findings.append({
            "type": "citation_gap", "priority": "high", "metric": "Citation rate",
            "title": "Give AI search a source it can cite",
            "summary": f"{len(citation_gaps)} of {len(successful)} successful checks returned no source citation.",
            "actions": [
                "Publish a factual source page for the missed topic with a direct answer, named author or organization, visible update date and links to primary evidence.",
                "Keep the page indexable: return HTTP 200, avoid noindex, use a self-referencing canonical URL and expose the page through internal navigation.",
                "Add accurate Organization plus Product or Service structured data; use FAQ markup only when the same questions and answers are visible on the page.",
            ],
            "evidence": [_finding_evidence(row) for row in citation_gaps[:5]],
        })
    if owned_domains:
        owned_gaps = [row for row in successful if row.get("brand_mentioned") and not row.get("owned_citation_count")]
        if owned_gaps:
            findings.append({
                "type": "owned_source_gap", "priority": "medium", "metric": "Owned source rate",
                "title": "Turn brand mentions into owned-source citations",
                "summary": f"{len(owned_gaps)} brand-mentioned checks did not cite {', '.join(owned_domains[:2])}.",
                "actions": [
                    "Strengthen the closest owned page with a concise answer, comparison criteria, proof points and links to supporting first-party data.",
                    "Use a descriptive title and H1, connect the page from relevant product and resource pages, and keep key facts in crawlable HTML.",
                    "Rerun the exact prompts below after indexing and compare owned source rate separately from overall citation rate.",
                ],
                "evidence": [_finding_evidence(row) for row in owned_gaps[:5]],
            })
    else:
        findings.append({
            "type": "owned_domain_setup", "priority": "setup", "metric": "Owned source rate",
            "title": "Add your website domain for owned-source tracking",
            "summary": "No owned domain was supplied, so the system cannot identify citations belonging to your business. This does not reduce the GEO score.",
            "actions": ["Add the main company domain under Your website domains on the next run; do not include paths or tracking parameters."],
            "evidence": [],
        })
    competitor_gaps = []
    for row in successful:
        leaders = [name for name, count in (row.get("competitor_mentions") or {}).items()
                   if count > (row.get("brand_mention_count") or 0)]
        if leaders:
            evidence = _finding_evidence(row)
            evidence["competitors"] = leaders[:3]
            competitor_gaps.append(evidence)
    if competitor_gaps:
        leaders = sorted({name for row in competitor_gaps for name in row.get("competitors", [])})
        findings.append({
            "type": "competitor_gap", "priority": "high", "metric": "Share of voice",
            "title": "Close the competitor evidence gap",
            "summary": f"{', '.join(leaders[:3])} received more exact-name mentions in {len(competitor_gaps)} checks.",
            "actions": [
                "Publish a fair comparison page for the evidenced buyer question using verifiable criteria, prices or capabilities instead of unsupported superiority claims.",
                "Add proof the competing answers can reuse: customer outcomes, product documentation, market coverage and dated case studies.",
                "Seek accurate inclusion on the independent sources already cited for these prompts, then measure the same prompt set again.",
            ],
            "evidence": competitor_gaps[:5],
        })
    cited_domains = {}
    for row in successful:
        for citation in row.get("citations") or []:
            domain = _normalise_domain(citation.get("domain") or citation.get("url") or "")
            if domain and not _owned(domain, owned_domains):
                cited_domains[domain] = cited_domains.get(domain, 0) + 1
    if cited_domains:
        sources = [domain for domain, _ in sorted(cited_domains.items(), key=lambda item: (-item[1], item[0]))[:3]]
        findings.append({
            "type": "source_opportunity", "priority": "medium", "metric": "Citation rate",
            "title": "Earn coverage from sources AI already uses",
            "summary": f"The measured answers cited {', '.join(sources)} most often outside your owned domains.",
            "actions": [
                "Review the cited pages to identify the format and facts used for this topic before creating new content.",
                "Where editorially appropriate, update your listing or profile, contribute verifiable data, or pitch a useful resource to these publishers.",
                "Track whether future answers cite the source and mention your brand; coverage is an opportunity, not a guaranteed ranking change.",
            ],
            "evidence": [{"domains": sources}],
        })
    failures = [row for row in executions if row.get("request_status") != "complete"]
    if failures:
        findings.append({
            "type": "collection_gap", "priority": "setup", "metric": "Evidence coverage",
            "title": "Restore missing platform evidence",
            "summary": f"{len(failures)} provider checks failed and were excluded from rate denominators.",
            "actions": [
                "Fix the provider configuration or billing error shown in the raw evidence, then rerun the same prompt set.",
                "Do not compare this score with a full three-platform run until the missing checks complete.",
            ],
            "evidence": [{**_finding_evidence(row), "error_code": row.get("error_code")} for row in failures[:5]],
        })
    if successful and not any(item["priority"] in {"high", "medium"} for item in findings):
        findings.append({
            "type": "protect_visibility", "priority": "medium", "metric": "All scored metrics",
            "title": "Protect the visibility already measured",
            "summary": "This small sample has no deterministic visibility, citation or competitor gap.",
            "actions": [
                "Keep the cited pages accurate and available, record today as the baseline, and rerun the same prompts on a consistent schedule.",
                "Treat a repeated change across multiple runs as stronger evidence than one score movement.",
            ],
            "evidence": [_finding_evidence(row) for row in successful[:3]],
        })
    return findings


def run_analysis(company_id, actor_user_id, payload, entitlement):
    spec = validate_spec(payload, entitlement)
    analysis = geo_repository.create_analysis(company_id, actor_user_id, spec, entitlement)
    stored = []
    try:
        tasks = [(prompt_index, prompt, platform, sample_index)
                 for prompt_index, prompt in enumerate(spec["prompts"])
                 for platform in spec["platforms"]
                 for sample_index in range(spec["samples_per_prompt"])]
        # Provider calls are independent and bounded by MAX_EXECUTIONS. Persist
        # sequentially afterwards because the shared Supabase client is not a
        # transaction boundary and should not be mutated concurrently.
        def execute(task):
            prompt_index, prompt, platform, sample_index = task
            return enrich(collect(platform, prompt, spec["country"], spec["language"]), spec,
                          prompt=prompt, prompt_index=prompt_index, sample_index=sample_index)

        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            collected = list(pool.map(execute, tasks))
        for execution in collected:
            stored.append(geo_repository.add_execution(company_id, analysis["id"], execution))
        metrics = calculate_metrics(stored, len(spec["prompts"]))
        metrics["findings"] = build_findings(stored, spec)
        successful = metrics["successful_samples"]
        status = "complete" if successful == len(stored) else "partial" if successful else "failed"
        methodology = {"version": "deterministic-v3", "formula": FORMULA,
                       "sentiment_affects_score": False,
                       "measurement_unit": "One provider check is one prompt sent to one AI-search platform.",
                       "notes": "Failed executions are excluded from rate denominators and remain visible as evidence. Any native provider citation contributes to citation rate; owned citations are reported separately. Recommendations are evidence-linked actions, not guaranteed ranking changes."}
        geo_repository.finish_analysis(company_id, analysis["id"], status=status, metrics=metrics,
                                       methodology=methodology,
                                       error_code="all_providers_failed" if not successful else None)
    except Exception:
        try:
            geo_repository.finish_analysis(company_id, analysis["id"], status="failed", metrics={},
                                           methodology={"version": "deterministic-v3", "formula": FORMULA},
                                           error_code="analysis_interrupted")
        except Exception:
            pass
        raise
    return geo_repository.get_analysis(company_id, analysis["id"])
