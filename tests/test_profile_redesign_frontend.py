"""Frontend tests for the redesigned, personal-only Profile page.

The Profile page was split in 2026-09: billing moved to billing.html and the
admin-only Company Information editor moved to team.html. What remains is a
single scrolling, personal page - identity, security, workspace standing and
preferences - built in the control-room design system.

These tests guard that split and the new sections. Billing coverage lives in
the test_profile_*_frontend / test_phase_4* suites, which now read billing.html;
the Company Information editor is covered by test_workspace_frontend.py against
team.html.
"""

import os
import re
import shutil
import subprocess
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")

PROFILE_HTML = os.path.join(FRONTEND, "profile.html")
PROFILE_JS = os.path.join(FRONTEND, "assets", "js", "profile.js")
PROFILE_CSS = os.path.join(FRONTEND, "assets", "css", "profile.css")

BUNDLED_NODE = os.path.join(ROOT, "node", "node.exe")


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _fn_source(source, name):
    """Return the full text of a JS function declaration, brace-matched."""
    marker = "function " + name
    if marker not in source:
        raise AssertionError("function %s not found" % name)
    i = source.index(marker)
    start = source.index("{", i)
    depth = 0
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)


class ProfilePageBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(PROFILE_HTML)
        cls.js = _read(PROFILE_JS)
        cls.css = _read(PROFILE_CSS)
        cls.source = cls.html + cls.js + cls.css


class TestProfileIsPersonalOnly(ProfilePageBase):
    """Billing and admin-write surfaces must not be on the Profile page."""

    def test_no_billing_endpoints_are_called(self):
        """No call site may reach a billing endpoint.

        Matched on call sites rather than raw text, because the file documents
        in a comment that it deliberately reads nothing under /api/billing.
        """
        self.assertNotRegex(self.js, re.compile(r"""(getJson|authenticatedFetch)\(\s*["'`]/api/billing"""))

    def test_no_billing_sections_remain(self):
        for token in (
            "Company Plan",
            "billing-notifications",
            "toyyibpay",
            "Top Up",
            "Billing History",
            "Credit Transactions",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, self.html)

    def test_no_company_information_editor(self):
        """The admin-only company editor lives on team.html now."""
        self.assertNotIn("Company information", self.html)
        self.assertNotIn("Company Information", self.html)
        self.assertNotIn("saveCompany", self.js)

    def test_tab_bar_is_retired(self):
        """The three-tab layout was replaced by a single scrolling page."""
        self.assertNotIn("switchProfileTab", self.source)
        self.assertNotIn("profile-tab-content", self.html)
        self.assertNotIn("tabs-nav", self.html)


class TestRetiredThemeToggle(ProfilePageBase):
    """The Dark Theme toggle was removed: no light palette exists."""

    def test_theme_toggle_is_gone(self):
        self.assertNotIn("pref-theme", self.source)
        self.assertNotIn("toggleTheme", self.source)

    def test_no_data_theme_manipulation(self):
        self.assertNotIn("data-theme", self.js)

    def test_notification_preference_survives_and_is_scoped_to_the_browser(self):
        self.assertIn("pref-notifications", self.html)
        self.assertIn("localStorage", self.js)
        self.assertRegex(self.html, re.compile(r"(?i)this browser|this device"))


class TestIdentityHero(ProfilePageBase):
    """The hero carries identity plus the security gauge."""

    def test_hero_elements_exist(self):
        for element_id in (
            "pro-hero",
            "pro-avatar",
            "pro-hero-name",
            "pro-hero-email",
            "pro-hero-tags",
            "pro-hero-tenure",
            "pro-hero-gauge",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, self.html)

    def test_initials_are_derived_for_the_avatar(self):
        self.assertIn("function initialsFor", self.js)

    def test_tenure_is_computed_from_created_at(self):
        self.assertIn("function tenureFrom", self.js)
        self.assertIn("created_at", self.js)

    def test_widened_user_fields_are_consumed(self):
        """GET /api/user was widened with these four fields."""
        for field in ("created_at", "updated_at", "is_verified", "status"):
            with self.subTest(field=field):
                self.assertIn(field, self.js)

    def test_roster_is_a_fallback_for_the_widened_fields(self):
        """If /api/user omits the new fields, find them in the roster."""
        self.assertIn("function mergeWithRoster", self.js)
        self.assertIn("/api/users", self.js)


