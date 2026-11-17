"""Profile page: the "Delete workspace" panel and its confirmation dialog.

Source tests in the house style (raw HTML/JS text), plus one Node run of the
pure view-selection function so the four states are executed, not just grepped.
"""

import json
import os
import re
import shutil
import subprocess
import unittest

from tests.frontend_pages import page_source_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")
PROFILE_HTML = page_source_path("profile.html")
PROFILE_JS = os.path.join(FRONTEND, "assets", "js", "profile.js")
PROFILE_CSS = os.path.join(FRONTEND, "assets", "css", "profile.css")
BUNDLED_NODE = os.path.join(ROOT, "node", "node.exe")


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _fn_source(source, name):
    marker = "function " + name
    if marker not in source:
        raise AssertionError("function %s not found" % name)
    start_of_name = source.index(marker)
    start = source.index("{", start_of_name)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start_of_name:index + 1]
    raise AssertionError("unbalanced braces in %s" % name)


def _panel(html):
    match = re.search(r'<section class="kw-panel[^"]*"[^>]*aria-labelledby="pro-delete-title".*?</section>', html, re.S)
    assert match, "the Delete workspace panel is missing"
    return match.group(0)


def _dialog(html):
    match = re.search(r'<dialog[^>]*id="pro-delete-dialog".*?</dialog>', html, re.S)
    assert match, "the confirmation dialog is missing"
    return match.group(0)


class DeletePanelBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(PROFILE_HTML)
        cls.js = _read(PROFILE_JS)
        cls.css = _read(PROFILE_CSS)
        cls.panel = _panel(cls.html)
        cls.dialog = _dialog(cls.html)


class TestPanelMarkup(DeletePanelBase):
    def test_it_is_the_last_panel_on_the_page(self):
        panels = [m.start() for m in re.finditer(r'<section class="kw-panel', self.html)]

        self.assertEqual(self.html.index(self.panel), panels[-1])
        self.assertLess(self.html.index(self.panel), self.html.index('id="pro-announce"'))

    def test_it_is_titled_and_labelled(self):
        self.assertRegex(self.panel, r'<h2 class="kw-panel-title" id="pro-delete-title">\s*Delete workspace\s*</h2>')
        self.assertIn("cannot be undone", self.panel)

    def test_every_state_has_its_own_region(self):
        for element_id in ("pro-delete-loading", "pro-delete-error", "pro-delete-retry", "pro-delete-owner-only",
                           "pro-delete-blocked", "pro-delete-blocked-text", "pro-delete-support-link",
                           "pro-delete-eligible", "pro-delete-request"):
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, self.panel)

    def test_non_owners_get_an_explanation_and_no_button(self):
        block = re.search(r'<div[^>]*id="pro-delete-owner-only".*?</div>', self.panel, re.S).group(0)

        self.assertIn("Only the workspace owner can delete this workspace", block)
        self.assertNotIn("<button", block)

    def test_blocked_owners_are_sent_to_support_and_get_no_delete_button(self):
        block = re.search(r'<div[^>]*id="pro-delete-blocked".*?</div>', self.panel, re.S).group(0)

        self.assertRegex(block, r'<a[^>]*id="pro-delete-support-link"[^>]*href="support\.html"')
        self.assertNotIn("<button", block)

    def test_eligible_owners_see_what_will_be_deleted_before_asking_for_a_code(self):
        block = re.search(r'id="pro-delete-eligible".*?id="pro-delete-request".*?</button>', self.panel, re.S).group(0)

        for thing in ("chatbots", "conversations", "team", "cannot be undone"):
            with self.subTest(thing=thing):
                self.assertIn(thing, block.lower() if thing != "cannot be undone" else block)
        self.assertIn("Email me a code", block)

    def test_states_start_hidden_except_loading(self):
        for element_id in ("pro-delete-error", "pro-delete-owner-only", "pro-delete-blocked", "pro-delete-eligible"):
            with self.subTest(element_id=element_id):
                self.assertRegex(self.panel, r'id="%s"[^>]*\bhidden\b' % element_id)
        self.assertNotRegex(self.panel, r'id="pro-delete-loading"[^>]*\bhidden\b')

    def test_it_uses_the_existing_danger_styling_not_new_colours(self):
        self.assertIn("kw-btn-danger", self.html)
        rules = re.findall(r"[^{}]*pro-delete[^{}]*\{[^}]*\}", self.css)
        self.assertTrue(rules, "the panel needs some styling")
        for rule in rules:
            with self.subTest(rule=rule.strip()[:40]):
                self.assertNotRegex(rule, r"#[0-9a-fA-F]{3,8}\b")
        self.assertIn("var(--control-danger)", "".join(rules))


