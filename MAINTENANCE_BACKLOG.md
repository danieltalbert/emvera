# Maintenance Backlog

Last updated: 2026-07-09

## Completed

- Fixed auth and manual-entry route regressions, including onboarding links, password reset routes, POST logout, and manual transaction account scoping.
- Added regression coverage for the 2FA gate, Plaid configuration errors, durable route smoke, competition flows, CSV upload imports, and CSV account ownership.
- Removed small dead code leftovers from data integration and investment routes.
- Afternoon continuation:
  - Required 2FA for debt-management and competition routes.
  - Added ownership coverage for manual debt entry.
  - Added ownership coverage for payment reminders and mark-paid behavior.
  - Added creation and user-isolation coverage for credit score tracking.

## Next Candidates

1. Add focused tests for Plaid sync idempotency and cursor updates using mocked Plaid responses.
2. Add export CSV ownership coverage for investment projections tied to another user.
3. Add competition visibility/authorization tests for dashboard, state, and winner routes when the signed-in user is not a participant.
4. Add validation tests for manual account and manual debt forms with empty or invalid numeric/date fields.
5. Review empty states on debt payoff, investment recommendations, and competition pages for consistent copy and responsive layout.
6. Audit management commands (`plaid_resync`, `send_due_reminders`) for dry-run behavior, user filtering, and safe error reporting.
