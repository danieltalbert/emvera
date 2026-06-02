# Emvera — System Architecture & UML

A whole-application view: the Django apps, their domain models, the request
lifecycle, and the optional third-party integrations. Companion to
[analytics-architecture.md](analytics-architecture.md), which drills into the
analytics/ML subsystem. All diagrams are Mermaid and render on GitHub.

---

## 1. App / component map

Emvera is one Django project (`core`) composed of focused apps. `data_integration`
owns the canonical financial models; feature apps build on top.

```mermaid
flowchart LR
    subgraph core["core (project)"]
        settings
        urls
    end

    accounts["accounts<br/>auth · 2FA · onboarding"]
    DI["data_integration<br/>Account · Transaction · Investment · Debt"]
    debt["debt_management<br/>payoff · reminders · credit"]
    inv["investments<br/>projections · recommendations"]
    comp["competition<br/>contests · mini-game"]
    paper["paper_trading<br/>simulated brokerage"]
    analytics["analytics<br/>page views · ML dashboard"]

    core --> accounts
    core --> DI
    core --> debt
    core --> inv
    core --> comp
    core --> paper
    core --> analytics

    debt --> DI
    inv --> DI
    comp --> paper
    paper --> DI
    analytics -. "logs all viewer requests" .-> core

    subgraph external["Optional integrations (gated, no keys required)"]
        plaid["Plaid<br/>bank linking"]
        snap["SnapTrade<br/>brokerage linking"]
        alpaca["Alpaca<br/>market data + paper orders"]
    end
    DI -. "lazy / gated" .-> plaid
    DI -. "lazy / gated" .-> snap
    paper -. "lazy / gated" .-> alpaca
```

---

## 2. Domain model (ER)

The core financial entities and the apps that extend them.

```mermaid
erDiagram
    CUSTOM_USER ||--o{ ACCOUNT : owns
    CUSTOM_USER ||--o{ PLAID_ITEM : links
    CUSTOM_USER ||--o{ BROKERAGE_LINK : links
    ACCOUNT ||--o{ TRANSACTION : has
    ACCOUNT ||--o{ INVESTMENT : has
    ACCOUNT ||--o{ DEBT : has
    INVESTMENT ||--o{ INVESTMENT_PROJECTION : projects
    INVESTMENT ||--o{ INVESTMENT_RECOMMENDATION : suggests
    CUSTOM_USER ||--o{ CREDIT_SCORE : tracks
    CUSTOM_USER ||--o{ PAYMENT_REMINDER : sets
    CUSTOM_USER ||--o{ PAPER_ACCOUNT : trades
    PAPER_ACCOUNT ||--o{ PAPER_POSITION : holds
    PAPER_ACCOUNT ||--o{ PAPER_ORDER : places
    COMPETITION ||--o{ COMPETITION_PARTICIPANT : has
    COMPETITION ||--o{ PAPER_ACCOUNT : "scores (paper mode)"
    CUSTOM_USER ||--o{ PAGE_VIEW : generates

    ACCOUNT {
        int id PK
        string name
        string type "checking·savings·credit·investment·debt"
        string institution
    }
    DEBT {
        int id PK
        decimal balance
        decimal interest_rate
        decimal minimum_payment
    }
    INVESTMENT {
        int id PK
        string symbol
        decimal value
        decimal quantity
    }
    PAPER_ACCOUNT {
        int id PK
        decimal cash
        decimal starting_cash
        int competition_id FK "null = practice"
    }
```

---

## 3. Domain logic (class diagram — competition × paper trading)

How a competition optionally rides on the paper-trading engine.

```mermaid
classDiagram
    class Competition {
        +str name
        +str status
        +decimal investment_goal
        +bool uses_paper_trading
        +start()
        +finish()
    }
    class CompetitionParticipant {
        +decimal portfolio_value
        +int mini_game_wins
    }
    class PaperAccount {
        +decimal cash
        +decimal starting_cash
        +holdings_value(prices) decimal
        +equity(prices) decimal
    }
    class PaperPosition {
        +str symbol
        +decimal quantity
        +decimal avg_cost
    }
    class services {
        <<module>>
        +ensure_paper_accounts(competition)
        +refresh_standings(competition)
    }

    Competition "1" --> "many" CompetitionParticipant
    Competition "1" --> "many" PaperAccount : "paper mode"
    PaperAccount "1" --> "many" PaperPosition
    services ..> Competition : updates standings
    services ..> PaperAccount : reads equity
    Competition ..> services : start() provisions
```

---

## 4. Request lifecycle (sequence)

A typical authenticated, 2FA-gated page request — including analytics logging.

```mermaid
sequenceDiagram
    autonumber
    participant Br as Browser
    participant Sec as SecurityMiddleware
    participant Auth as AuthMiddleware
    participant App as View (require_2fa)
    participant An as PageViewMiddleware
    participant DB as Database

    Br->>Sec: GET /paper-trading/
    Sec->>Auth: (HTTPS, headers ok)
    Auth->>App: request.user resolved
    App->>App: require_2fa check
    alt 2FA not set up
        App-->>Br: redirect to /accounts/two-factor/setup/
    else authorized
        App->>DB: read PaperAccount / positions
        App-->>An: HttpResponse 200 (text/html)
        An->>DB: INSERT PageView (async-safe, best-effort)
        An-->>Br: response
    end
```

---

## 5. Optional integration gating (state)

Every third-party integration follows the same safe lifecycle: it is inert
until configured, so the app and tests run with zero keys.

```mermaid
stateDiagram-v2
    [*] --> NotConfigured
    NotConfigured --> Configured : env keys present (is_configured() == true)
    Configured --> SDKMissing : import fails
    SDKMissing --> NotConfigured : pip install <sdk>
    Configured --> Live : API call succeeds
    Live --> Configured : idle

    NotConfigured : NotConfigured
    NotConfigured : UI shows an explainer
    NotConfigured : actions no-op gracefully
    Live : Live
    Live : real data flows (Plaid / SnapTrade / Alpaca)
```

---

## 6. App responsibilities

| App | Owns | Depends on |
| --- | --- | --- |
| `accounts` | CustomUser, auth, 2FA, onboarding | — |
| `data_integration` | Account/Transaction/Investment/Debt, Plaid, SnapTrade, CSV, crypto | accounts |
| `debt_management` | payoff math, reminders, credit score | data_integration |
| `investments` | projections, recommendations, performance | data_integration |
| `competition` | contests, mini-game, paper-mode wiring | paper_trading |
| `paper_trading` | simulated brokerage (accounts/positions/orders) | data_integration, Alpaca |
| `analytics` | page-view capture, ML insights dashboard | all (observes), accounts (is_staff) |

See each app's module docstrings for the detailed rationale, and
[analytics-architecture.md](analytics-architecture.md) for the ML internals.