class TestSecurityPosture(ProfilePageBase):
    """The posture gauge must be actionable, not decorative."""

    def test_gauge_and_signal_list_exist(self):
        self.assertIn('id="pro-hero-gauge"', self.html)
        self.assertIn('id="pro-signals"', self.html)
        self.assertIn("function buildGauge", self.js)
        self.assertIn("function renderSignals", self.js)

    def test_gauge_uses_the_design_system_component(self):
        self.assertIn("kw-gauge", self.source)

    def test_gauge_circumference_matches_the_stylesheet_radius(self):
        """r=33 in dashboard-control-room.css, so the circle is 2*pi*33."""
        self.assertRegex(self.js, re.compile(r"207\.3"))

    def test_gauge_is_announced_to_assistive_tech(self):
        gauge = _fn_source(self.js, "buildGauge")
        self.assertIn("aria-label", gauge)
        self.assertIn('"img"', gauge)

    def test_scoring_uses_only_signals_available_without_schema_changes(self):
        posture = _fn_source(self.js, "computeSecurityPosture")
        for signal in ("is_verified", "phone", "full_name", "status"):
            with self.subTest(signal=signal):
                self.assertIn(signal, posture)

    def test_unmet_signals_link_to_the_control_that_fixes_them(self):
        posture = _fn_source(self.js, "computeSecurityPosture")
        self.assertIn("#profile-phone", posture)
        self.assertIn("#profile-full-name", posture)

    def test_weighting_decision_is_still_flagged_for_the_owner(self):
        """The maths is a product decision and is marked as such."""
        self.assertIn("TODO(user decision)", self.js)


class TestSecurityPostureBehaviour(unittest.TestCase):
    """Execute the scoring function rather than pattern-matching it."""

    @classmethod
    def setUpClass(cls):
        cls.js = _read(PROFILE_JS)
        cls.node = shutil.which("node") or (BUNDLED_NODE if os.path.exists(BUNDLED_NODE) else None)

    def _score(self, user):
        if not self.node:
            self.skipTest("Node.js is not available")
        import json
        script = (
            _fn_source(self.js, "computeSecurityPosture")
            + ";const user = JSON.parse(process.argv[1]);"
            + ";console.log(JSON.stringify(computeSecurityPosture(user)));"
        )
        completed = subprocess.run(
            [self.node, "-e", script, json.dumps(user)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.strip())

    def test_fully_hardened_account_scores_100(self):
        result = self._score({
            "full_name": "Test User",
            "phone": "+60123456789",
            "is_verified": True,
            "status": "active",
        })
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["met"], result["total"])

    def test_empty_account_scores_zero(self):
        result = self._score({})
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["met"], 0)

    def test_score_is_a_percentage(self):
        result = self._score({"full_name": "Test User", "status": "active"})
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertEqual(result["score"], round(result["met"] / result["total"] * 100))

    def test_whitespace_only_values_do_not_count_as_met(self):
        """A phone of spaces must not satisfy the recovery-phone signal."""
        result = self._score({"phone": "   ", "full_name": "   "})
        self.assertEqual(result["met"], 0)


class TestWorkspaceStanding(ProfilePageBase):
    """Read-only standing: role, seats, composition, timeline, invites."""

    def test_section_exists(self):
        self.assertIn("Your standing in this workspace", self.html)
        for element_id in ("pro-standing", "pro-role", "pro-seats", "pro-composition",
                           "pro-timeline", "pro-pending"):
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, self.html)

    def test_seat_meter_and_composition_use_design_system_components(self):
        self.assertIn("kw-progress", self.source)
        self.assertIn("kw-composition", self.source)

    def test_timeline_uses_the_steps_component(self):
        self.assertIn("kw-steps", self.source)
        self.assertIn("function renderTimeline", self.js)

    def test_standing_is_read_only_and_delegates_to_the_team_page(self):
        self.assertIn('id="pro-team-link"', self.html)
        self.assertIn("team.html", self.html)

    def test_seat_limit_failure_degrades_without_breaking_the_panel(self):
        """A missing plan limit hides the meter rather than erroring."""
        self.assertIn("function renderSeats", self.js)
        self.assertIn('id="pro-seats-block"', self.html)


