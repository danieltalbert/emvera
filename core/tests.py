from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from competition.models import Competition, CompetitionParticipant, MiniGame
from core.settings import env_bool
from data_integration.models import Account, Debt, Investment


class RenderedAccessibilityParser(HTMLParser):
    VOID_TAGS = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden_stack = []
        self.current_heading = None
        self.heading_text = []
        self.visible_h1s = []
        self.labels_for = set()
        self.label_depth = 0
        self.controls = []
        self.buttons = []
        self.current_button = None
        self.button_text = []

    def _attrs(self, attrs):
        return dict(attrs)

    def _is_hidden(self, attrs):
        attrs = self._attrs(attrs)
        style = attrs.get('style', '').replace(' ', '').lower()
        return (
            attrs.get('aria-hidden') == 'true'
            or 'hidden' in attrs
            or attrs.get('type', '').lower() == 'hidden'
            or 'display:none' in style
            or 'visibility:hidden' in style
        )

    def _is_inside_hidden_content(self):
        return bool(self.hidden_stack)

    def handle_starttag(self, tag, attrs):
        if self._is_inside_hidden_content() or self._is_hidden(attrs):
            if tag not in self.VOID_TAGS:
                self.hidden_stack.append(tag)
            return

        attrs = self._attrs(attrs)
        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.current_heading = tag
            self.heading_text = []
        elif tag == 'label':
            self.label_depth += 1
            if attrs.get('for'):
                self.labels_for.add(attrs['for'])
        elif tag in {'input', 'select', 'textarea'}:
            control_type = attrs.get('type', '').lower()
            if control_type not in {'hidden', 'submit', 'button', 'reset'}:
                self.controls.append({
                    'tag': tag,
                    'id': attrs.get('id', ''),
                    'name': attrs.get('name', ''),
                    'type': control_type,
                    'aria_label': attrs.get('aria-label', ''),
                    'aria_labelledby': attrs.get('aria-labelledby', ''),
                    'title': attrs.get('title', ''),
                    'wrapped': self.label_depth > 0,
                })
        elif tag == 'button':
            self.current_button = attrs
            self.button_text = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.hidden_stack:
            if tag in self.hidden_stack:
                while self.hidden_stack:
                    popped = self.hidden_stack.pop()
                    if popped == tag:
                        break
            return

        if tag == self.current_heading:
            text = ''.join(self.heading_text).strip()
            if tag == 'h1' and text:
                self.visible_h1s.append(text)
            self.current_heading = None
            self.heading_text = []
        elif tag == 'label' and self.label_depth:
            self.label_depth -= 1
        elif tag == 'button' and self.current_button is not None:
            self.buttons.append({
                'text': ''.join(self.button_text).strip(),
                'aria_label': self.current_button.get('aria-label', ''),
                'title': self.current_button.get('title', ''),
            })
            self.current_button = None
            self.button_text = []

    def handle_data(self, data):
        if self._is_inside_hidden_content():
            return
        if self.current_heading:
            self.heading_text.append(data)
        if self.current_button is not None:
            self.button_text.append(data)

    def unlabeled_controls(self):
        return [
            control for control in self.controls
            if not (
                control['wrapped']
                or control['aria_label']
                or control['aria_labelledby']
                or control['title']
                or (control['id'] and control['id'] in self.labels_for)
            )
        ]

    def unnamed_buttons(self):
        return [
            button for button in self.buttons
            if not (button['text'] or button['aria_label'] or button['title'])
        ]


