"""Static contract for the Broadcast and Message Templates screens.

Both pages were rebuilt onto the control-room design system. These tests pin
the behaviours the rebuild exists to guarantee, not the markup that happens to
express them today:

  * both pages joined the shared design system and left the glass one behind
  * neither page carries inline CSS or inline JavaScript any more
  * a broadcast cannot be fired from the screen it was typed on
  * a running broadcast can be watched and stopped
  * the templates page shows what you already have before offering a form

Anything that needs a real cascade -- computed styles, overlap, hit
testing -- lives in tests/browser/broadcast.visual.js, which these
assertions cannot reach.
"""

from pathlib import Path

import pytest

from tests.frontend_pages import page_source_path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

BROADCAST_HTML = page_source_path("broadcast.html")
BROADCAST_JS = FRONTEND / "assets" / "js" / "broadcast.js"
BROADCAST_CSS = FRONTEND / "assets" / "css" / "broadcast.css"

TEMPLATES_HTML = page_source_path("meta_templates.html")
TEMPLATES_JS = FRONTEND / "assets" / "js" / "meta-templates.js"
TEMPLATES_CSS = FRONTEND / "assets" / "css" / "meta-templates.css"

PREVIEW_CSS = FRONTEND / "assets" / "css" / "whatsapp-preview.css"


def _read(path):
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def broadcast_html():
    return _read(BROADCAST_HTML)


@pytest.fixture(scope="module")
def broadcast_js():
    return _read(BROADCAST_JS)


@pytest.fixture(scope="module")
def templates_html():
    return _read(TEMPLATES_HTML)


@pytest.fixture(scope="module")
def templates_js():
    return _read(TEMPLATES_JS)


# -- Design system ------------------------------------------------------

# Both pages' four shell/style/logic/keyboard tests now live in tests/browser/page-smoke.spec.js:
# "pages on AppLayout load the shared shell in the fixed order" and "every built page loads its scripts from files".
@pytest.mark.parametrize("path", [BROADCAST_CSS, TEMPLATES_CSS])
def test_page_stylesheets_own_no_tokens_or_fonts(path):
    css = _read(path)

    # Tokens and font families belong to dashboard-control-room.css. A page
    # sheet that declares its own is how the two design systems drifted apart
    # in the first place.
    assert "--control-canvas:" not in css
    assert "@font-face" not in css
    assert "font-family: 'Outfit'" not in css

    # Everything stays inside the opt-in namespace so it cannot reach the
    # sidebar component or a page that has not joined the system.
    rules = [
        line for line in css.splitlines()
        if line.rstrip().endswith("{") and not line.startswith(("@", " ", "\t"))
    ]
    for rule in rules:
        assert rule.startswith(".dashboard-page"), rule


# -- No inline CSS or JS ------------------------------------------------

def test_broadcast_no_longer_compiles_jsx_in_the_browser(broadcast_html):
    # The old page shipped React, ReactDOM and Babel standalone from a CDN and
    # transpiled JSX on every load.
    assert "babel" not in broadcast_html.lower()
    assert "react" not in broadcast_html.lower()
    assert 'src="assets/js/broadcast.js"' in broadcast_html


# -- The message preview is shared, not duplicated ----------------------

def test_both_pages_share_one_message_preview():
    assert PREVIEW_CSS.exists()

    for path in (BROADCAST_HTML, TEMPLATES_HTML):
        assert "whatsapp-preview.css" in _read(path)

    preview = _read(PREVIEW_CSS)
    assert ".wa-bubble" in preview

    # Neither page sheet may grow its own copy of the bubble; that is how two
    # screens end up disagreeing about what a message looks like.
    for path in (BROADCAST_CSS, TEMPLATES_CSS):
        assert ".wa-bubble {" not in _read(path)


# -- Broadcast: a send cannot happen by accident ------------------------

def test_broadcast_is_a_three_step_wizard(broadcast_html):
    assert 'id="bc-step-1"' in broadcast_html
    assert 'id="bc-step-2"' in broadcast_html
    assert 'id="bc-step-3"' in broadcast_html
    assert 'class="kw-steps"' in broadcast_html


def test_send_button_starts_disabled_and_is_unlocked_by_typing_the_name(broadcast_html, broadcast_js):
    send = broadcast_html.split('id="bc-send"')[1].split(">")[0]
    assert "disabled" in send
    assert "hidden" in send

    # Arming compares the typed value against the campaign name.
    assert "function isArmed()" in broadcast_js
    assert '$("bc-arm").value.trim() === name' in broadcast_js
    assert '$("bc-send").disabled = !armed' in broadcast_js


def test_dispatch_is_held_behind_an_undo_window(broadcast_js):
    assert "UNDO_SECONDS" in broadcast_js

    # The start request must not be issued until the countdown expires,
    # otherwise Undo would be a lie.
    countdown = broadcast_js.split("function startCountdown(")[1].split("function abortCountdown(")[0]
    assert "/start" not in countdown
    assert "dispatch()" in countdown

    # And aborting must say plainly that nothing went out.
    abort = broadcast_js.split("function abortCountdown(")[1].split("async function dispatch(")[0]
    assert "Nobody was messaged" in abort


def test_a_running_broadcast_can_be_watched_and_stopped(broadcast_html, broadcast_js):
    assert 'id="bc-console-progress"' in broadcast_html
    assert 'id="bc-stop"' in broadcast_html
    assert "/progress" in broadcast_js
    assert "/cancel" in broadcast_js

    # Stopping never claims delivered messages were recalled.
    assert "Messages already delivered stay delivered" in broadcast_js


