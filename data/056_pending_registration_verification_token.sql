-- 056: email verification link for pending registrations
--
-- Registration already emails a six digit OTP, and /login already refuses any
-- user whose is_verified is false. What was missing is a clickable link, so
-- this adds a single-use token alongside the existing OTP.
--
-- The token deliberately does NOT get its own expiry column: it shares
-- otp_expiry, so the code and the link always expire together. Two clocks for
-- one registration is a bug waiting to happen.

ALTER TABLE pending_registrations
    ADD COLUMN IF NOT EXISTS verification_token TEXT;

-- Every click of the link looks the row up by token, so the token must be
-- unique across pending rows or one click could resolve to two registrations.
-- Partial index: rows predating this migration have NULL and must not collide.
CREATE UNIQUE INDEX IF NOT EXISTS pending_registrations_verification_token_key
    ON pending_registrations (verification_token)
    WHERE verification_token IS NOT NULL;

COMMENT ON COLUMN pending_registrations.verification_token IS
    'Single-use URL-safe token for the email verification link. Generated with '
    'secrets.token_urlsafe(32). Removed together with the pending row once the '
    'user is created. Shares otp_expiry so link and OTP expire together.';
