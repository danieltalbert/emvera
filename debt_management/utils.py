"""
Debt payoff calculators.

All functions work on plain dicts so callers can build them from either a Debt
queryset or arbitrary user input. The shape of a "debt" dict is:

    {
        'id':              <pk or any identifier>,
        'name':            str,
        'balance':         Decimal,
        'interest_rate':   Decimal,   # APR percent, e.g. Decimal('24.99')
        'minimum_payment': Decimal,
    }

The minimum-payment heuristic — used when the Debt model doesn't store one —
is max($25, 2% of balance), which mirrors a typical credit card statement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


def add_months(d: date, months: int) -> date:
    """Add a whole number of months to a date, clamping to month-end if needed."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


CENTS = Decimal('0.01')
MIN_PAYMENT_FLOOR = Decimal('25.00')
MIN_PAYMENT_PCT = Decimal('0.02')
MAX_MONTHS = 600  # 50 years — guard against runaway loops on bad data


def estimate_minimum_payment(balance: Decimal, interest_rate: Decimal) -> Decimal:
    """Heuristic minimum payment when one isn't stored on the Debt record."""
    balance = Decimal(balance or 0)
    if balance <= 0:
        return Decimal('0.00')
    pct = (balance * MIN_PAYMENT_PCT).quantize(CENTS, rounding=ROUND_HALF_UP)
    return max(MIN_PAYMENT_FLOOR, pct)


def debts_from_queryset(qs) -> list[dict]:
    """Convert a Debt queryset to the plain-dict shape used by the calculators."""
    out = []
    for d in qs:
        balance = Decimal(d.balance or 0)
        rate = Decimal(d.interest_rate or 0)
        stored_min = getattr(d, 'minimum_payment', None)
        minimum = Decimal(stored_min) if stored_min else estimate_minimum_payment(balance, rate)
        out.append({
            'id': d.pk,
            'name': d.name,
            'balance': balance,
            'interest_rate': rate,
            'minimum_payment': minimum,
            'due_date': d.due_date,
        })
    return out


@dataclass
class PayoffStep:
    debt_id: object
    name: str
    starting_balance: Decimal
    interest_rate: Decimal
    months_to_payoff: int
    total_interest: Decimal
    total_paid: Decimal
    payoff_date: date


@dataclass
class PayoffPlan:
    strategy: str
    steps: list[PayoffStep] = field(default_factory=list)
    total_interest: Decimal = Decimal('0.00')
    total_paid: Decimal = Decimal('0.00')
    months_to_debt_free: int = 0
    debt_free_date: date | None = None
    extra_payment: Decimal = Decimal('0.00')


def _simulate(
    debts: list[dict],
    order_key,
    extra_payment: Decimal,
    start: date,
) -> PayoffPlan:
    """
    Run a month-by-month simulation:
    - Charge interest on each remaining debt.
    - Pay the minimum on every debt.
    - Throw all remaining "extra" cash at the highest-priority debt.
    - Roll freed-up minimums forward as additional extra payment.
    """
    # Work on copies so we don't mutate caller input.
    remaining = []
    for d in debts:
        if Decimal(d['balance']) <= 0:
            continue
        remaining.append({
            **d,
            'balance': Decimal(d['balance']),
            'interest_rate': Decimal(d['interest_rate']),
            'minimum_payment': Decimal(d['minimum_payment']),
            'paid_interest': Decimal('0.00'),
            'paid_total': Decimal('0.00'),
            'starting_balance': Decimal(d['balance']),
        })

    plan = PayoffPlan(strategy=order_key.__name__, extra_payment=Decimal(extra_payment or 0))
    if not remaining:
        return plan

    extra_pool = Decimal(extra_payment or 0)
    month = 0
    finished_order: list[dict] = []

    while remaining and month < MAX_MONTHS:
        month += 1
        # Accrue interest for this month.
        for d in remaining:
            monthly_rate = d['interest_rate'] / Decimal(100) / Decimal(12)
            interest = (d['balance'] * monthly_rate).quantize(CENTS, rounding=ROUND_HALF_UP)
            d['balance'] += interest
            d['paid_interest'] += interest

        # Pay minimums first.
        leftover = extra_pool
        for d in remaining:
            payment = min(d['minimum_payment'], d['balance'])
            d['balance'] -= payment
            d['paid_total'] += payment
            # Any minimum-payment shortfall (balance < min) leaves cash for the priority debt.
            leftover += (d['minimum_payment'] - payment)

        # Target the highest-priority surviving debt with the leftover.
        priority = sorted(remaining, key=order_key)
        for target in priority:
            if leftover <= 0:
                break
            pay = min(leftover, target['balance'])
            target['balance'] -= pay
            target['paid_total'] += pay
            leftover -= pay

        # Retire fully-paid debts; roll their minimum into the extra pool.
        survivors = []
        payoff_date = add_months(start, month)
        for d in remaining:
            if d['balance'] <= Decimal('0.005'):
                extra_pool += d['minimum_payment']
                d['months_to_payoff'] = month
                d['payoff_date'] = payoff_date
                finished_order.append(d)
            else:
                survivors.append(d)
        remaining = survivors

    # Anything still outstanding after MAX_MONTHS — record it without a payoff date.
    payoff_date = add_months(start, month)
    for d in remaining:
        d['months_to_payoff'] = month
        d['payoff_date'] = None
        finished_order.append(d)

    for d in finished_order:
        plan.steps.append(PayoffStep(
            debt_id=d['id'],
            name=d['name'],
            starting_balance=d['starting_balance'].quantize(CENTS),
            interest_rate=d['interest_rate'],
            months_to_payoff=d['months_to_payoff'],
            total_interest=d['paid_interest'].quantize(CENTS),
            total_paid=d['paid_total'].quantize(CENTS),
            payoff_date=d.get('payoff_date'),
        ))
        plan.total_interest += d['paid_interest']
        plan.total_paid += d['paid_total']

    plan.total_interest = plan.total_interest.quantize(CENTS)
    plan.total_paid = plan.total_paid.quantize(CENTS)
    plan.months_to_debt_free = month
    plan.debt_free_date = add_months(start, month) if finished_order else None
    return plan