def test_broadcast_can_compose_its_own_message(broadcast_html, broadcast_js):
    """The old page had no message field at all.

    message_template was pinned to the welcome-flow sentinel with no input
    bound to it, so a campaign could only ever send the bot's welcome message
    or a Meta template.
    """
    assert 'id="bc-body"' in broadcast_html
    assert "WELCOME_SENTINEL" in broadcast_js
    assert 'state.bodyMode === "welcome"' in broadcast_js


def test_preview_tells_the_truth_about_meta_templates(broadcast_js):
    """Naming a template makes the worker ignore message_template entirely."""
    assert "Your own message text is" in broadcast_js
    assert "not used" in broadcast_js


# -- Templates: library first -------------------------------------------

def test_templates_page_shows_the_library_before_the_builder(templates_html):
    library = templates_html.index('id="mt-library"')
    builder = templates_html.index('id="mt-builder"')
    assert library < builder

    # The builder is the hidden one on arrival, not the library.
    assert '<section id="mt-builder" hidden>' in templates_html
    assert '<section id="mt-library">' in templates_html


def test_library_can_be_searched_and_filtered(templates_html, templates_js):
    assert "dashboard-icon" in templates_html
    assert "#050b18" not in templates_html
    assert 'id="mt-search"' in templates_html
    assert 'id="mt-filter-category"' in templates_html
    assert 'data-status="APPROVED"' in templates_html
    assert "function visibleTemplates()" in templates_js


def test_every_library_card_renders_the_real_message(templates_js):
    """A template is recognised by reading it, not by parsing its slug."""
    assert "function previewFromComponents(" in templates_js
    assert "function previewFromBuilder(" in templates_js

    # Both producers feed the same renderer, so a card and the builder can
    # never disagree about the same template.
    grid = templates_js.split("function renderGrid()")[1].split("function templateByName")[0]
    assert "renderPreview(container, previewFromComponents(" in grid


def test_builder_is_a_three_step_wizard(templates_html):
    assert 'id="mt-step-1"' in templates_html
    assert 'id="mt-step-2"' in templates_html
    assert 'id="mt-step-3"' in templates_html
    assert 'class="kw-steps"' in templates_html


def test_builder_keeps_every_meta_component_the_old_page_supported(templates_js):
    for token in ("HEADER", "BODY", "FOOTER", "BUTTONS"):
        assert '"' + token + '"' in templates_js
    for fmt in ("TEXT", "IMAGE", "VIDEO", "DOCUMENT"):
        assert fmt in templates_js
    for button in ("QUICK_REPLY", "URL", "PHONE_NUMBER", "COPY_CODE"):
        assert button in templates_js

    # Meta wants a sample for every placeholder in the body.
    assert "body_text" in templates_js
    assert "Sample_" in templates_js


def test_template_name_is_sanitised_to_meta_rules(templates_js):
    assert "function sanitizeName(" in templates_js
    assert "[^a-z0-9_]" in templates_js


def test_deleting_a_template_warns_what_it_breaks(templates_js):
    assert "removed from Meta permanently" in templates_js
    assert "Any campaign still naming it will stop working" in templates_js


# -- Accessibility floor ------------------------------------------------

@pytest.mark.parametrize("path", [BROADCAST_HTML, TEMPLATES_HTML])
def test_pages_announce_changes_and_label_their_controls(path):
    html = _read(path)

    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "kw-visually-hidden" in html

    # Segmented controls are radio groups, not anonymous button rows.
    assert 'role="radiogroup"' in html
    assert "aria-checked=" in html

    # Modals identify themselves.
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html


@pytest.mark.parametrize("path", [BROADCAST_JS, TEMPLATES_JS])
def test_rendered_values_are_escaped_before_reaching_innerhtml(path):
    js = _read(path)

    assert "function esc(value)" in js
    assert "&amp;" in js and "&lt;" in js and "&quot;" in js

    # Every value interpolated into markup goes through esc(). Keeping the
    # escape helper's call count well above the number of innerHTML writes is
    # the cheap smoke test for someone adding a raw one later.
    assert js.count("esc(") > js.count("innerHTML =")


@pytest.mark.parametrize("path", [BROADCAST_JS, TEMPLATES_JS])
def test_segmented_controls_are_reachable_by_keyboard(path):
    """kw-segment uses roving tabindex, so only one button is tabbable.

    Without arrow-key handling a keyboard user reaches that one button and
    can never choose a different option (WCAG 2.2 SC 2.1.1).
    """
    assert "kwRadioGroup(document)" in _read(path)


@pytest.mark.parametrize("path", [BROADCAST_JS, TEMPLATES_JS])
def test_dialogs_contain_and_return_focus(path):
    js = _read(path)

    # Opening and closing go through the helper, which traps Tab inside the
    # dialog and hands focus back to whatever opened it.
    assert "kwDialog.open(" in js
    assert "kwDialog.close(" in js
    assert 'classList.add("is-open")' not in js
    assert 'classList.remove("is-open")' not in js


def test_message_preview_is_readable_by_a_screen_reader(broadcast_html, templates_html, templates_js):
    """role="img" would announce only the label and skip the message inside.

    The message is the one thing a person needs read back to them before an
    irreversible send, so the preview is a group, not an image.
    """
    for source in (broadcast_html, templates_html, templates_js):
        assert 'role="img"' not in source

    assert 'class="wa-preview" id="bc-preview" aria-labelledby="bc-preview-label" role="group"' in broadcast_html


def test_broadcast_requires_customer_permission(broadcast_html, broadcast_js):
    assert 'id="bc-consent" required' in broadcast_html
    assert "I confirm these customers agreed to receive messages from my business." in broadcast_html
    armed = broadcast_js.split("function isArmed()")[1].split("function clearTimers()")[0]
    assert '$("bc-consent").checked' in armed
    assert 'consent_confirmed: $("bc-consent").checked' in broadcast_js
    assert '$("bc-consent").checked = false' in broadcast_js
