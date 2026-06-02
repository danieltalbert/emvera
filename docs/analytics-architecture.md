# Emvera Analytics & ML — Architecture & UML

This document describes the `analytics` app: how user activity is captured,
how the pure-Python ML toolkit turns it into intuition, and how it all reaches
the staff dashboard. All diagrams are [Mermaid](https://mermaid.js.org/) and
render directly on GitHub.

> **Design ethos.** Everything here is dependency-free (no numpy/sklearn) so it
> runs offline and the math is auditable. Each algorithm is implemented from
> first principles in `analytics/ml.py` and `analytics/metrics.py`, and unit-
> tested against closed-form answers.

---

## 1. Component overview

How the pieces fit together, from an HTTP request to a rendered insight.

```mermaid
flowchart TB
    subgraph Request path
        U[Visitor request] --> MW[PageViewMiddleware]
        MW --> V[Viewer page response]
        V -. "sendBeacon dwell time" .-> BE[beacon endpoint]
    end
    MW -- "append-only INSERT" --> PV[(PageView table)]
    BE -- "UPDATE dwell_ms by token" --> PV

    subgraph "Insight layer (read-only)"
        PV --> FS[features.py<br/>feature store]
        PV --> INS[insights.py<br/>descriptive]
        PV --> PA[product_analytics.py<br/>sessions · funnel · cohorts · churn]
        FS --> PA
        FS --> INS
        PA --> ML[ml.py<br/>regression · kmeans++ · logistic]
        INS --> ML
        PA --> MET[metrics.py<br/>train/test · ROC-AUC · F1]
        AB[ab_test.py<br/>z-test · Bayesian] --> EXP[experiments.py]
    end

    INS --> VIEW["views.dashboard<br/>staff_member_required"]
    PA --> VIEW
    EXP --> VIEW
    AL[(AnomalyAlert)] --> VIEW
    VIEW --> TPL[dashboard.html<br/>Chart.js + design system]
    VIEW --> REP[reporting.py<br/>CSV always · PDF if reportlab]
    TPL --> STAFF[Staff user]
    REP --> STAFF

    SEED[seed_analytics] -. "synthetic demo data" .-> PV
    CHK[check_anomalies<br/>scheduled] -- "raises" --> AL
    MAT[materialize_features<br/>scheduled] -. "caches" .-> VF[(VisitorFeatures)]
    FS --> VF
```

---

## 2. Data model (ER)

A single denormalized event table backs every insight. Time parts are
pre-extracted at write time so grouping is a cheap `GROUP BY`.

```mermaid
erDiagram
    CUSTOM_USER ||--o{ PAGE_VIEW : "generates (when signed in)"
    EXPERIMENT ||--o{ EXPERIMENT_ASSIGNMENT : "buckets visitors"
    PAGE_VIEW {
        bigint   id PK
        int      user_id FK "null for anonymous"
        string   session_hash "salted SHA-256, never the raw key/IP"
        string   path
        string   section "friendly group, e.g. 'Investments'"
        int      response_ms
        bool     is_authenticated
        string   view_token "per-view id for the dwell beacon"
        int      dwell_ms "time-on-page from the client beacon"
        datetime timestamp
        smallint hour "0-23 UTC, denormalized"
        smallint weekday "0=Mon..6=Sun, denormalized"
    }
    VISITOR_FEATURES {
        string visitor_key PK "materialized feature snapshot"
        json   features "name -> value (from FEATURE_REGISTRY)"
        int    recency_days
        datetime computed_at
    }
    EXPERIMENT {
        string key PK "stable id used for hashing"
        string name
        string status "running | stopped"
    }
    EXPERIMENT_ASSIGNMENT {
        int    experiment_id FK
        string visitor_key
        smallint variant "0=control, 1=variant"
        bool   converted
    }
    ANOMALY_ALERT {
        string metric
        date   date "unique with metric (dedup)"
        float  z_score
        string direction "spike | dip"
        bool   acknowledged
    }
    CUSTOM_USER {
        int     id PK
        bool    is_staff "gates the dashboard"
    }
```

**Privacy note.** Anonymous visitors are identified only by
`sha256(SECRET_KEY + session_key)`. That is stable enough to count distinct
visitors and build per-visitor features, but is non-reversible and stores no IP
or raw session id.

---

## 3. ML toolkit (class diagram)

The reusable, hand-rolled algorithms. Dataclasses carry fitted parameters;
free functions do the stateless work.

```mermaid
classDiagram
    class LinearModel {
        +float slope
        +float intercept
        +float r_squared
        +predict(x) float
    }
    class RegressionCI {
        +LinearModel model
        +float se_slope
        +float se_intercept
        +slope_ci95() tuple
        +slope_is_significant() bool
    }
    class Anomaly {
        +int index
        +float value
        +float z
        +str direction
    }
    class KMeansResult {
        +list~int~ labels
        +list centroids
        +float inertia
        +list~int~ sizes
    }
    class LogisticRegression {
        +list~float~ weights
        +float bias
        +list~float~ loss_history
        +fit(X, y, lr, epochs, l2, class_weight) LogisticRegression
        +predict_proba(x) float
        +predict(x, threshold) int
    }

    RegressionCI --> LinearModel : wraps

    class ml_functions {
        <<module functions>>
        +linear_regression(xs, ys) LinearModel
        +linear_regression_ci(xs, ys) RegressionCI
        +forecast_linear(series, horizon) list
        +holt_forecast(series, horizon, a, b) list
        +ewma(series, alpha) list
        +zscore_anomalies(series, thr) list~Anomaly~
        +kmeans(points, k) KMeansResult
        +silhouette_score(points, labels) float
        +choose_k_elbow(points) dict
        +pearson_correlation(xs, ys) float
        +standardize(rows) list
        +sigmoid(z) float
    }
    ml_functions ..> LinearModel
    ml_functions ..> KMeansResult
    ml_functions ..> Anomaly
```

### Evaluation suite (`metrics.py`)

```mermaid
classDiagram
    class ConfusionMatrix {
        +int tp
        +int fp
        +int fn
        +int tn
        +total() int
    }
    class ClassifierReport {
        +float accuracy
        +float precision
        +float recall
        +float f1
        +float roc_auc
        +ConfusionMatrix confusion
        +int n_test
        +float positive_rate
        +as_dict() dict
    }
    class metrics_functions {
        <<module functions>>
        +train_test_split(X, y, frac, seed)
        +kfold_indices(n, k, seed)
        +confusion_matrix(y_true, y_pred) ConfusionMatrix
        +precision(cm) float
        +recall(cm) float
        +f1_score(cm) float
        +roc_auc(y_true, scores) float
        +evaluate_classifier(y_true, scores, thr) ClassifierReport
    }
    ClassifierReport --> ConfusionMatrix : contains
    metrics_functions ..> ClassifierReport
    metrics_functions ..> ConfusionMatrix
```

---

## 4. Request logging (sequence)

What happens on every viewer request.

```mermaid
sequenceDiagram
    autonumber
    participant Br as Browser
    participant MW as PageViewMiddleware
    participant Vw as View
    participant DB as PageView table

    Br->>MW: GET /investments/
    MW->>MW: start = monotonic()
    MW->>Vw: get_response(request)
    Vw-->>MW: HttpResponse (200, text/html)
    MW->>MW: skip? (admin/static/analytics, non-GET, non-HTML)
    alt loggable
        MW->>MW: section_for(path), session_hash(salted)
        MW->>DB: INSERT PageView (path, section, ms, hour, weekday…)
    end
    MW-->>Br: response (unchanged)
    note over MW: logging is wrapped in try/except —<br/>analytics can never break a request
```

---

## 5. Churn model pipeline (sequence)

The end-to-end flow that produces the dashboard's Churn Risk panel — including
the ML best-practices that make it trustworthy.

```mermaid
sequenceDiagram
    autonumber
    participant V as views.dashboard
    participant PA as product_analytics.churn_model
    participant F as engagement_features
    participant ML as ml.LogisticRegression
    participant MT as metrics

    V->>PA: churn_model(days)
    PA->>F: engagement_features(days)
    F-->>PA: visitor_ids, raw_features, meta(recency)
    PA->>PA: label = recency >= churn_after_days
    PA->>PA: drop 'recency' feature (avoid label leakage)
    PA->>ML: standardize -> train_test_split
    PA->>ML: fit(class_weight='balanced')  %% imbalance fix
    PA->>PA: tune threshold to max F1 on TRAIN scores
    PA->>MT: evaluate_classifier(y_test, test_scores, thr)
    MT-->>PA: ROC-AUC, precision, recall, F1, confusion
    PA->>PA: standardized weights -> feature importances
    PA-->>V: report + importances + at-risk visitors
```

Key best-practices encoded above:

| Concern | Mitigation in code |
| --- | --- |
| **Label leakage** | `recency` defines the label, so it is removed from the feature inputs. |
| **Class imbalance** (few churners) | `class_weight='balanced'` + F1-tuned decision threshold. |
| **Optimistic scoring** | Metrics are computed on a held-out test split, never the training rows. |
| **Threshold-independent quality** | ROC-AUC reported alongside precision/recall/F1. |
| **Interpretability** | Standardized coefficients surfaced as signed feature importances. |
| **Reproducibility** | Fixed seeds in split, k-means++, and the seeder. |

---

## 6. Insight catalog

What each dashboard section answers, and the technique behind it.

```mermaid
mindmap
  root((Analytics))
    Descriptive
      KPIs
      Daily traffic
        OLS trend + r²
        Linear / Holt forecast
        Z-score anomalies
      Top pages
        Time-on-page (beacon)
      Activity heatmap
      Peak timing
    Behavioral
      Sessionization
        Bounce rate
        Depth histogram
      Activation funnel
      Cohort retention
      Markov path analysis
    Predictive / ML
      Feature store
        named registry
        materialized cache
      User segments
        k-means++
        silhouette / elbow
      Churn risk
        Logistic regression
        Class-balanced
        Held-out eval
    Experimentation
      A/B testing
        two-proportion z-test
        Bayesian P(B>A)
        sample-size calc
    Operations
      Anomaly alerting
        persist + email
      Report export
        CSV / PDF
```

---

## 7. Where to look in the code

| Concern | File |
| --- | --- |
| Event capture + dwell token | `analytics/middleware.py` |
| Event schema + models | `analytics/models.py` |
| ML fundamentals | `analytics/ml.py` |
| Model evaluation | `analytics/metrics.py` |
| Feature store | `analytics/features.py` |
| Descriptive insights | `analytics/insights.py` |
| Behavioral / predictive | `analytics/product_analytics.py` |
| A/B statistics | `analytics/ab_test.py` |
| A/B runtime | `analytics/experiments.py` |
| Report export (CSV/PDF) | `analytics/reporting.py` |
| Dashboard + beacon + export views | `analytics/views.py` |
| Dashboard UI | `analytics/templates/analytics/dashboard.html` |
| Demo data | `management/commands/seed_analytics.py` |
| Anomaly alerting (cron) | `management/commands/check_anomalies.py` |
| Feature materialization (cron) | `management/commands/materialize_features.py` |
| Tests | `analytics/tests*.py` (8 modules, 81 cases) |

Run the demo locally:

```bash
python manage.py migrate
python manage.py seed_analytics --days 45 --visitors 90
python manage.py createsuperuser   # so you can reach /analytics/ (is_staff)
python manage.py runserver
# visit http://127.0.0.1:8000/analytics/
```