def _avalanche_key(d):
    # Highest interest rate first.
    return (-d['interest_rate'], d['balance'])


def _snowball_key(d):
    # Smallest balance first.
    return (d['balance'], -d['interest_rate'])


def avalanche_plan(debts: Iterable[dict], extra_payment=Decimal('0.00'), start=None) -> PayoffPlan:
    plan = _simulate(list(debts), _avalanche_key, extra_payment, start or date.today())
    plan.strategy = 'avalanche'
    return plan


def snowball_plan(debts: Iterable[dict], extra_payment=Decimal('0.00'), start=None) -> PayoffPlan:
    plan = _simulate(list(debts), _snowball_key, extra_payment, start or date.today())
    plan.strategy = 'snowball'
    return plan


def custom_plan(debts: Iterable[dict], order_ids: list, extra_payment=Decimal('0.00'), start=None) -> PayoffPlan:
    """
    Honour a user-supplied ordering of debt IDs. Anything not in the list keeps
    its original relative order at the end.
    """
    debts = list(debts)
    rank = {str(did): idx for idx, did in enumerate(order_ids)}
    fallback = {str(d['id']): 10_000 + idx for idx, d in enumerate(debts)}

    def key(d):
        return (rank.get(str(d['id']), fallback[str(d['id'])]),)

    plan = _simulate(debts, key, extra_payment, start or date.today())
    plan.strategy = 'custom'
    return plan


def weighted_average_apr(debts: Iterable[dict]) -> Decimal:
    """Balance-weighted APR across all debts."""
    debts = list(debts)
    total_balance = sum((Decimal(d['balance']) for d in debts), Decimal('0'))
    if total_balance <= 0:
        return Decimal('0.00')
    weighted = sum(
        (Decimal(d['balance']) * Decimal(d['interest_rate']) for d in debts),
        Decimal('0'),
    )
    return (weighted / total_balance).quantize(Decimal('0.01'))


def total_minimum_payment(debts: Iterable[dict]) -> Decimal:
    return sum((Decimal(d['minimum_payment']) for d in debts), Decimal('0.00')).quantize(CENTS)


def recommend_consolidation(debts: Iterable[dict]) -> dict:
    """
    Pick which consolidation option to highlight given the user's debt profile.

    Heuristic:
    - <= $15k of mostly credit-card debt and a reasonable APR → balance transfer card.
    - Larger amounts or mixed types → personal loan.
    - Very large balances (>$30k) → home equity loan.
    """
    debts = list(debts)
    total_balance = sum((Decimal(d['balance']) for d in debts), Decimal('0'))
    if total_balance <= 0:
        return {'option': None, 'reason': 'No debts to consolidate.'}

    avg_apr = weighted_average_apr(debts)

    if total_balance > Decimal('30000'):
        return {
            'option': 'home_equity',
            'reason': f'Your total debt of ${total_balance:,.2f} is large enough that a home equity loan may unlock the lowest rate. Weighted APR today: {avg_apr}%.',
        }
    if total_balance <= Decimal('15000') and avg_apr >= Decimal('15'):
        return {
            'option': 'balance_transfer',
            'reason': f'A 0% intro APR balance transfer card could eliminate ${total_balance:,.2f} of high-rate debt (current weighted APR: {avg_apr}%).',
        }
    return {
        'option': 'personal_loan',
        'reason': f'A fixed-rate personal loan can simplify ${total_balance:,.2f} across {len(debts)} accounts into one predictable payment (current weighted APR: {avg_apr}%).',
    }
