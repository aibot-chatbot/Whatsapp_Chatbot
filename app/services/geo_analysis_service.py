"""Validation, deterministic measurement and orchestration for GEO analysis."""
from concurrent.futures import ThreadPoolExecutor
import math
import re
from urllib.parse import urlparse

from app.database import geo_repository
from app.services.geo_provider_service import collect


PLATFORMS = ("chatgpt", "gemini", "claude", "deepseek", "perplexity")
PLATFORM_LABELS = {
    "chatgpt": "ChatGPT Search", "gemini": "Gemini", "claude": "Claude",
    "deepseek": "DeepSeek", "perplexity": "Perplexity",
}
LANGUAGES = ("en", "ms", "zh")
FORMULA = "60% mention rate + 40% mention-rank prominence"
MAX_EXECUTIONS = 20
MIN_RELIABLE_SAMPLES = 3
ROLLING_ANALYSIS_LIMIT = 5
BRAND_DISCOVERY_LIST_SIZE = 30


def _measurement_prompt(prompt):
    """Ask once for broad, rankable brand evidence without biasing the answer."""
    return (
        f"Buyer question: {prompt}\n\n"
        "GEO measurement format:\n"
        f"- Use current web evidence and return a numbered ranking of up to "
        f"{BRAND_DISCOVERY_LIST_SIZE} distinct brands, providers, or products that directly answer "
        "the buyer question in the target market.\n"
        f"- Include {BRAND_DISCOVERY_LIST_SIZE} options when that many credible choices are supported; "
        "otherwise include every credible option you can verify and do not invent entries.\n"
        "- Put exactly one brand per numbered item, write the brand name first, and add one concise "
        "evidence-based reason of no more than 12 words.\n"
        "- Rank by relevance and strength of evidence, not alphabetically. Do not shorten the list "
        "to only two or three brands when more credible choices exist.\n"
        "- Answer independently. Do not favor or add any brand merely because it may be measured.\n"
        "- Cite the sources used."
    )


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
    platforms = _strings(value.get("platforms") or [], "platforms", maximum_items=len(PLATFORMS), maximum_length=32)
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
    if isinstance(samples, bool) or not isinstance(samples, int) or samples != 1:
        raise ValueError("GEO analysis runs exactly one provider check per question and platform.")
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


