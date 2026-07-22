"""Focused frontend regressions for Team Members limit UI."""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEAM_HTML = ROOT / "frontend" / "team.html"


class TestTeamMemberLimitFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEAM_HTML.read_text(encoding="utf-8", errors="replace")

    def test_reuses_shared_workspace_team_summary(self):
        self.assertIn('authenticatedFetch("/api/workspace")', self.html)
        self.assertIn("usageData.active_member_count", self.html)
        self.assertIn("usageData.pending_invitation_count", self.html)
        self.assertIn("usageData.plan_member_limit", self.html)

    def test_send_invite_remains_enabled_below_limit(self):
        apply_fn = re.search(
            r"function applyTeamInviteLimitState\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("var limitReached = isTeamMemberLimitReached();", apply_fn)
        self.assertIn("btn.disabled = !canManage || !teamMemberEntitlement.loaded || limitReached;", apply_fn)
        self.assertIn("btn.title = limitReached ? getTeamLimitMessage()", apply_fn)

    def test_send_invite_is_disabled_at_limit(self):
        limit_fn = re.search(
            r"function isTeamMemberLimitReached\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn(
            "return (teamMemberEntitlement.used + teamMemberEntitlement.pending) >= teamMemberEntitlement.limit;",
            limit_fn,
        )
        self.assertIn("applyTeamInviteLimitState();", self.html)

    def test_open_add_member_modal_is_blocked_at_limit(self):
        open_fn = re.search(
            r"function openAddMemberModal\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (isTeamMemberLimitReached())", open_fn)
        self.assertIn("showMessage(getTeamLimitMessage(), \"error\");", open_fn)
        self.assertIn("return;", open_fn)
        self.assertIn("add-member-modal", open_fn)

    def test_submit_add_member_is_blocked_at_limit(self):
        submit_fn = re.search(
            r"async function submitAddMember\(\) \{.*?var email =",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("if (isTeamMemberLimitReached())", submit_fn)
        self.assertIn("showMemberFormError(getTeamLimitMessage());", submit_fn)
        self.assertIn("return;", submit_fn)

    def test_unlimited_plans_are_not_blocked(self):
        limit_fn = re.search(
            r"function isTeamMemberLimitReached\(\) \{.*?\n        \}",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("teamMemberEntitlement.limit === null", limit_fn)
        self.assertIn("return false;", limit_fn)
        self.assertIn('var limit = rawLimit != null ? rawLimit : "Unlimited";', self.html)

    def test_cancel_invite_refreshes_usage_state(self):
        cancel_success = re.search(
            r'if \(json.status === "success"\) \{.*?showMessage\("Invitation cancelled successfully\.", "success"\);.*?\}',
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("loadInvites();", cancel_success)
        self.assertIn("loadTeamUsage();", cancel_success)

    def test_cancel_invite_confirmation_copy_mentions_pending_invitation(self):
        cancel_fn = re.search(
            r"async function cancelInvite\(inviteId\) \{.*?authenticatedFetch",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn(
            "Cancel this pending invitation? The invite link will no longer be usable.",
            cancel_fn,
        )
        self.assertIn('confirmText: "Cancel Invite"', cancel_fn)

    def test_resend_submits_invitation_id_instead_of_email(self):
        self.assertIn('data-invite-id=\\"" + inviteId', self.html)
        self.assertIn('onclick=\\"resendInvite(" + inviteId + ", this)\\"', self.html)
        self.assertNotIn("data-invite-email", self.html)

        resend_fn = re.search(
            r"async function resendInvite\(inviteId, clickedButton\) \{.*?\n        \}\n\n        async function cancelInvite",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("body: JSON.stringify({ invite_id: inviteId })", resend_fn)
        self.assertNotIn("JSON.stringify({ email:", resend_fn)

    def test_resend_blocks_duplicate_in_flight_requests_and_disables_button(self):
        resend_fn = re.search(
            r"async function resendInvite\(inviteId, clickedButton\) \{.*?\n        \}\n\n        async function cancelInvite",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn("var resendInviteInFlight = Object.create(null);", self.html)
        self.assertIn("if (resendInviteInFlight[inviteKey])", resend_fn)
        self.assertIn("resendInviteInFlight[inviteKey] = true;", resend_fn)
        self.assertIn("clickedButton.disabled = true;", resend_fn)
        self.assertIn("delete resendInviteInFlight[inviteKey];", resend_fn)
        self.assertIn("clickedButton.disabled = false;", resend_fn)

    def test_successful_resend_refreshes_invites_and_team_usage(self):
        resend_fn = re.search(
            r"async function resendInvite\(inviteId, clickedButton\) \{.*?\n        \}\n\n        async function cancelInvite",
            self.html,
            flags=re.S,
        ).group(0)
        self.assertIn('showMessage("Invitation resent successfully.", "success");', resend_fn)
        self.assertIn("await Promise.all([loadInvites(), loadTeamUsage()]);", resend_fn)

    def test_limit_message_matches_expected_copy(self):
        self.assertIn(
            "Team limit reached. Remove a member, cancel an invitation, or upgrade your plan.",
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
