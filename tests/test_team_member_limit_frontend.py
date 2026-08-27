"""Structural contract for the Team screen.

WHAT CHANGED AND WHY
--------------------
This file used to assert on the raw source text of ``frontend/team.html``:
exact JavaScript lines, exact indentation, function ordering, and the
presence of inline ``onclick=`` attributes built by string concatenation.
Those assertions passed without ever running the code, and they made the
seat rules impossible to refactor -- extracting the behaviour into
``assets/js/team.js`` (the convention every other control-room page
follows) broke twelve of them at once, none of them for a real reason.

The behaviour they were meant to protect is now covered properly by
``tests/browser/team.spec.js``, which drives the real page in a browser:
the invite button disabling at the limit, a pending invitation consuming a
seat, unlimited plans never blocking, resend de-duplicating in flight,
confirmation before destructive actions, and read-only access for members.

What remains here is the cheap structural half that a browser test should
not have to pay for: the wiring between the page and its assets, the
element ids the JavaScript depends on, and the handful of literal strings
and API shapes that are genuine contracts. None of it pins formatting.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEAM_HTML = ROOT / "frontend" / "team.html"
TEAM_JS = ROOT / "frontend" / "assets" / "js" / "team.js"
TEAM_CSS = ROOT / "frontend" / "assets" / "css" / "team.css"

LIMIT_MESSAGE = (
    "Team limit reached. Remove a member, cancel an invitation, "
    "or upgrade your plan."
)


class TeamPageWiringTests(unittest.TestCase):
    """The page must actually load the assets that implement it."""

    @classmethod
    def setUpClass(cls):
        cls.html = TEAM_HTML.read_text(encoding="utf-8", errors="replace")

    def test_assets_exist(self):
        self.assertTrue(TEAM_JS.is_file(), "frontend/assets/js/team.js is missing")
        self.assertTrue(TEAM_CSS.is_file(), "frontend/assets/css/team.css is missing")

    def test_page_loads_its_own_stylesheet_and_script(self):
        self.assertIn('href="assets/css/team.css"', self.html)
        self.assertIn('src="assets/js/team.js"', self.html)

    def test_page_uses_the_control_room_shell(self):
        # Every kw-* rule is scoped `.dashboard-page .kw-*`; without the body
        # class the entire component vocabulary silently does nothing.
        self.assertIn('<body class="dashboard-page">', self.html)
        self.assertIn('class="main-container kw-page"', self.html)

    def test_stylesheet_order_puts_page_css_last(self):
        # Page CSS must come after dashboard-control-room.css or its overrides
        # lose at equal specificity.
        order = [
            self.html.index("assets/css/dashboard-control-room.css"),
            self.html.index("assets/css/control-room-motion.css"),
            self.html.index("assets/css/team.css"),
        ]
        self.assertEqual(order, sorted(order))

    def test_no_wrapper_class_contains_the_substring_grid(self):
        # shared-glass.css force-collapses div[class*="grid"] to one column
        # below 768px with !important, which silently breaks any layout
        # wrapper whose class name happens to contain "grid".
        for match in re.finditer(r'<div[^>]*class="([^"]*)"', self.html):
            self.assertNotIn(
                "grid", match.group(1),
                "wrapper class %r contains 'grid' and will be collapsed by "
                "shared-glass.css at <=768px" % match.group(1),
            )

    def test_reading_the_team_does_not_require_admin(self):
        # GET /api/users and GET /api/invites are open to members; the page
        # must show them the roster rather than redirecting.
        self.assertIn("requireLogin();", self.html)
        self.assertNotIn("requireAdminOrOwner();", self.html)

    def test_ids_the_script_depends_on_are_present(self):
        # A rename on either side should fail here rather than producing a
        # silently dead control in the browser.
        for element_id in [
            "tm-banner", "tm-banner-text", "tm-retry", "tm-readonly",
            "tm-invite", "tm-count", "tm-loading", "tm-empty",
            "tm-table-wrap", "tm-tbody",
            "tm-invites", "tm-invites-empty", "tm-invites-loading",
            "tm-seats", "tm-upgrade", "tm-announce",
            "tm-invite-modal", "tm-invite-form", "tm-invite-email",
            "tm-invite-role", "tm-invite-error", "tm-invite-submit",
            "tm-invite-cancel", "tm-invite-close",
            "tm-confirm", "tm-confirm-title", "tm-confirm-body",
            "tm-confirm-ok", "tm-confirm-cancel", "tm-confirm-close",
        ]:
            self.assertIn('id="%s"' % element_id, self.html)

    def test_both_dialogs_are_announced_as_dialogs(self):
        # kw-a11y supplies the focus trap, but the roles have to be in the
        # markup or a screen reader never learns a dialog opened.
        self.assertEqual(self.html.count('role="dialog"'), 2)
        self.assertEqual(self.html.count('aria-modal="true"'), 2)
        self.assertEqual(self.html.count('aria-labelledby="tm-invite-title"'), 1)
        self.assertEqual(self.html.count('aria-labelledby="tm-confirm-title"'), 1)

    def test_a_live_region_exists_for_async_feedback(self):
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_primary_action_is_not_in_the_header_right_slot(self):
        # A fixed account menu at z-index 1001 covers that slot and swallows
        # clicks, so the invite button must live elsewhere.
        header = re.search(r"<header class=\"kw-header\">.*?</header>",
                           self.html, flags=re.S)
        if header is None:
            self.fail("team.html has no kw-header element")
        markup = header.group(0)
        self.assertNotIn("<button", markup)
        self.assertNotIn('id="tm-invite"', markup)


class TeamSeatRuleTests(unittest.TestCase):
    """Seat semantics that must not drift from the server."""

    @classmethod
    def setUpClass(cls):
        cls.js = TEAM_JS.read_text(encoding="utf-8", errors="replace")

    def test_reads_the_shared_workspace_summary(self):
        self.assertIn('getJson("/api/workspace")', self.js)
        self.assertIn("await authenticatedFetch(url)", self.js)
        self.assertIn("active_member_count", self.js)
        self.assertIn("pending_invitation_count", self.js)
        self.assertIn("plan_member_limit", self.js)

    def test_a_pending_invitation_counts_against_the_limit(self):
        # The server checks active + pending, so the UI must too. Checking
        # active alone would offer an invite the API then refuses.
        self.assertIn("(e.used + e.pending) >= e.limit", self.js)

    def test_unlimited_and_unknown_entitlement_never_block(self):
        self.assertIn("if (!e.loaded || e.limit === null) return false;", self.js)

    def test_limit_message_copy_is_unchanged(self):
        self.assertIn(LIMIT_MESSAGE, self.js)

    def test_resend_sends_the_invite_id_in_the_body(self):
        # POST /api/invites/resend takes invite_id in the body; the old page
        # briefly sent an email address instead. Scoped to the resend
        # function, because CREATING an invite legitimately sends an email.
        start = self.js.index("async function resendInvite(")
        end = self.js.index("async function cancelInvite(", start)
        body = self.js[start:end]
        self.assertIn("JSON.stringify({ invite_id: id })", body)
        self.assertNotIn("JSON.stringify({ email:", body)

    def test_resend_guards_against_a_double_submit(self):
        # The endpoint rotates the token, so a second in-flight resend would
        # invalidate the link the first one just mailed out.
        self.assertIn("resendInFlight", self.js)
        self.assertIn("if (resendInFlight[key]) return;", self.js)

    def test_invite_id_is_validated_before_use(self):
        self.assertIn("Number.isInteger(id)", self.js)

    def test_the_three_forbidden_states_are_told_apart(self):
        # Permission denied, suspended company and billing limit are three
        # different 403s that need three different answers.
        self.assertIn('body.code === "company_suspended"', self.js)
        self.assertIn('body.code === "team_member_limit"', self.js)
        self.assertIn('body.code === "no_subscription"', self.js)

    def test_success_feedback_survives_the_reload_that_follows_it(self):
        # loadAll() opens with clearBanner(), so a banner raised before the
        # reload is wiped before anyone can read it. Every success path must
        # reload first and announce afterwards.
        pattern = re.compile(r'showBanner\((?:[^()]|\([^()]*\))*"success"\)', re.S)
        matches = list(pattern.finditer(self.js))
        self.assertGreaterEqual(len(matches), 5)
        for match in matches:
            preceding = self.js[:match.start()]
            self.assertRegex(
                preceding[-120:], r"await loadAll\(\);\s*$",
                "a success banner is raised before loadAll(), which clears it",
            )

    def test_dates_are_locale_aware(self):
        # The old page hardcoded en-US.
        self.assertIn("Intl.DateTimeFormat", self.js)
        self.assertNotIn('"en-US"', self.js)

    def test_invite_expiry_is_derived_not_read_from_status(self):
        # Only "pending" and "accepted" are ever written to invites.status;
        # there is no stored "expired" state to read.
        self.assertIn("daysUntil", self.js)
        self.assertNotIn('status === "expired"', self.js)

    def test_no_blocking_dialogs_or_debug_output(self):
        self.assertNotIn("alert(", self.js)
        self.assertNotIn("console.log", self.js)


if __name__ == "__main__":
    unittest.main()
