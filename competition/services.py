"""
Bridge between competitions and the paper-trading simulator.

WHY THIS EXISTS
---------------
When a Competition has `uses_paper_trading=True`, players compete on the live
value of a SIMULATED portfolio instead of mini-game bonuses. This module:

  * ensure_paper_accounts() — gives each participant a competition-scoped
    PaperAccount seeded with the starting balance (called from Competition.start).
  * refresh_standings() — recomputes each participant's `portfolio_value` from
    their live paper-account equity (cash + holdings priced via Alpaca, falling
    back to cost basis when Alpaca isn't configured). Because the existing
    leaderboard already orders by and displays `portfolio_value`, writing equity
    there means the live standings "just work" with no template changes.

It lives in the competition app (not paper_trading) because paper_trading must
not depend on competition beyond its optional FK; the dependency points one way.
"""
from __future__ import annotations

from decimal import Decimal

from data_integration import alpaca_client


def ensure_paper_accounts(competition):
    """Create one competition-scoped PaperAccount per participant (idempotent)."""
    from paper_trading.models import PaperAccount
    for participant in competition.participants.select_related('user'):
        PaperAccount.objects.get_or_create(
            user=participant.user,
            competition=competition,
            defaults={
                'cash': competition.starting_balance,
                'starting_cash': competition.starting_balance,
            },
        )


def get_account(competition, user):
    """Get (or lazily create) the competition paper account for one user."""
    from paper_trading.models import PaperAccount
    account, _ = PaperAccount.objects.get_or_create(
        user=user,
        competition=competition,
        defaults={
            'cash': competition.starting_balance,
            'starting_cash': competition.starting_balance,
        },
    )
    return account


def _price_map(accounts) -> dict:
    """Build {symbol: price} across all positions in the given paper accounts.

    Uses live Alpaca quotes when configured; otherwise falls back to each
    position's average cost so equity stays meaningful (and deterministic in
    tests) with no market-data connection.
    """
    fallback: dict[str, Decimal] = {}
    symbols: set[str] = set()
    for account in accounts:
        for pos in account.positions.all():
            sym = pos.symbol.upper()
            symbols.add(sym)
            fallback.setdefault(sym, Decimal(pos.avg_cost))
    if not symbols:
        return {}

    live = {}
    if alpaca_client.is_configured():
        try:
            live = alpaca_client.get_latest_prices(symbols)
        except alpaca_client.AlpacaNotConfigured:
            live = {}
    # Live price wins; fall back to cost basis for anything not quoted.
    return {sym: live.get(sym, fallback[sym]) for sym in symbols}


def refresh_standings(competition) -> dict:
    """Sync each participant's portfolio_value from live paper equity.

    No-op for classic (non-paper) competitions. Auto-finishes the competition if
    a player has reached the investment goal. Returns the price map used.
    """
    if not competition.uses_paper_trading:
        return {}

    from paper_trading.models import PaperAccount
    participants = list(competition.participants.select_related('user'))
    accounts = {
        a.user_id: a
        for a in PaperAccount.objects.filter(competition=competition).prefetch_related('positions')
    }
    prices = _price_map(accounts.values())

    for participant in participants:
        account = accounts.get(participant.user_id)
        if account is None:
            continue
        equity = account.equity(prices)
        if participant.portfolio_value != equity:
            participant.portfolio_value = equity
            participant.save(update_fields=['portfolio_value'])

    # Self-resolve: first player to reach the goal wins.
    if competition.status == competition.STATUS_ACTIVE and participants:
        leader = max(participants, key=lambda p: p.portfolio_value)
        if leader.portfolio_value >= competition.investment_goal:
            competition.finish()

    return prices