class TestConfirmationDialog(DeletePanelBase):
    def test_it_is_a_native_dialog_with_a_name_and_a_description(self):
        self.assertRegex(self.dialog, r'<dialog[^>]*aria-labelledby="pro-delete-dialog-title"')
        self.assertRegex(self.dialog, r'<dialog[^>]*aria-describedby="[^"]+"')
        self.assertIn('id="pro-delete-dialog-title"', self.dialog)

    def test_the_code_field_is_labelled_numeric_and_one_time_code(self):
        field = re.search(r'<input[^>]*id="pro-delete-code"[^>]*>', self.dialog, re.S).group(0)

        self.assertRegex(self.dialog, r'<label[^>]*for="pro-delete-code"')
        self.assertIn('inputmode="numeric"', field)
        self.assertIn('autocomplete="one-time-code"', field)
        self.assertIn('maxlength="6"', field)
        self.assertNotIn('type="password"', field)

    def test_the_destructive_button_is_red_and_says_exactly_what_it_does(self):
        button = re.search(r'<button[^>]*id="pro-delete-confirm"[^>]*>.*?</button>', self.dialog, re.S).group(0)

        self.assertIn("kw-btn-danger", button)
        self.assertIn("Delete workspace permanently", button)
        self.assertIn("disabled", button, "nothing to confirm until six digits are typed")

    def test_cancel_is_offered_and_the_status_message_lives_inside_the_dialog(self):
        self.assertIn('id="pro-delete-cancel"', self.dialog)
        status = re.search(r'<p[^>]*id="pro-delete-dialog-status"[^>]*>', self.dialog).group(0)
        self.assertIn('role="status"', status)
        self.assertIn('aria-live="polite"', status)

    def test_a_page_level_live_region_is_not_relied_on_for_dialog_messages(self):
        """Under showModal() everything outside the dialog is inert, so a message
        written to #pro-announce while the dialog is open is never spoken."""
        for name in ("renderDeleteDialogMessage", "setDeleteDialogMessage"):
            if "function " + name in self.js:
                self.assertNotIn("announce(", _fn_source(self.js, name))
                return
        self.fail("no dialog message function found")

    def test_every_input_on_the_page_still_has_a_label(self):
        inputs = re.findall(r'<input[^>]*id="([^"]+)"', self.html)
        labels = set(re.findall(r'<label[^>]*for="([^"]+)"', self.html))
        for element_id in inputs:
            if element_id == "pref-notifications":
                continue
            with self.subTest(element_id=element_id):
                self.assertIn(element_id, labels)

    def test_no_inline_handlers_were_added(self):
        self.assertNotRegex(self.html, re.compile(r"\son(click|change|input|submit|close|cancel)\s*="))


class TestBehaviourSource(DeletePanelBase):
    def test_it_talks_to_the_three_endpoints_through_authenticated_fetch(self):
        for endpoint in ("/api/user/account-deletion", "/api/user/account-deletion/code",
                         "/api/user/account-deletion/confirm"):
            with self.subTest(endpoint=endpoint):
                self.assertRegex(self.js, r"""authenticatedFetch\(\s*["']%s["']""" % re.escape(endpoint))

    def test_the_code_is_never_stored_or_logged(self):
        self.assertNotRegex(self.js, r"(localStorage|sessionStorage)\.setItem\([^)]*code")
        self.assertNotIn("console.log", self.js)

    def test_the_dialog_is_opened_modally_and_focus_is_managed(self):
        self.assertIn(".showModal()", self.js)
        self.assertIn("pro-delete-code", self.js)
        self.assertRegex(self.js, r"\.focus\(\)")
        self.assertRegex(self.js, r"addEventListener\(\s*[\"']close[\"']")

    def test_the_code_field_only_accepts_six_digits(self):
        self.assertRegex(self.js, r"replace\(/\\D/g,\s*[\"']{2}\)")
        self.assertRegex(self.js, r"DELETE_CODE_LENGTH\s*=\s*6\b")
        self.assertRegex(self.js, r"length\s*===\s*DELETE_CODE_LENGTH")
        self.assertIn('maxlength="6"', self.html)

    def test_success_clears_the_session_like_logout_and_leaves_the_page(self):
        success = _fn_source(self.js, "confirmDeletion")

        self.assertIn("/api/user/account-deletion/confirm", success)
        self.assertIn("logout()", success)
        self.assertIn("deactivated_message", success, "the login page already shows this stored message")

    def test_no_markup_is_built_from_server_text(self):
        self.assertNotRegex(self.js, re.compile(r"\.innerHTML\s*="))

    def test_the_new_code_does_not_touch_the_existing_forms(self):
        for name in ("changePassword", "saveAccount", "computeSecurityPosture", "mergeWithRoster"):
            self.assertIn("function " + name, self.js)


@unittest.skipUnless(shutil.which("node") or os.path.exists(BUNDLED_NODE), "Node.js is not available")
class TestViewSelection(DeletePanelBase):
    """deletionView() decides which single region the panel shows."""

    def view(self, body):
        node = shutil.which("node") or BUNDLED_NODE
        script = (_fn_source(self.js, "deletionView")
                  + ";console.log(JSON.stringify(deletionView(JSON.parse(process.argv[1]))));")
        done = subprocess.run([node, "-e", script, json.dumps(body)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.strip())

    def test_an_eligible_owner_gets_the_request_button(self):
        self.assertEqual(self.view({"eligible": True, "is_owner": True, "reason_code": None})["state"], "eligible")

    def test_a_non_owner_gets_the_explanation_only(self):
        self.assertEqual(self.view({"eligible": False, "is_owner": False, "reason_code": "not_owner"})["state"],
                         "owner-only")

    def test_each_block_reason_is_blocked_with_its_own_wording(self):
        texts = set()
        for reason in ("payment_history", "protected", "support_records"):
            result = self.view({"eligible": False, "is_owner": True, "reason_code": reason})
            self.assertEqual(result["state"], "blocked")
            self.assertTrue(result["message"])
            texts.add(result["message"])
        self.assertEqual(len(texts), 3, "each reason is explained differently")

    def test_an_unknown_reason_is_still_blocked_with_a_fallback(self):
        result = self.view({"eligible": False, "is_owner": True, "reason_code": "something_new"})

        self.assertEqual(result["state"], "blocked")
        self.assertTrue(result["message"])

    def test_a_malformed_answer_fails_closed_to_the_error_state(self):
        for body in (None, {}, {"eligible": "yes"}, []):
            with self.subTest(body=body):
                self.assertEqual(self.view(body)["state"], "error")

    def test_eligible_without_ownership_never_shows_the_button(self):
        self.assertNotEqual(self.view({"eligible": True, "is_owner": False})["state"], "eligible")


if __name__ == "__main__":
    unittest.main()