class TestAsyncStates(ProfilePageBase):
    """Every async region needs loading, empty and error states."""

    def test_three_states_exist_for_each_async_region(self):
        for element_id in (
            "pro-hero-skeleton",
            "pro-signals-loading", "pro-signals-empty",
            "pro-standing-loading", "pro-standing-empty", "pro-standing-error",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, self.html)

    def test_errors_offer_a_retry(self):
        self.assertIn('id="pro-retry"', self.html)
        self.assertIn('id="pro-standing-retry"', self.html)

    def test_skeletons_use_the_motion_layer(self):
        self.assertIn("cr-skeleton", self.html)


class TestAccessibility(ProfilePageBase):
    def test_status_region_is_polite_and_live(self):
        self.assertIn('id="pro-announce"', self.html)
        self.assertIn('aria-live="polite"', self.html)

    def test_every_input_has_a_label(self):
        inputs = re.findall(r'<input[^>]*id="([^"]+)"', self.html)
        labels = set(re.findall(r'<label[^>]*for="([^"]+)"', self.html))
        for element_id in inputs:
            if element_id == "pref-notifications":
                continue  # wrapped in its own <label>
            with self.subTest(element_id=element_id):
                self.assertIn(element_id, labels)

    def test_reduced_motion_is_respected(self):
        self.assertIn("prefers-reduced-motion", self.css)

    def test_focus_is_visible(self):
        """Focus rings come from the shared control-room stylesheet.

        profile.css deliberately does not redefine them; the page loads
        dashboard-control-room.css, which owns the focus treatment.
        """
        shared = _read(os.path.join(FRONTEND, "assets", "css", "dashboard-control-room.css"))
        self.assertIn(":focus-visible", shared)
        self.assertIn("assets/css/dashboard-control-room.css", self.html)


class TestDesignSystemCompliance(ProfilePageBase):
    """The page must read as the same product as team.html / pricing.html."""

    def test_stylesheet_order_is_correct(self):
        order = [
            "assets/css/shared-glass.css",
            "assets/css/dashboard-control-room.css",
            "assets/css/control-room-motion.css",
            "assets/css/profile.css",
        ]
        positions = [self.html.index(href) for href in order]
        self.assertEqual(positions, sorted(positions),
                         "page CSS must load last to win at equal specificity")

    def test_control_room_shell_is_used(self):
        self.assertIn('class="dashboard-page"', self.html)
        self.assertIn("main-container kw-page", self.html)
        self.assertIn("kw-header", self.html)

    def test_retired_design_system_tokens_are_absent(self):
        for token in ("#3b82f6", "Outfit", "glass-card", "profile-section"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.html)
                self.assertNotIn(token, self.css)

    def test_markup_is_thin_and_logic_is_external(self):
        """The 4,827-line inline-everything page is the anti-pattern retired."""
        self.assertNotIn("<style", self.html)
        self.assertLess(len(self.html.splitlines()), 600)
        self.assertIn('src="assets/js/profile.js"', self.html)

    def test_no_inline_event_handlers(self):
        self.assertNotRegex(self.html, re.compile(r"\son(click|change|input|submit)\s*="))
        self.assertIn("addEventListener", self.js)

    def test_vanilla_markup_not_react_idiom(self):
        self.assertNotIn("className", self.html)


class TestRenderingSafety(ProfilePageBase):
    """Backend values must never be written as markup."""

    def test_no_inner_html_assignment(self):
        self.assertNotRegex(self.js, re.compile(r"\.innerHTML\s*="))

    def test_dom_helper_assigns_text_content(self):
        self.assertIn("textContent", _fn_source(self.js, "el"))


if __name__ == "__main__":
    unittest.main()
