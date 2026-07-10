# Maintenance Backlog

Last updated: 2026-07-10

## Completed

- Fixed auth and manual-entry route regressions, including onboarding links, password reset routes, POST logout, and manual transaction account scoping.
- Added regression coverage for the 2FA gate, Plaid configuration errors, durable route smoke, competition flows, CSV upload imports, and CSV account ownership.
- Removed small dead code leftovers from data integration and investment routes.
- Afternoon continuation:
  - Required 2FA for debt-management and competition routes.
  - Added ownership coverage for manual debt entry.
  - Added ownership coverage for payment reminders and mark-paid behavior.
  - Added creation and user-isolation coverage for credit score tracking.
- 2026-07-10 maintenance:
  - Hardened Plaid transaction sync so same-ID rows from another user are not moved, edited, or deleted.
  - Added mocked Plaid cursor, replay, and ownership regression coverage.
  - Added validation coverage for manual account, transaction, and debt entry forms with empty or invalid fields.
  - Let `plaid_resync --dry-run` audit eligible items without Plaid credentials, with user/stale filters covered by tests.
  - Hardened `send_due_reminders` so email/SMS send failures are logged per reminder and do not stop later reminders.
  - Afternoon continuation normalized empty-state copy/actions for payoff, recommendation, and competition pages and made payoff sidebar layouts responsive.
  - Displayed generated portfolio-wide investment recommendations without creating recommendation rows during GET requests.
  - Reused responsive layout helpers on debt dashboard, reminders, credit score, and investment comparison pages to avoid fixed-grid mobile overflow.

## Next Candidates

1. Add recommendation count/status coverage if reviewed recommendations become user-actionable.
2. Review consolidation recommendation detail grids for small-screen polish.