class EnvironmentSettingsTests(SimpleTestCase):
    def test_env_bool_accepts_common_truthy_values(self):
        for raw_value in ('1', 'true', 'TRUE', 'yes', 'on'):
            with self.subTest(raw_value=raw_value):
                with patch.dict('os.environ', {'CODEX_BOOL_SETTING': raw_value}):
                    self.assertTrue(env_bool('CODEX_BOOL_SETTING'))

    def test_env_bool_uses_default_when_missing(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertTrue(env_bool('CODEX_BOOL_SETTING', True))
            self.assertFalse(env_bool('CODEX_BOOL_SETTING'))


class AuthenticatedRouteSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='route-smoke',
            password='testpass',
            two_factor_enabled=True,
        )
        cls.investment_account = Account.objects.create(
            user=cls.user,
            name='Brokerage',
            type='investment',
            institution='Codex Bank',
        )
        cls.debt_account = Account.objects.create(
            user=cls.user,
            name='Rewards Card',
            type='debt',
            institution='Codex Card',
        )
        Investment.objects.create(
            account=cls.investment_account,
            name='Index Fund',
            type='etf',
            value=Decimal('1000.00'),
            quantity=Decimal('2.0000'),
            symbol='IDX',
            as_of=date(2026, 7, 9),
        )
        Debt.objects.create(
            account=cls.debt_account,
            name='Rewards Card Balance',
            principal=Decimal('1000.00'),
            balance=Decimal('900.00'),
            interest_rate=Decimal('19.99'),
            minimum_payment=Decimal('35.00'),
            due_date=date(2026, 8, 1),
            as_of=date(2026, 7, 9),
        )
        cls.lobby_competition = Competition.objects.create(
            name='Smoke Cup',
            created_by=cls.user,
        )
        CompetitionParticipant.objects.create(
            competition=cls.lobby_competition,
            user=cls.user,
            portfolio_value=cls.lobby_competition.starting_balance,
        )
        cls.active_competition = Competition.objects.create(
            name='Active Smoke Cup',
            created_by=cls.user,
            status=Competition.STATUS_ACTIVE,
        )
        CompetitionParticipant.objects.create(
            competition=cls.active_competition,
            user=cls.user,
            portfolio_value=cls.active_competition.starting_balance,
        )
        cls.active_mini_game = MiniGame.objects.create(
            competition=cls.active_competition,
            game_type=MiniGame.GAME_PAINTBALL,
            bonus_amount=cls.active_competition.mini_game_bonus,
        )
        cls.finished_competition = Competition.objects.create(
            name='Finished Smoke Cup',
            created_by=cls.user,
            status=Competition.STATUS_FINISHED,
        )
        CompetitionParticipant.objects.create(
            competition=cls.finished_competition,
            user=cls.user,
            portfolio_value=cls.finished_competition.starting_balance,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def assertAccessibleHtml(self, response, route_name):
        parser = RenderedAccessibilityParser()
        parser.feed(response.content.decode(response.charset or 'utf-8', errors='replace'))
        problems = []
        if not parser.visible_h1s:
            problems.append('missing visible h1')
        unlabeled_controls = parser.unlabeled_controls()
        if unlabeled_controls:
            problems.append(f'unlabeled controls: {unlabeled_controls}')
        unnamed_buttons = parser.unnamed_buttons()
        if unnamed_buttons:
            problems.append(f'unnamed buttons: {unnamed_buttons}')
        self.assertFalse(problems, f'{route_name} accessibility smoke failed: {problems}')

    def assertPageRenders(self, route_name, url, template_name):
        with self.subTest(route=route_name):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, template_name)
            self.assertIn('text/html', response['Content-Type'])
            self.assertAccessibleHtml(response, route_name)

    def test_public_auth_pages_have_accessible_page_structure(self):
        self.client.logout()
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        routes = (
            ('accounts:login', reverse('accounts:login'), False),
            ('accounts:register', reverse('accounts:register'), False),
            ('accounts:password_reset', reverse('accounts:password_reset'), False),
            ('accounts:password_reset_done', reverse('accounts:password_reset_done'), False),
            ('accounts:password_reset_complete', reverse('accounts:password_reset_complete'), False),
            (
                'accounts:password_reset_confirm',
                reverse('accounts:password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token}),
                True,
            ),
        )
        for route_name, url, follow in routes:
            with self.subTest(route=route_name):
                response = self.client.get(url, follow=follow)
                self.assertEqual(response.status_code, 200)
                self.assertIn('text/html', response['Content-Type'])
                self.assertAccessibleHtml(response, route_name)

    def test_two_factor_setup_pages_have_accessible_page_structure(self):
        setup_user = get_user_model().objects.create_user(username='setup-2fa', password='x')
        self.client.force_login(setup_user)

        setup_response = self.client.get(reverse('accounts:two_factor_setup'))
        self.assertEqual(setup_response.status_code, 200)
        self.assertAccessibleHtml(setup_response, 'accounts:two_factor_setup')

        session = self.client.session
        session['totp_secret'] = 'JBSWY3DPEHPK3PXP'
        session.save()
        verify_response = self.client.get(reverse('accounts:two_factor_verify'))
        self.assertEqual(verify_response.status_code, 200)
        self.assertAccessibleHtml(verify_response, 'accounts:two_factor_verify')

    def test_authenticated_page_routes_render(self):
        routes = (
            ('accounts:profile', reverse('accounts:profile'), 'accounts/profile.html'),
            ('accounts:change_password', reverse('accounts:change_password'), 'accounts/change_password.html'),
            ('accounts:password_change', reverse('accounts:password_change'), 'accounts/change_password.html'),
            ('accounts:onboarding', reverse('accounts:onboarding'), 'accounts/onboarding.html'),
            (
                'accounts:two_factor_settings',
                reverse('accounts:two_factor_settings'),
                'accounts/two_factor_settings.html',
            ),
            (
                'data_integration:connect_plaid',
                reverse('data_integration:connect_plaid'),
                'data_integration/connect_plaid.html',
            ),
            (
                'data_integration:manual_account_entry',
                reverse('data_integration:manual_account_entry'),
                'data_integration/manual_account_entry.html',
            ),
            (
                'data_integration:manual_transaction_entry',
                reverse('data_integration:manual_transaction_entry'),
                'data_integration/manual_transaction_entry.html',
            ),
            (
                'data_integration:manual_debt_entry',
                reverse('data_integration:manual_debt_entry'),
                'data_integration/manual_debt_entry.html',
            ),
            (
                'data_integration:csv_upload',
                reverse('data_integration:csv_upload'),
                'data_integration/csv_upload.html',
            ),
            (
                'investments:portfolio_overview',
                reverse('investments:portfolio_overview'),
                'investments/portfolio_overview.html',
            ),
            (
                'investments:investment_projections',
                reverse('investments:investment_projections'),
                'investments/investment_projections.html',
            ),
            (
                'investments:investment_recommendations',
                reverse('investments:investment_recommendations'),
                'investments/investment_recommendations.html',
            ),
            (
                'investments:investment_comparison',
                reverse('investments:investment_comparison'),
                'investments/investment_comparison.html',
            ),
            (
                'investments:portfolio_performance',
                reverse('investments:portfolio_performance'),
                'investments/portfolio_performance.html',
            ),
            (
                'debt_management:debt_dashboard',
                reverse('debt_management:debt_dashboard'),
                'debt_management/debt_dashboard.html',
            ),
            (
                'debt_management:payoff_avalanche',
                reverse('debt_management:payoff_avalanche'),
                'debt_management/payoff_avalanche.html',
            ),
            (
                'debt_management:payoff_snowball',
                reverse('debt_management:payoff_snowball'),
                'debt_management/payoff_snowball.html',
            ),
            (
                'debt_management:payoff_custom',
                reverse('debt_management:payoff_custom'),
                'debt_management/payoff_custom.html',
            ),
            (
                'debt_management:debt_reminders',
                reverse('debt_management:debt_reminders'),
                'debt_management/debt_reminders.html',
            ),
            (
                'debt_management:consolidation_suggestion',
                reverse('debt_management:consolidation_suggestion'),
                'debt_management/consolidation_suggestion.html',
            ),
            (
                'debt_management:credit_score_tracking',
                reverse('debt_management:credit_score_tracking'),
                'debt_management/credit_score_tracking.html',
            ),
            ('competition:lobby', reverse('competition:lobby'), 'competition/lobby.html'),
            ('competition:create', reverse('competition:create'), 'competition/create.html'),
            (
                'competition:dashboard',
                reverse('competition:dashboard', kwargs={'pk': self.lobby_competition.pk}),
                'competition/dashboard.html',
            ),
            (
                'competition:paintball',
                reverse(
                    'competition:paintball',
                    kwargs={
                        'pk': self.active_competition.pk,
                        'game_pk': self.active_mini_game.pk,
                    },
                ),
                'competition/paintball.html',
            ),
            (
                'competition:winner',
                reverse('competition:winner', kwargs={'pk': self.finished_competition.pk}),
                'competition/winner.html',
            ),
        )
        for route_name, url, template_name in routes:
            self.assertPageRenders(route_name, url, template_name)

    def test_authenticated_data_routes_return_expected_formats(self):
        checks = (
            (
                'investments:investment_growth_chart',
                reverse('investments:investment_growth_chart'),
                'application/json',
            ),
            (
                'competition:state',
                reverse('competition:state', kwargs={'pk': self.active_competition.pk}),
                'application/json',
            ),
            (
                'investments:export_investments_csv',
                reverse('investments:export_investments_csv'),
                'text/csv',
            ),
        )
        for route_name, url, content_type in checks:
            with self.subTest(route=route_name):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response['Content-Type'])

        state_response = self.client.get(
            reverse('competition:state', kwargs={'pk': self.active_competition.pk})
        )
        self.assertEqual(state_response.json()['status'], Competition.STATUS_ACTIVE)

        csv_response = self.client.get(reverse('investments:export_investments_csv'))
        self.assertTrue(csv_response.content.startswith(b'Name,Type,Current Value'))

    def test_accessibility_markup_regressions_stay_fixed(self):
        portfolio_response = self.client.get(reverse('investments:portfolio_overview'))
        self.assertContains(portfolio_response, 'class="portfolio-main-grid"')

        lobby_response = self.client.get(reverse('competition:lobby'))
        self.assertContains(
            lobby_response,
            '<h2 class="section-label">Your Active Competitions</h2>',
            html=True,
        )
        self.assertContains(
            lobby_response,
            '<h2 class="section-label">Open Lobbies &mdash; Join Now</h2>',
            html=True,
        )
        self.assertContains(
            lobby_response,
            '<h2 class="section-label">In Progress</h2>',
            html=True,
        )

        dashboard_response = self.client.get(
            reverse('competition:dashboard', kwargs={'pk': self.lobby_competition.pk})
        )
        self.assertContains(dashboard_response, '<h1>Smoke Cup</h1>', html=True)

        active_dashboard_response = self.client.get(
            reverse('competition:dashboard', kwargs={'pk': self.active_competition.pk})
        )
        self.assertContains(
            active_dashboard_response,
            '<h1><span class="live-dot"></span>Active Smoke Cup</h1>',
            html=True,
        )
