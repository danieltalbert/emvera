from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from data_integration.models import Account, Debt

from .models import PaymentReminder
from debt_management.utils import (
    add_months,
    avalanche_plan,
    custom_plan,
    estimate_minimum_payment,
    recommend_consolidation,
    snowball_plan,
    total_minimum_payment,
    weighted_average_apr,
)


def _debt(id_, name, balance, rate, minimum):
    return {
        'id': id_,
        'name': name,
        'balance': Decimal(balance),
        'interest_rate': Decimal(rate),
        'minimum_payment': Decimal(minimum),
    }


class MinimumPaymentEstimateTests(SimpleTestCase):
    def test_floor_for_small_balances(self):
        self.assertEqual(estimate_minimum_payment(Decimal('100'), Decimal('20')), Decimal('25.00'))

    def test_percentage_kicks_in_for_large_balances(self):
        self.assertEqual(estimate_minimum_payment(Decimal('5000'), Decimal('20')), Decimal('100.00'))

    def test_zero_balance(self):
        self.assertEqual(estimate_minimum_payment(Decimal('0'), Decimal('20')), Decimal('0.00'))


class AddMonthsTests(SimpleTestCase):
    def test_basic(self):
        self.assertEqual(add_months(date(2026, 1, 15), 3), date(2026, 4, 15))

    def test_month_end_clamps(self):
        self.assertEqual(add_months(date(2027, 1, 31), 1), date(2027, 2, 28))

    def test_year_rollover(self):
        self.assertEqual(add_months(date(2026, 11, 1), 5), date(2027, 4, 1))


class AvalancheVsSnowballTests(SimpleTestCase):
    def setUp(self):
        self.debts = [
            _debt(1, 'Card A', '4200',  '24.99', '100'),
            _debt(2, 'Card B', '800',   '14.99', '40'),
            _debt(3, 'Loan',   '12000', '7.5',   '220'),
        ]

    def test_snowball_orders_smallest_balance_first(self):
        plan = snowball_plan(self.debts, extra_payment=Decimal('200'), start=date(2026, 1, 1))
        names = [s.name for s in plan.steps]
        self.assertEqual(names[0], 'Card B')

    def test_avalanche_pays_less_or_equal_interest_vs_snowball(self):
        av = avalanche_plan(self.debts, extra_payment=Decimal('200'))
        sn = snowball_plan(self.debts, extra_payment=Decimal('200'))
        self.assertLessEqual(av.total_interest, sn.total_interest)

    def test_extra_payment_reduces_interest(self):
        no_extra = avalanche_plan(self.debts)
        with_extra = avalanche_plan(self.debts, extra_payment=Decimal('300'))
        self.assertGreater(no_extra.total_interest, with_extra.total_interest)
        self.assertLessEqual(with_extra.months_to_debt_free, no_extra.months_to_debt_free)

    def test_empty_input(self):
        plan = avalanche_plan([])
        self.assertEqual(plan.total_interest, Decimal('0.00'))
        self.assertEqual(plan.months_to_debt_free, 0)
        self.assertIsNone(plan.debt_free_date)
        self.assertEqual(plan.steps, [])


class ZeroRateDebtTests(SimpleTestCase):
    def test_zero_interest_no_interest_charged(self):
        debts = [_debt(1, 'Furniture 0% APR', '1200', '0', '100')]
        plan = avalanche_plan(debts, start=date(2026, 1, 1))
        self.assertEqual(plan.steps[0].total_interest, Decimal('0.00'))
        self.assertEqual(plan.months_to_debt_free, 12)


class CustomPlanTests(SimpleTestCase):
    def test_priority_targets_extras_first(self):
        debts = [
            _debt(1, 'Card A', '5000', '20', '100'),
            _debt(2, 'Card B', '5000', '20', '100'),
        ]
        plan = custom_plan(debts, order_ids=[2, 1], extra_payment=Decimal('200'))
        b = next(s for s in plan.steps if s.name == 'Card B')
        a = next(s for s in plan.steps if s.name == 'Card A')
        self.assertLessEqual(b.months_to_payoff, a.months_to_payoff)


class AggregateHelperTests(SimpleTestCase):
    def test_weighted_average_apr(self):
        debts = [
            _debt(1, 'A', '1000', '20', '25'),
            _debt(2, 'B', '3000', '5',  '50'),
        ]
        self.assertEqual(weighted_average_apr(debts), Decimal('8.75'))

    def test_weighted_average_apr_empty(self):
        self.assertEqual(weighted_average_apr([]), Decimal('0.00'))

    def test_total_minimum_payment(self):
        debts = [
            _debt(1, 'A', '1000', '20', '25'),
            _debt(2, 'B', '3000', '5',  '50'),
        ]
        self.assertEqual(total_minimum_payment(debts), Decimal('75.00'))


