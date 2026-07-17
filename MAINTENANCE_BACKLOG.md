# Maintenance Backlog

Last updated: 2026-07-16

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
  - Rejected malformed and negative mini-game scores before creating result rows.
  - Ranked competition leaders and winners by total value, including mini-game bonuses.
  - Normalized negative or invalid payoff extra-payment query values to zero.
- 2026-07-14 maintenance:
  - Browser DOM QA covered onboarding, portfolio, debt, investment, and competition pages at desktop and mobile sizes with no page-level overflow, missing headings, unlabeled controls, unnamed buttons, or console errors.
  - Required mini-game score submissions to include an explicit score before creating result rows.
  - Aligned participant rank calculations with the total-value leaderboard that includes mini-game bonuses.
- 2026-07-14 afternoon continuation:
  - Required 2FA-enabled users for the two-factor settings page and redirected users back to setup after disabling 2FA.
  - Replaced remaining PNW Finance branding on onboarding and portfolio performance pages with Ridge & River Financial.
  - Removed unreferenced initial scaffold handoff notes from data integration and debt management app folders.
- 2026-07-15 deep QA:
  - Added durable no-data accessibility smoke coverage for investment, debt, and competition empty-state routes.
  - Browser QA checked those no-data routes at desktop and mobile widths for headings, expected copy, form labels, button names, and horizontal overflow.
- 2026-07-15 afternoon continuation:
  - Added server-side validation for competition create-form numeric bounds so crafted POSTs cannot bypass the UI limits.
  - Added server-side validation for manual debt numeric bounds so crafted POSTs cannot bypass nonnegative balance/payment and APR limits.
  - Added server-side validation so payment reminders reject nonpositive payment amounts.
  - Removed proven-dead imports from account and investment modules.
- 2026-07-16 maintenance:
  - Tightened mini-game score parsing so JSON booleans, floats, and decimal strings cannot create result rows.
  - Moved the login password-reset link outside the password field label so the input's accessible name stays concise.
- 2026-07-16 afternoon continuation:
  - Added a server-side ceiling for mini-game score submissions so oversized crafted payloads cannot create result rows.
  - Normalized non-finite payoff extra-payment query values to zero so crafted `NaN` or `Infinity` inputs keep debt tools rendering.
  - Made manual transaction entry assign `manual` source server-side and removed the misleading Source selector from the form.
- 2026-07-17 afternoon continuation:
  - Kept competitions the signed-in user already joined out of the public Join Now and In Progress lobby lists, with route-smoke coverage for separate joined and spectatable sections.
  - Redirected repeat join requests from existing lobby participants back to the competition dashboard while preserving full-lobby rejection for new users.
  - Added credit-score tracking coverage for crafted below-minimum and above-maximum scores at the debt-tools route.
  - Added payment-reminder coverage for crafted negative notification lead times before reminder scheduling.
  - Added competition create-form validation that requires portfolio goals to be greater than the starting balance.
  - Rejected non-finite CSV transaction amounts such as `NaN` and `Infinity` before import rows are bulk-created.
  - Returned a clear CSV import error for invalid UTF-8 files instead of raising during decode.
  - Rejected CSV transaction amounts outside the model's decimal storage range before database bulk-create.

## Next Candidates

1. Turn browser screenshot, keyboard-focus, and color-contrast QA into repeatable tooling if a stable browser dependency is added to the repo.
2. Decide whether generated portfolio-wide recommendations should be persisted with a nullable investment relationship or a separate recommendation target model.
