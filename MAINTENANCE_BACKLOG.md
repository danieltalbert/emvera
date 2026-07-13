# Maintenance Backlog

Last updated: 2026-07-13

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
  - Replaced the consolidation recommendation detail grid with the responsive card-grid helper.
  - Removed stale imports from the investment recommendation/view modules.
  - Backed the investment recommendation total/new/reviewed stat cards with real view counts.
- 2026-07-11 maintenance:
  - Browser screenshot QA covered portfolio overview, debt dashboard, investment recommendations, and competition dashboard at desktop and mobile sizes.
  - Fixed mobile top-header overflow from the authenticated greeting on narrow investment recommendation pages.
  - Added a POST-only review workflow for persisted investment recommendations, with owner-scoped coverage.
- 2026-07-12 maintenance:
  - Fixed investment comparison allocation bars to use real user-scoped percentages instead of raw dollar values.
  - Restored page-level `h1` headings on competition dashboards after browser QA found the status banner used `h2`.
  - Required POST for marking payment reminders paid, with regression coverage that GET leaves reminders unchanged.
  - Removed stale imports from debt-management and data-integration view modules.
- 2026-07-13 maintenance:
  - Added programmatic labels for avalanche and snowball extra-payment controls, with regression coverage.
- 2026-07-13 deep QA:
  - Promoted auth, password reset/change, onboarding, 2FA, paintball, and competition results pages to accessible page-level headings.
  - Added rendered route accessibility smoke coverage for public/authenticated headings, form labels, and button names.
  - Unified password-change routes on the branded custom view and required 2FA before password updates.
- 2026-07-13 afternoon continuation:
  - Rejected stale mini-game score submissions unless both the competition and mini-game are still active.

## Next Candidates

1. Turn browser screenshot, keyboard-focus, and color-contrast QA into repeatable tooling if a stable browser dependency is added to the repo.
2. Decide whether generated portfolio-wide recommendations should be persisted with a nullable investment relationship or a separate recommendation target model.
