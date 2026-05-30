"""
Alpaca integration — OPTIONAL, gated, and lazy-loaded.

WHY THIS FILE EXISTS
--------------------
Emvera is keeping two possible "live investing" directions open (the product
decision hasn't been made yet). Alpaca plays a role in BOTH, so it lives here:

  1. Market data (live prices). Alpaca's market-data API returns quotes for a
     symbol using only Emvera's OWN keys (ALPACA_API_KEY / ALPACA_SECRET_KEY) —
     the end user does not need an Alpaca account. This is what lets us value
     holdings, and competition portfolios, in (near) real time no matter where
     the holdings actually live. See data_integration/pricing.py.

  2. Paper trading. Alpaca can place SIMULATED ("paper") orders against a
     virtual account. This backs the in-app paper-trading game in the
     `paper_trading` app — compete on returns with no real money at risk.

WHAT ALPACA IS *NOT*
--------------------
Alpaca is a broker + market-data provider. It CANNOT read positions out of a
user's existing Robinhood / Fidelity / Schwab account. For "link the brokerage
I already have" (the Plaid-for-brokerages model) see snaptrade_client.py.

NOTHING HERE RUNS WITHOUT KEYS
------------------------------
`is_configured()` returns False until the env vars are set, and the `alpaca-py`
SDK is imported lazily inside each function. So the project — and the test
suite — run fine with no Alpaca account, no keys, and the package not installed.
Add the keys (and `pip install alpaca-py`) and these functions light up.
"""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Iterable


class AlpacaNotConfigured(RuntimeError):
    """Raised when Alpaca is used but the keys / SDK aren't available."""


def is_configured() -> bool:
    """True only when both API keys are present in the environment."""
    return bool(os.environ.get('ALPACA_API_KEY') and os.environ.get('ALPACA_SECRET_KEY'))


def is_paper() -> bool:
    """Trade against the PAPER endpoint unless ALPACA_PAPER is explicitly False.

    Defaults to paper so a misconfiguration can never place a real-money order.
    """
    return os.environ.get('ALPACA_PAPER', 'True') != 'False'


def _require() -> None:
    if not is_configured():
        raise AlpacaNotConfigured(
            'Set ALPACA_API_KEY and ALPACA_SECRET_KEY to use Alpaca.'
        )


def _data_client():
    _require()
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError as exc:  # SDK not installed — treat as "not configured".
        raise AlpacaNotConfigured(
            'alpaca-py is not installed. Run `pip install alpaca-py` to enable Alpaca.'
        ) from exc
    return StockHistoricalDataClient(
        os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY']
    )


def _trading_client():
    _require()
    try:
        from alpaca.trading.client import TradingClient
    except ImportError as exc:
        raise AlpacaNotConfigured(
            'alpaca-py is not installed. Run `pip install alpaca-py` to enable Alpaca.'
        ) from exc
    return TradingClient(
        os.environ['ALPACA_API_KEY'], os.environ['ALPACA_SECRET_KEY'], paper=is_paper()
    )


def get_latest_prices(symbols: Iterable[str]) -> dict[str, Decimal]:
    """Return {SYMBOL: latest_price} for the given symbols.

    The single network entry point used for live valuation. Needs only Emvera's
    own Alpaca keys (no end-user account). Returns {} for an empty input.
    """
    symbols = sorted({s.upper().strip() for s in symbols if s and s.strip()})
    if not symbols:
        return {}
    client = _data_client()
    from alpaca.data.requests import StockLatestQuoteRequest

    quotes = client.get_stock_latest_quote(
        StockLatestQuoteRequest(symbol_or_symbols=symbols)
    )
    prices: dict[str, Decimal] = {}
    for sym, quote in quotes.items():
        # Prefer the ask, fall back to the bid; alpaca-py returns these as floats.
        raw = getattr(quote, 'ask_price', None) or getattr(quote, 'bid_price', None)
        if raw:
            prices[sym] = Decimal(str(raw))
    return prices


def submit_paper_order(symbol: str, qty: Decimal, side: str) -> dict:
    """Place a market order on the configured Alpaca account (paper by default).

    `side` is 'buy' or 'sell'. The `paper_trading` app uses this when Alpaca is
    configured and otherwise falls back to its own local simulation, so this is
    only ever reached once keys exist.
    """
    client = _trading_client()
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    order = client.submit_order(MarketOrderRequest(
        symbol=symbol.upper(),
        qty=float(qty),
        side=OrderSide.BUY if side == 'buy' else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    ))
    return {
        'id': str(order.id), 'symbol': order.symbol, 'qty': str(order.qty),
        'side': str(order.side), 'status': str(order.status),
    }


def get_account() -> dict:
    """Snapshot of the configured Alpaca (paper) account: cash, equity, buying power."""
    acct = _trading_client().get_account()
    return {
        'cash': Decimal(str(acct.cash)),
        'equity': Decimal(str(acct.equity)),
        'buying_power': Decimal(str(acct.buying_power)),
    }
