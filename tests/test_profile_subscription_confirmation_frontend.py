"""Frontend regressions for subscription management confirmation UX."""

from pathlib import Path
import os
import re
import unittest


# --- Billing moved out of profile.html (2026-09) -------------------------------
# The billing surface now lives on its own page, split across markup, logic and
# styles. These assertions guard the billing guarantees, so they read all three
# parts of that page as one source rather than a single monolithic file.
def _read_billing_source():
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _parts = []
    for _rel in (("billing.html",), ("assets", "js", "billing.js"), ("assets", "css", "billing.css")):
        _path = os.path.join(_root, "frontend", *_rel)
        with open(_path, "r", encoding="utf-8", errors="replace") as _fh:
            _parts.append(_fh.read())
    return chr(10).join(_parts)


def _fn_body(source, name):
    """Return the brace-matched body of a JS function declaration."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", source)
    if not m:
        raise AssertionError("function %s not found in billing source" % name)
    start = source.index("{", m.end() - 1)
    depth = 0
    for j in range(start, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError("unbalanced braces in %s" % name)
# ------------------------------------------------------------------------------



ROOT = Path(__file__).resolve().parents[1]
PROFILE_HTML = ROOT / "frontend" / "profile.html"


class TestProfileSubscriptionConfirmationFrontend(unittest.TestCase):
    """Destructive subscription actions must confirm before calling the API.

    The old Profile page duplicated a confirm-then-call wrapper for each of the
    three destructive actions. The rewritten billing page routes all of them
    through a single mutateSubscription() chokepoint that awaits confirmAction()
    and returns early when the user declines, so an action that skips
    confirmation is structurally impossible rather than merely absent.
    """

    @classmethod
    def setUpClass(cls):
        cls.html = _read_billing_source()

    def test_mutation_confirms_before_calling_the_api(self):
        body = _fn_body(self.html, "mutateSubscription")
        self.assertIn("confirmAction(", body)
        self.assertIn("authenticatedFetch(", body)
        self.assertLess(
            body.index("confirmAction("), body.index("authenticatedFetch("),
            "confirmation must be awaited before the API call",
        )

    def test_declining_the_dialog_aborts_the_mutation(self):
        self.assertRegex(_fn_body(self.html, "mutateSubscription"),
                         re.compile(r"if \(!\w+\) return;"))

    def test_confirm_dialog_never_calls_the_api_itself(self):
        self.assertNotIn("authenticatedFetch", _fn_body(self.html, "confirmAction"))

    def test_all_destructive_actions_route_through_the_chokepoint(self):
        for fn in ("doCancelSubscription", "doUndoCancel", "doClearDowngrade"):
            with self.subTest(action=fn):
                self.assertIn("mutateSubscription", _fn_body(self.html, fn))

    def test_confirmation_copy_preserved(self):
        self.assertIn(
            "Your subscription will remain active and will not be cancelled "
            "at the end of the billing period.", self.html)
        self.assertIn(
            "Your current plan will remain active and the scheduled downgrade "
            "will be removed.", self.html)
