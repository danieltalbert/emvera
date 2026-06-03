# Session Handoff — Emvera

A running handoff for whoever picks this up next. Everything below is on branch
**`claude/peaceful-carson-Se7n9`** and open as **PR #1** (`danieltalbert/emvera`),
CI green.

## What Emvera is
A Django personal-finance web app: accounts/2FA, data integration (Plaid, CSV,
manual), debt management, investments, savings competitions, an in-app
paper-trading simulator, and a staff-only **analytics + ML platform**. Targets
Python 3.12 / Django 6.0, SQLite by default.

## What was done across this work (high level)
1. **Consolidated** the Emvera code that was split across the
   `Agentic-Coding-Projects` monorepo into this repo (templates, deployment/docs,
   branding → "Emvera"), keeping the more-advanced backend.
2. **QA hardening**: fixed N+1 queries, gated production-security settings
   (`DJANGO_SECURE`), bounded `bulk_create`, leap-day bugfix, removed dead code.
3. **Gated optional integrations** (run with zero keys, light up when configured):
   - Plaid (bank linking), **SnapTrade** (brokerage linking), **Alpaca** (market
     data + paper orders). All lazy-import + `is_configured()`.
   - **Competition paper-trading mode**: competitions can rank by live paper equity.
4. **Apple-esque UI** across all pages: spring motion, scroll-reveal, count-up,
   frosted glass, **light/dark/system theme toggle** (persisted), full
   `prefers-reduced-motion`; redesigned day-trading pages.
5. **Analytics + ML platform** (the big one — app: `analytics/`). Pure-Python ML
   (no numpy/sklearn, offline, unit-tested against known answers):
   - **ML/stats lib**: linear + logistic regression (class-balanced, threshold-
     tuned), honest eval (train/test, k-fold, confusion matrix, precision/recall/
     F1, ROC-AUC), k-means++ + silhouette/elbow, seasonal decomposition + seasonal
     forecast, Holt, EWMA, **Kaplan-Meier survival**, percentiles, regression CIs,
     A/B stats (two-proportion z-test, chi-square, **Bayesian P(B>A)**, sample
     size).
   - **Product analytics**: feature store (+materialization), sessionization,
     activation funnel (+by engagement tier), cohort retention, **churn** model,
     **conversion-propensity** + driver analysis, **engagement health** (RFM),
     stickiness (DAU/WAU/MAU), retention curve, **survival analysis**, Markov
     paths, performance percentiles + slow pages, live-activity panel.
   - **Experimentation**: A/B experiments with significance, a **sequential-
     testing guardrail** (anti-peeking), per-experiment detail pages.
   - **Ops**: anomaly alerting (persisted + emailed), `run_analytics_jobs` runner,
     JSON metrics + live APIs, CSV/PDF export (PDF gated on `reportlab`).
   - **14-section staff dashboard** (`is_staff` gated); privacy-conscious capture
     (salted session hash, never an IP) + client dwell beacons. Seeder + UML docs.
6. **Comments everywhere**: every Python file has a module docstring; every
   template a header comment; migrations carry Django's auto header.
7. **Admin discoverability**: the analytics dashboard is linked from the Django
   admin home (`admin.site.index_template`), in addition to the staff sidebar link.

## Current state / verification
- **210 tests pass** (`python manage.py test`), most in `analytics/tests*.py`.
- `manage.py check` clean; `check --deploy` clean with `DJANGO_SECURE=True`;
  no migration drift; flake8 critical clean.
- 12 Mermaid UML diagrams (in `docs/`) validated with mermaid-cli.
- All viewer pages render 200; dashboard renders all 14 sections.

## How to run / demo locally
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_SECRET_KEY=dev-secret
python manage.py migrate
python manage.py createsuperuser           # is_staff=True -> can see /analytics/
python manage.py seed_analytics --days 60 --visitors 90   # synthetic demo data
python manage.py run_analytics_jobs        # materialize features + check anomalies
python manage.py runserver
# Visit /analytics/ (or the link on the /admin/ home).
```
Tests run on Python 3.12 (Django 6 requires it). In this build environment the
venv lives at `/tmp/venv`; run tests with `DJANGO_SECRET_KEY=x`.

## Key file map (analytics)
- ML library: `analytics/ml.py`, `analytics/metrics.py`, `analytics/ab_test.py`
- Feature store: `analytics/features.py`
- Insights: `analytics/insights.py` (descriptive), `analytics/product_analytics.py`
  (behavioral/predictive), `analytics/conversion.py`, `analytics/health.py`,
  `analytics/experiments.py`
- Capture: `analytics/middleware.py`, `analytics/models.py`
- UI/API: `analytics/views.py`, `analytics/templates/analytics/*.html`
- Commands: `analytics/management/commands/{seed_analytics,check_anomalies,
  materialize_features,run_analytics_jobs}.py`
- Docs/UML: `docs/system-architecture.md`, `docs/analytics-architecture.md`

## Honest caveats / open follow-ups
- **ML metrics are demonstrated on synthetic seed data** designed to be learnable.
  On real traffic the numbers will reflect actual user behavior — the machinery
  and evaluation honesty are correct, but don't read the seeded AUC/lift as
  production truth.
- **Gated dependencies**: PDF export needs `pip install reportlab`; SnapTrade/
  Alpaca/Plaid need their SDKs + keys. All degrade gracefully without them.
- **Compute-on-load**: dashboard insights compute per request. The feature-store
  materialization + `run_analytics_jobs` are the seam for caching/scheduling at
  scale (e.g., precompute nightly, read snapshots). Not yet wired to a scheduler.
- **No real screenshots** were possible in the build sandbox (browser download
  blocked); visual QA was via rendered-HTML previews sent to the user.
- The duplicate Emvera code still physically exists in `Agentic-Coding-Projects`
  (cleanup there was out of scope).
- Possible next features discussed but not built: Celery-beat scheduling, funnel
  path-to-conversion attribution, per-segment cohort retention, a visitor-detail
  explorer page.

## Conventions
- Develop on `claude/peaceful-carson-Se7n9`; commit + push there. Don't open new
  PRs unless asked (PR #1 already tracks this).
- Keep the "gated optional dependency" pattern for anything needing external
  keys/SDKs. Keep ML pure-Python + unit-tested against known answers.
