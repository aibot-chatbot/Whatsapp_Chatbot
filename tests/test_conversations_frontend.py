"""Static contract for the rebuilt conversations (sales/CRM pipeline) screen.

Replaces the old glass-styled frontend/conversations.html (2272 lines, Outfit
font, its own inline <style>) with a control-room page built against the
pinned API contract in DESIGN.md ("Pinned API contract for the conversations
redesign"). This file asserts the behaviours that contract and the approved
design spec require and that the old page's kill list is actually gone --
in the style of tests/test_publish_frontend.py, which did the same job for
the previous control-room migration (integration.html).
"""

import re

import pytest

from tests.frontend_pages import ROOT, WEB_PUBLIC_JS, page_source_path

CONV_HTML = page_source_path("conversations.html")
CONV_CSS = ROOT / "frontend" / "assets" / "css" / "conversations.css"
CONTROL_ROOM_CSS = ROOT / "frontend" / "assets" / "css" / "dashboard-control-room.css"

APPROVED_NEW_CONV_CLASSES = {
    "conv-group", "conv-group-head", "conv-row", "conv-row-chips",
    "conv-mini-row", "conv-avatar", "conv-workspace", "conv-composebar",
    "conv-transcript", "conv-bubble",
}


@pytest.fixture(scope="module")
def html():
    markup = CONV_HTML.read_text(encoding="utf-8")
    return markup + (WEB_PUBLIC_JS / "conversations.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css():
    return CONV_CSS.read_text(encoding="utf-8")


# ── Design system integration ────────────────────────────────────────────

def test_conversations_page_joins_the_control_room_design_system(html, css):
    # The conversations.html branch of page-smoke.spec.js's AppLayout order test
    # checks the served shell CSS, three font families, body class and sole allowed CDN script.
    assert "conversations.css" in html
    assert "dashboard-icon" in html

    # The legacy glass system (Outfit, hardcoded bg, inline <style> theme) is gone.
    assert "family=Outfit" not in html
    assert "#050b18" not in html
    assert "glass-card" not in html
    assert "<style>" not in html
    assert "unpkg.com" not in html
    assert "lucide" not in html.lower()

    assert "@media (max-width: 768px)" in css
    assert "prefers-reduced-motion: reduce" in css


def test_every_conv_rule_is_namespaced(css):
    """A page stylesheet must not reach outside .dashboard-page."""
    for line in css.splitlines():
        stripped = line.strip()
        if (".conv-" in line or "#conv-" in line) and not stripped.startswith(("*", "/*")):
            if "{" in line or stripped.startswith(".") or stripped.startswith("#"):
                assert ".dashboard-page" in line, line


def test_only_the_approved_conv_classes_are_new(css):
    """Ten conv-* classes were pre-approved as genuinely new. Everything else
    must reuse kw-*/dashboard-*/cr-* or reach internals via id/data-attribute,
    never a twin of an existing shared component."""
    found = set(re.findall(r"\.conv-[a-z-]+", css))
    found = {name.lstrip(".") for name in found}
    assert found == APPROVED_NEW_CONV_CLASSES, found


def test_reuses_shared_vocabulary_rather_than_twinning_it(html):
    for shared in ("kw-stats", "kw-toolbar", "kw-search", "kw-select", "kw-chip",
                   "kw-badge", "kw-pill", "kw-field", "kw-label", "kw-input",
                   "kw-textarea", "kw-segment", "kw-locked", "kw-banner",
                   "kw-empty", "kw-btn", "cr-skeleton", "dashboard-icon",
                   "dashboard-back-link", "kw-visually-hidden", "kw-panel",
                   "kw-rail", "kw-deflist", "kw-queue", "kw-counter", "kw-muted"):
        assert shared in html, shared


# ── Known data gaps: dead fields never rendered ──────────────────────────

def test_dead_conversation_fields_are_never_rendered(html, css):
    """DESIGN.md 'Known data gaps': these columns are never written by app/
    code and must not be read, searched, or displayed."""
    for dead in ("customer_username", "conversation_status", "ended_at", "phone_requested", "conversation.username"):
        assert dead not in html, dead
        assert dead not in css, dead


# ── Phone masking ─────────────────────────────────────────────────────────

def test_phone_is_masked_client_side(html):
    """/api/conversations returns customer_phone raw (unlike crm_leads, which
    masks it). The page must own its own masking rather than trust the source."""
    assert "function maskPhone(" in html
    mask_fn = re.search(r"function maskPhone\(phone\) \{.*?\n        \}", html, flags=re.S)
    assert mask_fn is not None
    body = mask_fn.group(0)
    assert "***" in body
    # Every place a phone number reaches the DOM goes through maskPhone(...).
    assert re.search(r"maskPhone\(lead \? lead\.customer_phone : conv\.customer_phone\)", html)
    # The raw field is never interpolated into rendered markup directly.
    assert not re.search(r"\$\{[^}]*\.customer_phone\}", html.replace("maskPhone(", ""))


# ── Website replies require a real visitor session ───────────────────────

def test_web_reply_composer_requires_a_valid_visitor_session(html):
    assert "conv-web-notice" in html
    assert "No visitor chat is available for replies" in html
    assert "source_channel === 'web'" in html
    assert "/^web_[0-9a-zA-Z_-]{16,64}$/.test(conv.platform_user_id || '')" in html
    # Test Lab and missing sessions stay hidden; real visitor sessions can reply.
    assert "conv-reply-row').hidden = !canReply" in html
    # "Mark as Resolved" survives and stays independent of channel.
    assert "Mark as Resolved" in html
    assert "does not change the CRM stage" in html


def test_transcript_actions_and_delivery_states_remain_available(html):
    for control in (
        "conv-copy-link",
        "conv-copy-transcript",
        "conv-download-transcript",
        "conv-message-search",
    ):
        assert f'id="{control}"' in html
    for function_name in (
        "function conversationLink(",
        "function transcriptText(",
        "function downloadTranscript(",
        "function deliveryStatusLabel(",
    ):
        assert function_name in html
    assert "state.transcriptSearch" in html
    assert "message.delivery_status" in html


def test_agent_reply_endpoint_is_only_wired_to_the_send_button(html):
    assert "/agent-reply" in html
    assert "async function sendReply()" in html


# ── AI intent and confidence ───────────────────────────────────────────────

def test_ai_signal_suppressed_for_action_type_none(html):
    fn = re.search(r"function buildSignal\(action\) \{.*?\n        \}", html, flags=re.S)
    assert fn is not None
    body = fn.group(0)
    assert "'none'" in body
    assert "return null" in body


def test_confidence_bands_match_the_pinned_thresholds(html):
    fn = re.search(r"function confidenceBand\(confidence\) \{.*?\n        \}", html, flags=re.S)
    assert fn is not None
    body = fn.group(0)
    assert "0.8" in body and "High confidence" in body
    assert "0.6" in body and "Medium confidence" in body
    assert "Low confidence" in body
    # Never rendered as a coloured badge in the signal text itself.
    assert "kw-badge" not in body


def test_raw_confidence_decimal_never_reaches_a_pipeline_row(html):
    # The row/chip builders only ever pass the pre-formatted signal object
    # (text/level), never a raw numeric confidence value.
    row_fn = re.search(r"function buildChipsHtml\(d\) \{.*?\n        \}", html, flags=re.S).group(0)
    assert "confidence" not in row_fn.lower()


# ── Kill list: these do not come back ────────────────────────────────────

def test_kill_list_is_gone(html, css):
    for dead in (
        "setStatusFilter", "status-tab", "Previous</button>", "Clear</button>",
        "crm-lead-modal", "CRM Lead Modal",
    ):
        assert dead not in html, dead
    assert ".status-tab" not in css
    assert "window.confirm" not in html
    assert re.search(r"\balert\(", html) is None


def test_message_search_ui_is_scoped_to_the_open_transcript(html):
    assert 'id="conv-message-search"' in html
    assert 'id="conv-message-search-count"' in html


# ── Accessibility ─────────────────────────────────────────────────────────

def test_transcript_is_a_labelled_live_log(html):
    assert 'role="log"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-relevant="additions"' in html
    assert 'aria-labelledby="conv-transcript-heading"' in html


def test_stage_and_priority_are_real_radiogroups(html):
    assert 'role="radiogroup" aria-label="Stage"' in html
    assert 'role="radiogroup" aria-label="Priority"' in html
    assert html.count('role="radio"') >= 8  # 5 stages + 3 priorities (+ mobile segment)


def test_groups_use_native_details_summary(html):
    assert html.count('<details class="conv-group"') == 5
    for stage in ("new", "contacted", "qualified", "won", "lost"):
        assert f'data-stage="{stage}"' in html

    won_block = re.search(r'<details class="conv-group" data-stage="won">.*?</details>', html, flags=re.S)
    lost_block = re.search(r'<details class="conv-group" data-stage="lost">.*?</details>', html, flags=re.S)
    assert won_block and "open" not in won_block.group(0).split(">")[0]
    assert lost_block and "open" not in lost_block.group(0).split(">")[0]

    new_block = re.search(r'<details class="conv-group" data-stage="new" open>', html)
    assert new_block is not None


def test_pane_announcers_use_visually_hidden_status_roles(html):
    assert 'id="conv-announce-pipeline"' in html
    assert 'id="conv-announce-workspace"' in html
    assert html.count('kw-visually-hidden" role="status" aria-live="polite"') >= 2


def test_no_emoji_and_no_em_dashes_in_page_chrome(html):
    assert "—" not in html
    assert "–" not in html
    emoji = re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", html)
    assert not emoji, emoji


# ── Loading / empty / error / offline states ─────────────────────────────

def test_loading_state_is_skeleton_rows_not_a_bare_string(html):
    assert "cr-skeleton" in html
    assert 'id="conv-pipeline-loading"' in html
    assert ">Loading...<" not in html


def test_empty_states_are_distinct_and_offer_clear_filters(html):
    assert "No conversations yet" in html
    assert "No conversations match these filters" in html
    assert 'id="conv-clear-filters"' in html


def test_error_state_is_a_banner_with_retry_not_a_console_log(html):
    assert "kw-banner-error" in html
    assert 'id="conv-retry"' in html
    assert "We could not load your conversations" in html


def test_offline_keeps_last_good_list_and_marks_it_stale(html):
    assert 'id="conv-stale"' in html
    assert "setStale(" in html
    # A poll failure sets stale and returns without touching the loaded list.
    stale_branch = re.search(r"if \(isPoll && state\.loaded\) \{.*?\n\s*\}", html, flags=re.S)
    assert stale_branch is not None
    assert "setStale(true)" in stale_branch.group(0)


# ── Performance: bounded fan-out, patch-based rendering, slow polling ────

def test_polls_no_faster_than_ten_seconds(html):
    match = re.search(r"setInterval\(\(\) => refresh\(true\), (\d+)\)", html)
    assert match is not None
    assert int(match.group(1)) >= 10000


def test_open_transcript_poll_runs_on_timer_and_visibility_change(html):
    timer = re.search(r"setInterval\(pollOpenTranscript, (\d+)\)", html)
    assert timer and 0 < int(timer.group(1)) <= 5000
    assert "addEventListener('visibilitychange', pollOpenTranscript)" in html
    poll = re.search(r"function pollOpenTranscript\(\) \{(.*?)\n        \}", html, re.S)
    assert poll and "refreshOpenTranscript(true)" in poll[1]
    assert "refresh(true)" not in poll[1]
    refresh = re.search(r"function refreshOpenTranscript\(isPoll\) \{(.*?)\n        \}", html, re.S)[1]
    assert "if (!conv" in refresh and "document.visibilityState" in refresh and "'visible'" in refresh
    assert "state.transcriptInFlight" in refresh.split("getJson(")[0]
    assert "finally" in refresh and "state.transcriptInFlight = null" in refresh
    assert "state.selectedConversationId !== conv.id" in refresh
    assert all(s not in refresh for s in (".focus(", "renderLeadRail", "renderComposebar"))


def test_open_transcript_poll_repaints_changed_message_ids_and_delivery_states(html):
    refresh = re.search(r"function refreshOpenTranscript\(isPoll\) \{(.*?)\n        \}", html, re.S)[1]
    assert "message.id" in refresh and "message.delivery_status" in refresh
    assert "signature === state.transcriptSignature" in refresh
    assert "lastMessageCount" not in refresh
    assert "isTranscriptNearBottom(container)" in refresh


def test_fanout_is_bounded_by_distinct_chatbot_ids_not_by_conversation(html):
    assert "chatbotIds.map(id => getJson(`/api/crm/leads" in html
    assert "chatbotIds.map(id => getJson(`/api/agent/escalations" in html
    # No per-conversation loop hitting /api/conversations/<id>/... for every
    # row in the list -- only for the one conversation the reader opened.
    assert "state.conversations.map" not in html
    assert "state.conversations.forEach(async" not in html


def test_reconciliation_patches_rather_than_rebuilds(html):
    assert "function reconcileChildren(" in html
    # Called for both the pipeline groups and the workspace mini rail.
    assert "reconcileChildren(group.listbox" in html
    assert "reconcileChildren(list, items" in html


def test_poll_never_clobbers_an_in_progress_edit(html):
    # The lead rail and the reply box are rebuilt from server data only on
    # open or after this client's own save/send -- never unconditionally on
    # a poll tick.
    assert "if (!isPoll) renderLeadRailFromState();" in html
    assert "renderLeadRailFromState();" in html  # still called somewhere (on open/save)


# ── Notes autosave: blur AND explicit button, never blur-only ───────────

def test_notes_save_on_blur_and_on_a_visible_button(html):
    assert 'id="conv-notes-save"' in html
    assert "event.target.id !== 'conv-notes'" in html  # blur handler guard
    assert "conv-notes-save" in html


# ── Read-only lead-rail fields have no write path ─────────────────────────

def test_readonly_fields_are_never_included_in_a_save_payload(html):
    save_calls = re.findall(r"saveLeadField\(\{([^}]*)\}", html)
    joined = " ".join(save_calls)
    for readonly_field in ("summary", "customer_name", "customer_phone", "bot_name", "lead_type"):
        assert readonly_field not in joined, readonly_field


def test_lead_type_is_rendered_in_plain_language(html):
    assert "Flagged for staff attention" in html
    assert "Flagged for follow-up" in html
    assert "staff_attention" in html and "follow_up" in html


# ── Owner is plan-gated, attempted optimistically ────────────────────────

def test_owner_control_swaps_to_locked_on_a_403_feature_gate(html):
    assert "state.ownerLocked = true" in html
    assert "kw-locked" in html
    assert re.search(r"result\.status === 403 && 'assigned_to' in fields", html)


# ── DOM order equals visual order ────────────────────────────────────────

def test_pipeline_precedes_workspace_in_dom_order(html):
    assert html.index('id="conv-pipeline"') < html.index('id="conv-workspace"')


def test_workspace_pane_order_matches_the_1440_column_order(html):
    """mini-rail (272px) / transcript (flex) / lead rail (336px), left to
    right, must be the DOM order the three-pane grid relies on."""
    mini_at = html.index('id="conv-mini-rail"')
    transcript_at = html.index('id="conv-transcript-pane"')
    rail_at = html.index('id="conv-lead-rail"')
    assert mini_at < transcript_at < rail_at


def test_back_link_precedes_the_panes_it_replaces(html):
    back_at = html.index('id="conv-back-link"')
    mini_at = html.index('id="conv-mini-rail"')
    assert back_at < mini_at


# ── bot_id / conversation_id contract preserved ──────────────────────────

def test_the_page_belongs_to_one_bot_and_sends_you_to_pick_one_without_it(html):
    assert "urlBotId" in html
    assert "sessionStorage.setItem('selectedBotId'" in html
    assert "location.replace('bots.html')" in html


def test_conversation_id_deep_link_still_works(html):
    assert "conversation_id" in html
    assert "openConversation(" in html
    assert "setUrlConversationId(" in html


def test_only_the_selected_bots_conversations_are_loaded(html):
    assert "/api/conversations?chatbot_id=${BOT_ID}" in html
    assert "company=1" not in html


def test_there_is_no_cross_bot_filter(html):
    assert 'id="conv-filter-bot"' not in html
    assert "All bots" not in html
    assert "filters.bot" not in html