class ConsolidationRecommendationTests(SimpleTestCase):
    def test_empty_returns_none(self):
        rec = recommend_consolidation([])
        self.assertIsNone(rec['option'])

    def test_large_balance_picks_home_equity(self):
        debts = [_debt(1, 'Big Loan', '40000', '10', '500')]
        self.assertEqual(recommend_consolidation(debts)['option'], 'home_equity')

    def test_small_high_rate_picks_balance_transfer(self):
        debts = [_debt(1, 'Card', '8000', '24', '150')]
        self.assertEqual(recommend_consolidation(debts)['option'], 'balance_transfer')

    def test_midsize_picks_personal_loan(self):
        debts = [_debt(1, 'Mixed', '20000', '10', '300')]
        self.assertEqual(recommend_consolidation(debts)['option'], 'personal_loan')


class DebtManagementViewsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='testuser',
            password='testpass',
            two_factor_enabled=True,
        )
        self.other_user = get_user_model().objects.create_user(
            username='otheruser',
            password='testpass',
            two_factor_enabled=True,
        )
        self.account = Account.objects.create(
            user=self.user,
            name='Credit Card',
            type='credit',
            institution='Codex Card',
        )
        self.debt = Debt.objects.create(
            account=self.account,
            name='Credit Card Balance',
            principal=Decimal('5000.00'),
            balance=Decimal('4200.00'),
            interest_rate=Decimal('19.99'),
            minimum_payment=Decimal('125.00'),
            due_date=date(2026, 8, 1),
            as_of=date(2026, 7, 9),
        )
        self.other_account = Account.objects.create(
            user=self.other_user,
            name='Other Credit Card',
            type='credit',
            institution='Other Bank',
        )
        self.other_debt = Debt.objects.create(
            account=self.other_account,
            name='Other Credit Card Balance',
            principal=Decimal('2500.00'),
            balance=Decimal('2100.00'),
            interest_rate=Decimal('15.50'),
            minimum_payment=Decimal('75.00'),
            due_date=date(2026, 8, 1),
            as_of=date(2026, 7, 9),
        )
        self.client.login(username='testuser', password='testpass')

    def test_debt_dashboard_view(self):
        response = self.client.get(reverse('debt_management:debt_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/debt_dashboard.html')

    def test_credit_score_tracking_view(self):
        response = self.client.get(reverse('debt_management:credit_score_tracking'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/credit_score_tracking.html')

    def test_consolidation_suggestion_view(self):
        response = self.client.get(reverse('debt_management:consolidation_suggestion'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/consolidation_suggestion.html')

    def test_debt_reminders_view(self):
        response = self.client.get(reverse('debt_management:debt_reminders'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/debt_reminders.html')

    def test_debt_reminders_create_for_selected_user_debt(self):
        response = self.client.post(reverse('debt_management:debt_reminders'), {
            'debt': self.debt.pk,
            'name': 'Credit card payment',
            'institution': '',
            'amount': '125.00',
            'due_date': '2026-08-01',
            'notify_days_before': '3',
        })

        self.assertRedirects(response, reverse('debt_management:debt_reminders'))
        reminder = PaymentReminder.objects.get(user=self.user, debt=self.debt)
        self.assertEqual(reminder.amount, Decimal('125.00'))
        self.assertEqual(reminder.institution, 'Codex Card')

    def test_debt_reminders_reject_another_users_debt(self):
        response = self.client.post(reverse('debt_management:debt_reminders'), {
            'debt': self.other_debt.pk,
            'name': 'Wrong payment',
            'institution': '',
            'amount': '75.00',
            'due_date': '2026-08-01',
            'notify_days_before': '3',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PaymentReminder.objects.filter(debt=self.other_debt).exists())
        self.assertFormError(
            response.context['form'],
            'debt',
            'Select a valid choice. That choice is not one of the available choices.',
        )

    def test_mark_reminder_paid_only_updates_signed_in_users_reminder(self):
        own_reminder = PaymentReminder.objects.create(
            user=self.user,
            debt=self.debt,
            name='Credit card payment',
            institution='Codex Card',
            amount=Decimal('125.00'),
            due_date=date(2026, 8, 1),
        )
        other_reminder = PaymentReminder.objects.create(
            user=self.other_user,
            debt=self.other_debt,
            name='Other payment',
            institution='Other Bank',
            amount=Decimal('75.00'),
            due_date=date(2026, 8, 1),
        )

        response = self.client.post(
            reverse('debt_management:mark_reminder_paid', kwargs={'pk': own_reminder.pk})
        )
        self.assertRedirects(response, reverse('debt_management:debt_reminders'))
        own_reminder.refresh_from_db()
        self.assertTrue(own_reminder.is_paid)
        self.assertEqual(own_reminder.paid_on, date.today())

        response = self.client.post(
            reverse('debt_management:mark_reminder_paid', kwargs={'pk': other_reminder.pk})
        )
        self.assertRedirects(response, reverse('debt_management:debt_reminders'))
        other_reminder.refresh_from_db()
        self.assertFalse(other_reminder.is_paid)
        self.assertIsNone(other_reminder.paid_on)

    def test_payoff_avalanche_view(self):
        response = self.client.get(reverse('debt_management:payoff_avalanche'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/payoff_avalanche.html')

    def test_payoff_snowball_view(self):
        response = self.client.get(reverse('debt_management:payoff_snowball'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/payoff_snowball.html')

    def test_payoff_custom_view(self):
        response = self.client.get(reverse('debt_management:payoff_custom'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'debt_management/payoff_custom.html')
