# Deployment Checklist

## Release Scope

Before deployment, define:

- Features included
- Database changes
- RPC changes
- Environment changes
- External integration changes
- Rollback point

## Environment

Confirm:

- Production Python version
- Dependency installation
- Runtime command
- Environment variables
- Secret storage
- HTTPS
- Domain configuration
- CORS origins
- Logging configuration
- Time zone
- File storage paths

## Required Secrets

Confirm secure configuration for:

- Supabase
- JWT
- AI providers
- Email
- Telegram
- Wasender
- Meta WhatsApp
- ToyyibPay

Never store live secret values in the repository.

## Database

Before deployment:

- Back up the database
- Review migrations
- Review RPC changes
- Review indexes
- Review constraints
- Review RLS policies
- Apply changes in staging
- Record rollback SQL where practical

## Security

Confirm:

- Debug mode disabled
- OTP values not logged
- Development tunnels disabled
- CORS restricted
- Raw exceptions not returned
- Rate limiting enabled for authentication-sensitive routes
- Webhook signatures or secrets configured
- Secrets masked in logs
- Frontend contains no credentials
- Tenant-isolation tests pass

## Automated Verification

Run:

```powershell
python -m compileall app tests
python -m pytest tests -q
git diff --check
```

Record exact results.

## Manual Application Verification

### Authentication

- Register
- Login
- Logout
- Forgot password
- Reset password
- Invite acceptance

### Chatbots

- Create
- Edit
- Delete
- Change model
- Update prompt

### Knowledge

- Upload
- List
- Activate
- Toggle support
- Scrape
- Ask a knowledge-based question

### Conversations and CRM

- Receive or create a conversation
- View messages
- Search messages
- Copy link
- Open deep link
- Copy transcript
- Download transcript
- Open conversation from CRM
- Update CRM fields

### Integrations

- Telegram
- Wasender
- Meta WhatsApp

Verify connect, webhook, reply, failure, and disconnect behavior as applicable.

### Billing

- Load plan
- Load usage
- Load balance
- Create top-up checkout
- Complete controlled payment
- Confirm callback
- Confirm credited order
- Confirm single balance increase
- Confirm transaction history

## Background Workers

Confirm:

- Required workers start once
- Duplicate workers are not created by reloaders
- Retry intervals are correct
- Failures are logged safely
- Shutdown behavior is acceptable

## Monitoring

Confirm visibility for:

- Application errors
- Authentication failures
- Webhook failures
- Provider failures
- Payment callback failures
- Credit-processing failures
- Retry exhaustion
- Database errors

## Rollback

Document:

- Previous application version
- Database rollback limitations
- RPC rollback steps
- Environment rollback
- External webhook rollback
- Communication owner

Do not roll back application code across an irreversible schema change without a compatible plan.

## Release Approval

Production deployment requires human approval after:

- Tests pass
- Security checklist passes
- Database review passes
- Integration configuration is confirmed
- Rollback plan is recorded
