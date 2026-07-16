import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Competition, CompetitionParticipant, MiniGame, MiniGameResult


class CompetitionFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.creator = User.objects.create_user(username='creator', password='x', two_factor_enabled=True)
        cls.joiner = User.objects.create_user(username='joiner', password='x', two_factor_enabled=True)
        cls.outsider = User.objects.create_user(username='outsider', password='x', two_factor_enabled=True)

    def setUp(self):
        self.client.force_login(self.creator)

    def test_lobby_empty_state_invites_first_competition(self):
        response = self.client.get(reverse('competition:lobby'))

        self.assertContains(response, 'No competitions yet')
        self.assertContains(response, 'Create a virtual portfolio challenge')
        self.assertContains(response, 'Create Competition')

    def create_competition(self, **overrides):
        values = {
            'name': 'Test Cup',
            'created_by': self.creator,
            'starting_balance': Decimal('1000.00'),
            'investment_goal': Decimal('2000.00'),
            'mini_game_bonus': Decimal('75.00'),
            'max_players': 4,
        }
        values.update(overrides)
        return Competition.objects.create(**values)

    def add_participant(self, competition, user, **overrides):
        values = {
            'competition': competition,
            'user': user,
            'portfolio_value': competition.starting_balance,
        }
        values.update(overrides)
        return CompetitionParticipant.objects.create(**values)

    def test_create_competition_adds_creator_as_participant(self):
        response = self.client.post(reverse('competition:create'), {
            'name': 'Friday Cup',
            'description': 'Weekly challenge',
            'starting_balance': '1500',
            'investment_goal': '3500',
            'mini_game_bonus': '100',
            'max_players': '6',
        })

        competition = Competition.objects.get(name='Friday Cup')
        self.assertRedirects(response, reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        participant = CompetitionParticipant.objects.get(competition=competition, user=self.creator)
        self.assertEqual(participant.portfolio_value, Decimal('1500.00'))

    def test_create_competition_rejects_values_outside_server_bounds(self):
        response = self.client.post(reverse('competition:create'), {
            'name': 'Impossible Cup',
            'description': 'Crafted request below UI limits',
            'starting_balance': '99',
            'investment_goal': '499',
            'mini_game_bonus': '9',
            'max_players': '1',
        })

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertTrue(form.has_error('starting_balance'))
        self.assertTrue(form.has_error('investment_goal'))
        self.assertTrue(form.has_error('mini_game_bonus'))
        self.assertTrue(form.has_error('max_players'))
        self.assertFalse(Competition.objects.filter(name='Impossible Cup').exists())

        response = self.client.post(reverse('competition:create'), {
            'name': 'Oversized Cup',
            'description': 'Crafted request above UI limits',
            'starting_balance': '1000',
            'investment_goal': '5000',
            'mini_game_bonus': '50',
            'max_players': '21',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('max_players'))
        self.assertFalse(Competition.objects.filter(name='Oversized Cup').exists())

    def test_join_competition_requires_post_and_does_not_duplicate_participants(self):
        competition = self.create_competition(max_players=2)
        self.add_participant(competition, self.creator)
        self.client.force_login(self.joiner)

        get_response = self.client.get(reverse('competition:join', kwargs={'pk': competition.pk}))
        self.assertEqual(get_response.status_code, 405)

        join_url = reverse('competition:join', kwargs={'pk': competition.pk})
        response = self.client.post(join_url)
        self.assertRedirects(response, reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        response = self.client.post(join_url)
        self.assertRedirects(response, reverse('competition:lobby'))

        self.assertEqual(competition.participants.filter(user=self.joiner).count(), 1)
        participant = competition.participants.get(user=self.joiner)
        self.assertEqual(participant.portfolio_value, competition.starting_balance)

    def test_only_creator_can_start_competition_with_enough_players(self):
        competition = self.create_competition()
        self.add_participant(competition, self.creator)
        start_url = reverse('competition:start', kwargs={'pk': competition.pk})

        response = self.client.post(start_url)
        self.assertRedirects(response, reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        competition.refresh_from_db()
        self.assertEqual(competition.status, Competition.STATUS_LOBBY)

        self.client.force_login(self.joiner)
        forbidden_response = self.client.post(start_url)
        self.assertEqual(forbidden_response.status_code, 404)

        self.add_participant(competition, self.joiner)
        self.client.force_login(self.creator)
        response = self.client.post(start_url)
        self.assertRedirects(response, reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        competition.refresh_from_db()
        self.assertEqual(competition.status, Competition.STATUS_ACTIVE)
        self.assertIsNotNone(competition.started_at)

    def test_trigger_mini_game_creates_one_active_game_for_creator(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        self.add_participant(competition, self.creator)
        trigger_url = reverse('competition:trigger_mini_game', kwargs={'pk': competition.pk})

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(trigger_url).status_code, 404)

        self.client.force_login(self.creator)
        response = self.client.post(trigger_url)
        self.assertRedirects(response, reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        self.assertEqual(competition.mini_games.filter(status=MiniGame.STATUS_ACTIVE).count(), 1)

        response = self.client.post(trigger_url)
        self.assertRedirects(response, reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        self.assertEqual(competition.mini_games.filter(status=MiniGame.STATUS_ACTIVE).count(), 1)

    def test_leaderboards_order_by_total_value_including_bonus(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        creator_participant = self.add_participant(
            competition,
            self.creator,
            portfolio_value=Decimal('1200.00'),
            bonus_earned=Decimal('0.00'),
        )
        joiner_participant = self.add_participant(
            competition,
            self.joiner,
            portfolio_value=Decimal('1000.00'),
            bonus_earned=Decimal('300.00'),
        )

        dashboard_response = self.client.get(reverse('competition:dashboard', kwargs={'pk': competition.pk}))
        self.assertEqual(list(dashboard_response.context['leaderboard'])[:2], [
            joiner_participant,
            creator_participant,
        ])

        state_response = self.client.get(reverse('competition:state', kwargs={'pk': competition.pk}))
        self.assertEqual(state_response.json()['leaderboard'][0]['username'], 'joiner')

        creator_participant.refresh_from_db()
        joiner_participant.refresh_from_db()
        self.assertEqual(creator_participant.rank, 2)
        self.assertEqual(joiner_participant.rank, 1)

    def test_winner_uses_total_value_including_bonus(self):
        competition = self.create_competition(status=Competition.STATUS_FINISHED)
        creator_participant = self.add_participant(
            competition,
            self.creator,
            portfolio_value=Decimal('1200.00'),
            bonus_earned=Decimal('0.00'),
        )
        joiner_participant = self.add_participant(
            competition,
            self.joiner,
            portfolio_value=Decimal('1000.00'),
            bonus_earned=Decimal('300.00'),
        )

        self.assertEqual(competition.winner, joiner_participant)

        response = self.client.get(reverse('competition:winner', kwargs={'pk': competition.pk}))
        self.assertEqual(response.context['winner'], joiner_participant)
        self.assertEqual(list(response.context['leaderboard'])[:2], [
            joiner_participant,
            creator_participant,
        ])

    def test_submit_score_resolves_mini_game_after_all_participants_play(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        creator_participant = self.add_participant(competition, self.creator)
        joiner_participant = self.add_participant(competition, self.joiner)
        mini_game = MiniGame.objects.create(
            competition=competition,
            game_type=MiniGame.GAME_PAINTBALL,
            bonus_amount=competition.mini_game_bonus,
        )
        submit_url = reverse('competition:submit_score', kwargs={
            'pk': competition.pk,
            'game_pk': mini_game.pk,
        })

        response = self.client.post(
            submit_url,
            data=json.dumps({'score': 10}),
            content_type='application/json',
        )
        self.assertEqual(response.json(), {'ok': True, 'score': 10})
        mini_game.refresh_from_db()
        self.assertEqual(mini_game.status, MiniGame.STATUS_ACTIVE)

        self.client.force_login(self.joiner)
        response = self.client.post(
            submit_url,
            data=json.dumps({'score': 20}),
            content_type='application/json',
        )
        self.assertEqual(response.json(), {'ok': True, 'score': 20})

        mini_game.refresh_from_db()
        creator_participant.refresh_from_db()
        joiner_participant.refresh_from_db()
        self.assertEqual(mini_game.status, MiniGame.STATUS_FINISHED)
        self.assertEqual(mini_game.winner, joiner_participant)
        self.assertEqual(creator_participant.bonus_earned, Decimal('0.00'))
        self.assertEqual(joiner_participant.bonus_earned, competition.mini_game_bonus)

    def test_mini_game_bonus_can_finish_competition_by_total_value(self):
        competition = self.create_competition(
            status=Competition.STATUS_ACTIVE,
            investment_goal=Decimal('1100.00'),
            mini_game_bonus=Decimal('150.00'),
        )
        self.add_participant(competition, self.creator, portfolio_value=Decimal('1050.00'))
        self.add_participant(competition, self.joiner, portfolio_value=Decimal('1000.00'))
        mini_game = MiniGame.objects.create(competition=competition, bonus_amount=competition.mini_game_bonus)
        submit_url = reverse('competition:submit_score', kwargs={
            'pk': competition.pk,
            'game_pk': mini_game.pk,
        })

        self.client.post(
            submit_url,
            data=json.dumps({'score': 5}),
            content_type='application/json',
        )
        competition.refresh_from_db()
        self.assertEqual(competition.status, Competition.STATUS_ACTIVE)

        self.client.force_login(self.joiner)
        self.client.post(
            submit_url,
            data=json.dumps({'score': 10}),
            content_type='application/json',
        )

        competition.refresh_from_db()
        self.assertEqual(competition.status, Competition.STATUS_FINISHED)

    def test_submit_score_rejects_duplicate_entries(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        participant = self.add_participant(competition, self.creator)
        mini_game = MiniGame.objects.create(competition=competition, bonus_amount=competition.mini_game_bonus)
        MiniGameResult.objects.create(mini_game=mini_game, participant=participant, score=15)

        response = self.client.post(
            reverse('competition:submit_score', kwargs={'pk': competition.pk, 'game_pk': mini_game.pk}),
            data=json.dumps({'score': 99}),
            content_type='application/json',
        )

        self.assertEqual(response.json(), {'ok': False, 'error': 'Already submitted.'})
        self.assertEqual(mini_game.results.filter(participant=participant).count(), 1)

    def test_submit_score_rejects_inactive_competition_or_mini_game(self):
        finished_competition = self.create_competition(status=Competition.STATUS_FINISHED)
        self.add_participant(finished_competition, self.creator)
        active_mini_game = MiniGame.objects.create(
            competition=finished_competition,
            bonus_amount=finished_competition.mini_game_bonus,
        )

        response = self.client.post(
            reverse('competition:submit_score', kwargs={
                'pk': finished_competition.pk,
                'game_pk': active_mini_game.pk,
            }),
            data=json.dumps({'score': 99}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MiniGameResult.objects.filter(mini_game=active_mini_game).exists())

        active_competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        self.add_participant(active_competition, self.creator)
        finished_mini_game = MiniGame.objects.create(
            competition=active_competition,
            bonus_amount=active_competition.mini_game_bonus,
            status=MiniGame.STATUS_FINISHED,
        )

        response = self.client.post(
            reverse('competition:submit_score', kwargs={
                'pk': active_competition.pk,
                'game_pk': finished_mini_game.pk,
            }),
            data=json.dumps({'score': 88}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(MiniGameResult.objects.filter(mini_game=finished_mini_game).exists())

    def test_submit_score_rejects_malformed_or_negative_scores(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        self.add_participant(competition, self.creator)
        mini_game = MiniGame.objects.create(competition=competition, bonus_amount=competition.mini_game_bonus)
        submit_url = reverse('competition:submit_score', kwargs={
            'pk': competition.pk,
            'game_pk': mini_game.pk,
        })

        malformed_response = self.client.post(
            submit_url,
            data=json.dumps(['not', 'an', 'object']),
            content_type='application/json',
        )

        self.assertEqual(malformed_response.json(), {'ok': False, 'error': 'Invalid score.'})
        self.assertFalse(MiniGameResult.objects.filter(mini_game=mini_game).exists())

        missing_score_response = self.client.post(
            submit_url,
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(missing_score_response.json(), {'ok': False, 'error': 'Invalid score.'})
        self.assertFalse(MiniGameResult.objects.filter(mini_game=mini_game).exists())

        negative_response = self.client.post(
            submit_url,
            data=json.dumps({'score': -1}),
            content_type='application/json',
        )

        self.assertEqual(negative_response.json(), {'ok': False, 'error': 'Invalid score.'})
        self.assertFalse(MiniGameResult.objects.filter(mini_game=mini_game).exists())

        for invalid_score in [True, 12.5, '12.5']:
            with self.subTest(invalid_score=invalid_score):
                response = self.client.post(
                    submit_url,
                    data=json.dumps({'score': invalid_score}),
                    content_type='application/json',
                )

                self.assertEqual(response.json(), {'ok': False, 'error': 'Invalid score.'})
                self.assertFalse(MiniGameResult.objects.filter(mini_game=mini_game).exists())

    def test_outsider_cannot_play_or_submit_mini_game(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        self.add_participant(competition, self.creator)
        mini_game = MiniGame.objects.create(competition=competition, bonus_amount=competition.mini_game_bonus)
        self.client.force_login(self.outsider)

        paintball_response = self.client.get(reverse('competition:paintball', kwargs={
            'pk': competition.pk,
            'game_pk': mini_game.pk,
        }))
        self.assertEqual(paintball_response.status_code, 404)

        submit_response = self.client.post(
            reverse('competition:submit_score', kwargs={'pk': competition.pk, 'game_pk': mini_game.pk}),
            data=json.dumps({'score': 99}),
            content_type='application/json',
        )
        self.assertEqual(submit_response.status_code, 404)
        self.assertFalse(MiniGameResult.objects.filter(mini_game=mini_game).exists())

    def test_creator_can_end_active_competition(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        self.add_participant(competition, self.creator)
        mini_game = MiniGame.objects.create(competition=competition, bonus_amount=competition.mini_game_bonus)

        response = self.client.post(reverse('competition:end', kwargs={'pk': competition.pk}))

        self.assertRedirects(response, reverse('competition:winner', kwargs={'pk': competition.pk}))
        competition.refresh_from_db()
        mini_game.refresh_from_db()
        self.assertEqual(competition.status, Competition.STATUS_FINISHED)
        self.assertEqual(mini_game.status, MiniGame.STATUS_FINISHED)

    def test_outsider_cannot_end_active_competition(self):
        competition = self.create_competition(status=Competition.STATUS_ACTIVE)
        self.add_participant(competition, self.creator)
        mini_game = MiniGame.objects.create(competition=competition, bonus_amount=competition.mini_game_bonus)
        self.client.force_login(self.outsider)

        response = self.client.post(reverse('competition:end', kwargs={'pk': competition.pk}))

        self.assertEqual(response.status_code, 404)
        competition.refresh_from_db()
        mini_game.refresh_from_db()
        self.assertEqual(competition.status, Competition.STATUS_ACTIVE)
        self.assertEqual(mini_game.status, MiniGame.STATUS_ACTIVE)
