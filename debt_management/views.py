from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render

from data_integration.models import Debt

from .forms import CreditScoreForm, CustomPayoffForm, PaymentReminderForm
from .models import CreditScore, PaymentReminder
from .utils import (
    avalanche_plan,
    debts_from_queryset,
    recommend_consolidation,
    snowball_plan,
    custom_plan,
    total_minimum_payment,
    weighted_average_apr,
)


def _user_debts(user):
    return Debt.objects.filter(account__user=user).select_related('account')


@login_required
def debt_dashboard(request):
    debt_qs = _user_debts(request.user).order_by('-interest_rate')
    debts = debts_from_queryset(debt_qs)

    total_debt = sum((d['balance'] for d in debts), Decimal('0.00'))
    avg_rate = weighted_average_apr(debts) if debts else None
    monthly_minimum = total_minimum_payment(debts) if debts else Decimal('0.00')

    debt_free_date = None
    if debts:
        plan = avalanche_plan(debts)
        debt_free_date = plan.debt_free_date

    context = {
        'debts': debt_qs,
        'debt_rows': debts,
        'total_debt': total_debt,
        'avg_interest_rate': avg_rate,
        'monthly_minimum': monthly_minimum,
        'debt_free_date': debt_free_date,
        'has_debts': bool(debts),
    }
    return render(request, 'debt_management/debt_dashboard.html', context)


def _extra_payment_from_request(request) -> Decimal:
    raw = request.GET.get('extra') or request.POST.get('extra_payment') or '0'
    try:
        return Decimal(raw)
    except (ValueError, ArithmeticError):
        return Decimal('0.00')


@login_required
def payoff_avalanche(request):
    debts = debts_from_queryset(_user_debts(request.user))
    extra = _extra_payment_from_request(request)
    plan = avalanche_plan(debts, extra_payment=extra) if debts else None
    baseline = avalanche_plan(debts, extra_payment=Decimal('0.00')) if debts else None

    interest_saved = None
    if plan and baseline and extra > 0:
        interest_saved = (baseline.total_interest - plan.total_interest)

    context = {
        'plan': plan,
        'baseline': baseline,
        'extra_payment': extra,
        'interest_saved': interest_saved,
        'has_debts': bool(debts),
    }
    return render(request, 'debt_management/payoff_avalanche.html', context)


@login_required
def payoff_snowball(request):
    debts = debts_from_queryset(_user_debts(request.user))
    extra = _extra_payment_from_request(request)
    plan = snowball_plan(debts, extra_payment=extra) if debts else None
    avalanche_compare = avalanche_plan(debts, extra_payment=extra) if debts else None

    extra_interest_vs_avalanche = None
    if plan and avalanche_compare:
        extra_interest_vs_avalanche = plan.total_interest - avalanche_compare.total_interest

    context = {
        'plan': plan,
        'avalanche_compare': avalanche_compare,
        'extra_interest_vs_avalanche': extra_interest_vs_avalanche,
        'extra_payment': extra,
        'has_debts': bool(debts),
    }
    return render(request, 'debt_management/payoff_snowball.html', context)


@login_required
def payoff_custom(request):
    debt_qs = _user_debts(request.user)
    debts = debts_from_queryset(debt_qs)
    form = CustomPayoffForm(request.POST or None)

    plan = None
    extra = Decimal('0.00')
    if request.method == 'POST' and form.is_valid():
        extra = form.cleaned_data.get('extra_payment') or Decimal('0.00')
        order_raw = form.cleaned_data.get('order') or ''
        order_ids = [token for token in order_raw.split(',') if token]
        plan = custom_plan(debts, order_ids=order_ids, extra_payment=extra) if debts else None
    elif debts:
        plan = avalanche_plan(debts, extra_payment=Decimal('0.00'))

    context = {
        'form': form,
        'plan': plan,
        'debts': debt_qs,
        'extra_payment': extra,
        'has_debts': bool(debts),
    }
    return render(request, 'debt_management/payoff_custom.html', context)


@login_required
def consolidation_suggestion(request):
    debts = debts_from_queryset(_user_debts(request.user))
    recommendation = recommend_consolidation(debts) if debts else None
    context = {
        'recommendation': recommendation,
        'recommended_option': recommendation['option'] if recommendation else None,
        'total_balance': sum((d['balance'] for d in debts), Decimal('0.00')),
        'avg_apr': weighted_average_apr(debts) if debts else None,
        'has_debts': bool(debts),
    }
    return render(request, 'debt_management/consolidation_suggestion.html', context)


@login_required
def credit_score_tracking(request):
    if request.method == 'POST':
        form = CreditScoreForm(request.POST)
        if form.is_valid():
            score = form.save(commit=False)
            score.user = request.user
            score.save()
            messages.success(request, f'Logged credit score of {score.score}.')
            return redirect('debt_management:credit_score_tracking')
    else:
        form = CreditScoreForm(initial={'recorded_on': date.today()})

    scores = CreditScore.objects.filter(user=request.user)
    latest = scores.first()
    history = list(scores.order_by('recorded_on').values('recorded_on', 'score', 'bureau'))

    context = {
        'form': form,
        'latest_score': latest,
        'credit_score': latest.score if latest else None,
        'score_history': history,
        'has_scores': bool(latest),
    }
    return render(request, 'debt_management/credit_score_tracking.html', context)


@login_required
def debt_reminders(request):
    if request.method == 'POST':
        form = PaymentReminderForm(request.POST, user=request.user)
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.user = request.user
            if reminder.debt and not reminder.institution:
                reminder.institution = reminder.debt.account.institution
            reminder.save()
            messages.success(request, f'Reminder added for {reminder.name}.')
            return redirect('debt_management:debt_reminders')
    else:
        form = PaymentReminderForm(user=request.user, initial={'due_date': date.today()})

    today = date.today()
    week_out = today + timedelta(days=7)
    month_out = today + timedelta(days=30)

    open_reminders = PaymentReminder.objects.filter(
        user=request.user,
        is_paid=False,
    ).select_related('debt', 'debt__account').order_by('due_date')

    overdue_count = open_reminders.filter(due_date__lt=today).count()
    due_this_week_count = open_reminders.filter(due_date__gte=today, due_date__lte=week_out).count()
    due_this_month_count = open_reminders.filter(due_date__gte=today, due_date__lte=month_out).count()

    reminders = []
    for r in open_reminders:
        delta_days = (r.due_date - today).days
        reminders.append({
            'obj': r,
            'name': r.name,
            'institution': r.institution or (r.debt.account.institution if r.debt and r.debt.account else ''),
            'due_date': r.due_date,
            'amount': r.amount,
            'days_until_due': delta_days,
            'is_overdue': delta_days < 0,
        })

    context = {
        'form': form,
        'reminders': reminders,
        'overdue_count': overdue_count,
        'due_this_week_count': due_this_week_count,
        'due_this_month_count': due_this_month_count,
    }
    return render(request, 'debt_management/debt_reminders.html', context)


@login_required
def mark_reminder_paid(request, pk):
    if request.method != 'POST':
        return redirect('debt_management:debt_reminders')
    try:
        reminder = PaymentReminder.objects.get(pk=pk, user=request.user)
    except PaymentReminder.DoesNotExist:
        messages.error(request, 'Reminder not found.')
        return redirect('debt_management:debt_reminders')
    reminder.is_paid = True
    reminder.paid_on = date.today()
    reminder.save(update_fields=['is_paid', 'paid_on', 'updated_at'])
    messages.success(request, f'Marked “{reminder.name}” paid.')
    return redirect('debt_management:debt_reminders')
