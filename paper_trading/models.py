"""
Paper-trading models — an in-app SIMULATED brokerage.

WHY THIS APP EXISTS
-------------------
This is the second of Emvera's two "investing" directions (the first being
linking a *real* brokerage via SnapTrade). Here a user gets a virtual cash
balance and trades simulated positions priced by live market data (Alpaca).
It's ideal for the competition feature: everyone starts equal and competes on
returns with no real money at risk.

It is deliberately DECOUPLED from the `competition` app — a PaperAccount may
optionally belong to a Competition, but paper trading also works stand-alone as
a practice account. When/if you decide to power competitions with it, a
participant's standing can be driven by PaperAccount.equity() instead of the
current static `CompetitionParticipant.portfolio_value`. (That wiring is left
out on purpose so competitions keep working unchanged until you choose to.)

Pricing/fills run through paper_trading.execution, which uses Alpaca market data
when configured and otherwise refuses to fill — nothing here fabricates prices.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models


class PaperAccount(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='paper_accounts'
    )
    # Optional: ties this account to one competition. NULL = stand-alone practice.
    competition = models.ForeignKey(
        'competition.Competition', on_delete=models.CASCADE,
        null=True, blank=True, related_name='paper_accounts',
    )
    cash = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('100000.00'))
    starting_cash = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('100000.00'))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One practice account (competition NULL) + at most one per competition.
        unique_together = ('user', 'competition')

    def __str__(self):
        scope = self.competition.name if self.competition_id else 'practice'
        return f"PaperAccount({self.user}, {scope})"

    def holdings_value(self, prices: dict) -> Decimal:
        """Market value of all positions given a {symbol: price} map."""
        total = Decimal('0.00')
        for pos in self.positions.all():
            price = prices.get(pos.symbol.upper())
            if price is not None:
                total += pos.quantity * Decimal(price)
        return total.quantize(Decimal('0.01'))

    def equity(self, prices: dict) -> Decimal:
        """Total account value = cash + market value of holdings."""
        return (self.cash + self.holdings_value(prices)).quantize(Decimal('0.01'))


class PaperPosition(models.Model):
    account = models.ForeignKey(PaperAccount, on_delete=models.CASCADE, related_name='positions')
    symbol = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    avg_cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal('0'))

    class Meta:
        unique_together = ('account', 'symbol')

    def __str__(self):
        return f"{self.symbol} x{self.quantity}"


class PaperOrder(models.Model):
    SIDE_BUY = 'buy'
    SIDE_SELL = 'sell'
    SIDE_CHOICES = [(SIDE_BUY, 'Buy'), (SIDE_SELL, 'Sell')]

    STATUS_FILLED = 'filled'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [(STATUS_FILLED, 'Filled'), (STATUS_REJECTED, 'Rejected')]

    account = models.ForeignKey(PaperAccount, on_delete=models.CASCADE, related_name='orders')
    symbol = models.CharField(max_length=20)
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)
    quantity = models.DecimalField(max_digits=18, decimal_places=6)
    fill_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.side} {self.quantity} {self.symbol} [{self.status}]"
