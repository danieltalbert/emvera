"""
SnapTrade integration — OPTIONAL, gated, and lazy-loaded.

WHY THIS FILE EXISTS
--------------------
This is the "Plaid for brokerages." SnapTrade lets a user securely connect a
brokerage account they ALREADY have (Robinhood, Schwab, Webull, Fidelity, …) so
Emvera can read their real holdings — and, later, place trades. It's the piece
that would let a competition track real portfolios in (near) live time, exactly
analogous to how Plaid links a user's existing bank.

Why not Alpaca for this? Alpaca is itself a broker; it cannot read a user's
*external* brokerage. SnapTrade is the aggregator that can. The two are
complementary: SnapTrade tells us WHAT a user holds; Alpaca market data
(alpaca_client.py) can price it live.

FLOW (once keys exist)
----------------------
  1. register_user(user)                        -> get a per-user `userSecret`
  2. build_connection_portal_url(user, secret)  -> send the user there to
                                                   authorize their brokerage
  3. list_accounts / list_holdings(...)         -> read connected accounts +
                                                   positions; brokerage_sync.py
                                                   upserts them into Emvera's
                                                   Account / Investment models.

NOTHING HERE RUNS WITHOUT KEYS
------------------------------
`is_configured()` is False until SNAPTRADE_CLIENT_ID / SNAPTRADE_CONSUMER_KEY
are set, and the SDK is imported lazily, so the project and tests run without a
SnapTrade account or the `snaptrade-python-sdk` package installed.

NOTE FOR WHOEVER WIRES THIS UP
------------------------------
The exact response shapes from the SnapTrade SDK should be verified against the
current SDK/docs when you add keys — the field mapping below follows SnapTrade's
documented structure but SDKs evolve. It is intentionally defensive (.get with
defaults) so a shape change degrades to empty data rather than a 500.
"""
from __future__ import annotations

import os


class SnapTradeNotConfigured(RuntimeError):
    """Raised when SnapTrade is used but credentials / SDK aren't available."""


def is_configured() -> bool:
    """True only when both SnapTrade credentials are present in the environment."""
    return bool(
        os.environ.get('SNAPTRADE_CLIENT_ID') and os.environ.get('SNAPTRADE_CONSUMER_KEY')
    )


def _client():
    if not is_configured():
        raise SnapTradeNotConfigured(
            'Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY to use SnapTrade.'
        )
    try:
        from snaptrade_client import SnapTrade
    except ImportError as exc:
        raise SnapTradeNotConfigured(
            'snaptrade-python-sdk is not installed. '
            'Run `pip install snaptrade-python-sdk` to enable brokerage linking.'
        ) from exc
    return SnapTrade(
        client_id=os.environ['SNAPTRADE_CLIENT_ID'],
        consumer_key=os.environ['SNAPTRADE_CONSUMER_KEY'],
    )


def snaptrade_user_id(user) -> str:
    """Opaque, stable, unique id we present to SnapTrade for this Emvera user."""
    return f'emvera-{user.pk}'


def register_user(user) -> dict:
    """Register the Emvera user with SnapTrade; returns {user_id, user_secret}.

    The `user_secret` must be stored encrypted and replayed on every later call
    — see data_integration.models.BrokerageLink.
    """
    resp = _client().authentication.register_snap_trade_user(
        body={'userId': snaptrade_user_id(user)}
    )
    data = resp.body
    return {'user_id': data['userId'], 'user_secret': data['userSecret']}


def build_connection_portal_url(user, user_secret: str) -> str:
    """Return a SnapTrade connection-portal URL to redirect the user to."""
    resp = _client().authentication.login_snap_trade_user(
        query_params={'userId': snaptrade_user_id(user), 'userSecret': user_secret}
    )
    body = resp.body
    # The portal URL key has been documented as both redirectURI and redirectURL.
    return body.get('redirectURI') or body.get('redirectURL') or ''


def list_accounts(user, user_secret: str) -> list[dict]:
    """Normalized list of brokerage accounts the user has connected."""
    resp = _client().account_information.list_user_accounts(
        query_params={'userId': snaptrade_user_id(user), 'userSecret': user_secret}
    )
    accounts = resp.body or []
    return [
        {
            'account_id': a.get('id', ''),
            'name': a.get('name') or a.get('institution_name') or 'Brokerage',
            'institution': a.get('institution_name', ''),
            'number': a.get('number', ''),
        }
        for a in accounts
    ]


def list_holdings(user, user_secret: str, account_id: str) -> list[dict]:
    """Normalized positions for one connected brokerage account.

    Returns a list of {symbol, quantity, price} dicts. Defensive about the
    nested symbol structure SnapTrade returns.
    """
    resp = _client().account_information.get_user_holdings(
        account_id=account_id,
        query_params={'userId': snaptrade_user_id(user), 'userSecret': user_secret},
    )
    body = resp.body if isinstance(resp.body, dict) else {}
    out: list[dict] = []
    for pos in body.get('positions', []) or []:
        out.append({
            'symbol': _extract_symbol(pos),
            'quantity': pos.get('units') or pos.get('quantity') or 0,
            'price': pos.get('price') or 0,
        })
    return out


def _extract_symbol(position: dict) -> str:
    """Dig the ticker out of SnapTrade's nested symbol object.

    Shape is roughly position['symbol']['symbol']['symbol']; we walk it
    defensively so a structural change yields '' rather than raising.
    """
    node = position.get('symbol')
    for _ in range(4):
        if isinstance(node, str):
            return node.upper()
        if isinstance(node, dict):
            node = node.get('symbol') or node.get('raw_symbol') or node.get('ticker')
        else:
            break
    return node.upper() if isinstance(node, str) else ''