def _first_mention_offset(text, names):
    offsets = [match.start() for name in names
               for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", text, flags=re.IGNORECASE)]
    return min(offsets) if offsets else None


def _listed_mention_rank(text, aliases):
    """Return the brand's position in an explicit numbered or bulleted result list."""
    ordinal = 0
    for line in text.splitlines():
        candidate = re.sub(r"^\s*(?:>\s*)?(?:#{1,6}\s*)?(?:\*\*|__)?", "", line)
        match = re.match(r"(?:(?P<number>\d{1,2})[.)]|(?P<bullet>[-*•]))\s+(?P<body>.+)", candidate)
        if not match:
            continue
        ordinal += 1
        if count_mentions(match.group("body"), aliases):
            number = int(match.group("number")) if match.group("number") else ordinal
            return number if 1 <= number <= 50 else None
    return None


def _mention_rank_details(text, aliases, competitors):
    listed_rank = _listed_mention_rank(text, aliases)
    if listed_rank is not None:
        return listed_rank, "explicit_result_list"
    brand_offset = _first_mention_offset(text, aliases)
    if brand_offset is None:
        return None, "brand_not_mentioned"
    competitor_offsets = [_first_mention_offset(text, [name]) for name in competitors]
    detected = [offset for offset in competitor_offsets if offset is not None]
    if not detected:
        return None, "mention_without_rank_evidence"
    return 1 + sum(offset < brand_offset for offset in detected), "tracked_entity_order"


def _mention_rank(text, aliases, competitors):
    """Return a defensible answer rank, or None when the answer is not ranked."""
    return _mention_rank_details(text, aliases, competitors)[0]


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
    mention_rank, rank_method = (_mention_rank_details(text, spec["aliases"], spec["competitors"])
                                 if successful else (None, "request_failed"))
    provider_metadata = {**(result.get("provider_metadata") or {}),
                         "mention_rank_method": rank_method}
    return {**result, "prompt": prompt, "prompt_index": prompt_index, "sample_index": sample_index,
            "country": spec["country"], "language": spec["language"],
            "brand_mentioned": brand_mentions > 0, "brand_mention_count": brand_mentions,
            "competitor_mentions": competitor_mentions, "owned_citation_count": owned_citations,
            # The legacy column name is retained in storage for compatibility;
            # deterministic-v5 treats it as the brand's mention rank.
            "recommendation_position": mention_rank, "provider_metadata": provider_metadata,
            "sentiment": _sentiment(text, spec["aliases"]) if successful else "neutral"}


def _mention_metrics(rows):
    successful = [row for row in rows if row.get("request_status") == "complete"]
    mentioned = [row for row in successful if row.get("brand_mentioned")]
    ranks = [row["recommendation_position"] for row in mentioned
             if row.get("recommendation_position") is not None]
    mention_rate = len(mentioned) / len(successful) * 100 if successful else 0
    average_rank = sum(ranks) / len(ranks) if ranks else 0
    rank_prominence = max(0, 100 - (average_rank - 1) * 20) if ranks else 0
    score = mention_rate * .6 + rank_prominence * .4
    return {
        "score": round(score, 2),
        "mention_rate": round(mention_rate, 2),
        "average_mention_rank": round(average_rank, 2) if ranks else None,
        "mention_rank_prominence": round(rank_prominence, 2),
        "samples": len(rows),
        "successful_samples": len(successful),
        "mentioned_samples": len(mentioned),
        "ranked_samples": len(ranks),
        "sample_quality": "sufficient" if len(successful) >= MIN_RELIABLE_SAMPLES else "insufficient",
        "minimum_reliable_samples": MIN_RELIABLE_SAMPLES,
    }


def _combine_metric_snapshots(snapshots):
    successful = sum(int(item.get("successful_samples") or 0) for item in snapshots)
    mentioned = sum(int(item.get("mentioned_samples") or 0) for item in snapshots)
    samples = sum(int(item.get("samples") or 0) for item in snapshots)
    ranked = 0
    rank_total = 0.0
    for item in snapshots:
        average_rank = item.get("average_mention_rank")
        ranked_count = int(item.get("ranked_samples") or (
            item.get("mentioned_samples") if average_rank is not None else 0
        ) or 0)
        if average_rank is not None and ranked_count:
            ranked += ranked_count
            rank_total += float(average_rank) * ranked_count
    mention_rate = mentioned / successful * 100 if successful else 0
    average_rank = rank_total / ranked if ranked else None
    rank_prominence = max(0, 100 - (average_rank - 1) * 20) if average_rank is not None else 0
    return {
        "score": round(mention_rate * .6 + rank_prominence * .4, 2),
        "mention_rate": round(mention_rate, 2),
        "average_mention_rank": round(average_rank, 2) if average_rank is not None else None,
        "mention_rank_prominence": round(rank_prominence, 2),
        "samples": samples,
        "successful_samples": successful,
        "mentioned_samples": mentioned,
        "ranked_samples": ranked,
        "sample_quality": "sufficient" if successful >= MIN_RELIABLE_SAMPLES else "insufficient",
        "minimum_reliable_samples": MIN_RELIABLE_SAMPLES,
    }


def calculate_rolling_summary(current_metrics, prior_analyses, spec, *, current_analysis_id=None):
    """Combine the current run with up to four comparable historical analyses."""
    comparable = []
    brand = spec["brand_name"].casefold()
    for analysis in prior_analyses or []:
        if str(analysis.get("id")) == str(current_analysis_id):
            continue
        if str(analysis.get("brand_name") or "").casefold() != brand:
            continue
        if analysis.get("country") != spec["country"] or analysis.get("language") != spec["language"]:
            continue
        metrics = analysis.get("metrics") or {}
        if metrics.get("platform_summary"):
            comparable.append(metrics)
        if len(comparable) >= ROLLING_ANALYSIS_LIMIT - 1:
            break
    snapshots = [current_metrics, *comparable]
    platforms = {}
    for platform in PLATFORMS:
        values = [item.get("platform_summary", {}).get(platform) for item in snapshots]
        values = [item for item in values if item]
        if values:
            platforms[platform] = {**_combine_metric_snapshots(values), "analysis_count": len(values)}
    overall_values = []
    overall_analysis_count = 0
    for item in snapshots:
        platform_values = [item.get("platform_summary", {}).get(platform)
                           for platform in spec.get("platforms", PLATFORMS)]
        platform_values = [value for value in platform_values if value]
        if platform_values:
            overall_values.extend(platform_values)
            overall_analysis_count += 1
    return {
        "window_size": ROLLING_ANALYSIS_LIMIT,
        "analysis_count": overall_analysis_count,
        "minimum_reliable_samples": MIN_RELIABLE_SAMPLES,
        "overall": {**_combine_metric_snapshots(overall_values),
                    "analysis_count": overall_analysis_count},
        "platform_summary": platforms,
    }


def calculate_metrics(executions, prompt_count=None):
    del prompt_count  # Retained in the public function signature for stored-run compatibility.
    successful = [row for row in executions if row.get("request_status") == "complete"]
    mentioned = [row for row in successful if row.get("brand_mentioned")]
    overall = _mention_metrics(executions)
    proportion = len(mentioned) / len(successful) if successful else 0
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
        platform_summary[platform] = _mention_metrics(platform_rows)
    score_breakdown = {
        "mention": {"rate": overall["mention_rate"], "weight": 60,
                    "points": round(overall["mention_rate"] * .6, 2)},
        "mention_rank": {"rate": overall["mention_rank_prominence"], "weight": 40,
                         "points": round(overall["mention_rank_prominence"] * .4, 2)},
    }
    return {"geo_score": overall["score"],
            "mention_rate": overall["mention_rate"],
            "average_mention_rank": overall["average_mention_rank"],
            "mention_rank_prominence": overall["mention_rank_prominence"],
            "sample_size": len(executions), "successful_samples": len(successful),
            "mentioned_samples": overall["mentioned_samples"],
            "ranked_samples": overall["ranked_samples"],
            "sample_quality": overall["sample_quality"],
            "minimum_reliable_samples": MIN_RELIABLE_SAMPLES,
            "confidence_level": 95, "mention_rate_margin_of_error": round(margin, 2),
            "mention_rate_confidence_interval": interval,
            "platform_summary": platform_summary,
            "score_breakdown": score_breakdown}


def _finding_evidence(row):
    evidence = {"prompt": row.get("prompt"), "platform": row.get("platform")}
    domains = sorted({_normalise_domain(item.get("domain") or item.get("url") or "")
                      for item in (row.get("citations") or [])} - {""})
    if domains:
        evidence["domains"] = domains[:3]
    return evidence


def build_findings(executions, spec=None):
    """Return one evidence-linked four-pillar improvement plan per platform."""
    findings = []
    publishing_channels = {
        "chatgpt": "LinkedIn, Medium, relevant Reddit communities and reputable Malaysian industry publications",
        "gemini": "Google Business Profile posts, YouTube, LinkedIn and reputable Malaysian directories",
        "claude": "LinkedIn, Medium, product documentation hubs and respected industry publications",
        "deepseek": "LinkedIn, relevant Bahasa Melayu or Chinese business communities and regional industry directories",
        "perplexity": "LinkedIn, Medium, relevant Reddit communities and independent comparison or editorial sites",
    }
    for platform in PLATFORMS:
        rows = [row for row in executions if row.get("platform") == platform]
        if not rows:
            continue
        successful = [row for row in rows if row.get("request_status") == "complete"]
        label = PLATFORM_LABELS[platform]
        if not successful:
            findings.append({
                "type": "platform_unavailable", "platform": platform, "priority": "setup",
                "metric": "Mention rate · Mention rank", "title": f"Restore {label} measurement",
                "title_key": "geo.finding.restore.title", "title_params": {"platform": label},
                "summary": "No completed answer is available, so mention performance cannot be measured.",
                "summary_key": "geo.finding.restore.summary", "summary_params": {},
                "actions": [
                    "Fix the provider API key, billing or model-access error shown in the response details.",
                    "Rerun the same prompts before comparing this platform with other platforms.",
                ],
                "action_pillars": [
                    {"key": "provider_setup", "title": "Provider setup",
                     "title_key": "geo.pillar.provider_setup",
                     "action": "Fix the provider API key, billing or model-access error shown in the response details.",
                     "message_key": "geo.action.provider_setup", "params": {}},
                    {"key": "rerun", "title": "Verify measurement",
                     "title_key": "geo.pillar.rerun",
                     "action": "Rerun the same prompts before comparing this platform with other platforms.",
                     "message_key": "geo.action.rerun", "params": {}},
                ],
                "evidence": [{**_finding_evidence(row), "error_code": row.get("error_code")} for row in rows[:3]],
            })
            continue
        values = _mention_metrics(rows)
        gaps = [row for row in successful if not row.get("brand_mentioned")]
        example = (gaps[0] if gaps else successful[0]).get("prompt") or "the measured buyer question"
        leaders = sorted({name for row in successful for name, count in
                          (row.get("competitor_mentions") or {}).items() if count})
        priority = "high" if values["mention_rate"] < 50 else "medium" if (
            values["mention_rate"] < 100 or (values["average_mention_rank"] or 99) > 1
        ) else "low"
        competitor_context = ", ".join(leaders[:3]) if leaders else "the alternatives buyers already compare"
        pillars = [
            {"key": "website", "title": "Website / landing page",
             "title_key": "geo.pillar.website", "message_key": "geo.action.website",
             "params": {"prompt": example, "competitors": competitor_context},
             "action": (f"Build or improve a fast, focused website or landing page that directly answers “{example}”. "
                        f"State the brand, category, offer, verified proof and a factual comparison with {competitor_context} near the top.")},
            {"key": "authority_posts", "title": "Articles on trusted platforms",
             "title_key": "geo.pillar.authority_posts", "message_key": "geo.action.authority_posts",
             "params": {"channels": publishing_channels[platform], "prompt": example},
             "action": (f"Publish useful, original articles or posts about “{example}” on {publishing_channels[platform]}. "
                        "Keep the business name, category and claims consistent and link to the strongest relevant page.")},
            {"key": "local_context", "title": "Local landmarks and context",
             "title_key": "geo.pillar.local_context", "message_key": "geo.action.local_context",
             "params": {"country": spec.get("country", "MY") if spec else "MY"},
             "action": ("Add genuine local context: service areas, nearby landmarks, neighbourhood or city names, MYR pricing, "
                        "local contact details and verified Malaysian customer proof. Never invent a landmark, address or review.")},
            {"key": "crawler_technical", "title": "Technical fixes for AI crawlers",
             "title_key": "geo.pillar.crawler_technical", "message_key": "geo.action.crawler_technical",
             "params": {},
             "action": ("Keep important content in crawlable HTML; provide accurate titles, descriptions, canonical URLs, internal links, "
                        "sitemap.xml and truthful structured data. Check robots rules, mobile speed and server errors so relevant search and AI crawlers are not accidentally blocked.")},
        ]
        actions = [pillar["action"] for pillar in pillars]
        if values["sample_quality"] == "insufficient":
            priority = "observe"
        rank_text = (f"#{values['average_mention_rank']:g}"
                     if values["average_mention_rank"] is not None else "not ranked")
        insufficient = values["sample_quality"] == "insufficient"
        confidence_text = "Directional only: insufficient sample. " if insufficient else ""
        summary_key = "geo.finding.summary"
        if values["average_mention_rank"] is None:
            summary_key += ".insufficient_unranked" if insufficient else ".unranked"
        elif insufficient:
            summary_key += ".insufficient"
        findings.append({
            "type": "platform_mention_plan", "platform": platform, "priority": priority,
            "metric": "Mention rate · Mention rank",
            "title": f"Improve AI mentions in {label}",
            "title_key": "geo.finding.title", "title_params": {"platform": label},
            "summary": (
                f"{confidence_text}Mention rate {values['mention_rate']:g}% ({values['mentioned_samples']}/"
                f"{values['successful_samples']} completed checks); average mention rank {rank_text}."
            ),
            "summary_key": summary_key,
            "summary_params": {"mention_rate": f"{values['mention_rate']:g}",
                               "mentioned": values["mentioned_samples"],
                               "checks": values["successful_samples"], "rank": rank_text},
            "score": values["score"], "mention_rate": values["mention_rate"],
            "average_mention_rank": values["average_mention_rank"],
            "sample_quality": values["sample_quality"],
            "actions": actions, "action_pillars": pillars,
            "evidence": [_finding_evidence(row) for row in (gaps or successful)[:3]],
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
            return enrich(collect(platform, _measurement_prompt(prompt), spec["country"], spec["language"]), spec,
                          prompt=prompt, prompt_index=prompt_index, sample_index=sample_index)

        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            collected = list(pool.map(execute, tasks))
        for execution in collected:
            stored.append(geo_repository.add_execution(company_id, analysis["id"], execution))
        metrics = calculate_metrics(stored, len(spec["prompts"]))
        try:
            prior_analyses = geo_repository.list_analyses(company_id, 50)
        except geo_repository.GeoStorageUnavailable:
            prior_analyses = []
        metrics["rolling_summary"] = calculate_rolling_summary(
            metrics, prior_analyses, spec, current_analysis_id=analysis["id"]
        )
        metrics["findings"] = build_findings(stored, spec)
        successful = metrics["successful_samples"]
        status = "complete" if successful == len(stored) else "partial" if successful else "failed"
        methodology = {"version": "deterministic-v8", "formula": FORMULA,
                       "measurement_unit": "One provider check is one prompt sent to one AI-search platform.",
                       "notes": "Each buyer question is sent once per selected platform. The provider is asked for up to thirty credible ranked brands in that single answer. Failed executions are excluded from mention-rate denominators. A single check is valid directional evidence; rolling metrics combine up to five comparable analyses for trend context. Mention rank uses the explicit answer list when available, then tracked-entity order; an unopposed mention is not rank #1."}
        geo_repository.finish_analysis(company_id, analysis["id"], status=status, metrics=metrics,
                                       methodology=methodology,
                                       error_code="all_providers_failed" if not successful else None)
    except Exception:
        try:
            geo_repository.finish_analysis(company_id, analysis["id"], status="failed", metrics={},
                                           methodology={"version": "deterministic-v8", "formula": FORMULA},
                                           error_code="analysis_interrupted")
        except Exception:
            pass
        raise
    return geo_repository.get_analysis(company_id, analysis["id"])
