from django.conf import settings
from django.db import models, transaction
from django.db.models import DecimalField, ExpressionWrapper, F
from django.utils import timezone


class Competition(models.Model):
    STATUS_LOBBY = 'lobby'
    STATUS_ACTIVE = 'active'
    STATUS_FINISHED = 'finished'
    STATUS_CHOICES = [
        (STATUS_LOBBY, 'Waiting for Players'),
        (STATUS_ACTIVE, 'In Progress'),
        (STATUS_FINISHED, 'Finished'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_competitions',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_LOBBY)
    starting_balance = models.DecimalField(max_digits=12, decimal_places=2, default=1000.00)
    investment_goal = models.DecimalField(max_digits=12, decimal_places=2, default=5000.00)
    mini_game_bonus = models.DecimalField(max_digits=8, decimal_places=2, default=50.00)
    max_players = models.PositiveIntegerField(default=8)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def winner(self):
        total_value = ExpressionWrapper(
            F('portfolio_value') + F('bonus_earned'),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        return (
            self.participants.annotate(leaderboard_total=total_value)
            .order_by('-leaderboard_total', '-portfolio_value', '-bonus_earned', 'joined_at')
            .first()
        )

    def start(self):
        self.status = self.STATUS_ACTIVE
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

    def finish(self):
        self.status = self.STATUS_FINISHED
        self.ended_at = timezone.now()
        self.save(update_fields=['status', 'ended_at'])


class CompetitionParticipant(models.Model):
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name='participants'
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    portfolio_value = models.DecimalField(max_digits=12, decimal_places=2, default=1000.00)
    mini_game_wins = models.PositiveIntegerField(default=0)
    bonus_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('competition', 'user')
        ordering = ['-portfolio_value']

    @property
    def total_value(self):
        return self.portfolio_value + self.bonus_earned

    @property
    def rank(self):
        total_value = ExpressionWrapper(
            F('portfolio_value') + F('bonus_earned'),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        return (
            self.competition.participants.annotate(leaderboard_total=total_value)
            .filter(leaderboard_total__gt=self.total_value)
            .count()
            + 1
        )

    def __str__(self):
        return f'{self.user.username} in {self.competition.name}'


class MiniGame(models.Model):
    GAME_PAINTBALL = 'paintball'
    GAME_CHOICES = [
        (GAME_PAINTBALL, 'Paintball'),
    ]
    STATUS_ACTIVE = 'active'
    STATUS_FINISHED = 'finished'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_FINISHED, 'Finished'),
    ]

    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name='mini_games'
    )
    game_type = models.CharField(max_length=30, choices=GAME_CHOICES, default=GAME_PAINTBALL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    winner = models.ForeignKey(
        CompetitionParticipant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mini_game_wins_set',
    )
    bonus_amount = models.DecimalField(max_digits=8, decimal_places=2, default=50.00)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_game_type_display()} — {self.competition.name}'

    @transaction.atomic
    def resolve(self):
        """Determine winner from submitted scores, apply bonus, mark finished."""
        locked_game = MiniGame.objects.select_for_update().get(pk=self.pk)
        if locked_game.status == self.STATUS_FINISHED:
            self.status = locked_game.status
            self.winner_id = locked_game.winner_id
            self.finished_at = locked_game.finished_at
            return

        top = (
            locked_game.results.select_related('participant')
            .order_by('-score', 'submitted_at', 'pk')
            .first()
        )
        if top:
            CompetitionParticipant.objects.filter(pk=top.participant_id).update(
                bonus_earned=F('bonus_earned') + locked_game.bonus_amount,
                mini_game_wins=F('mini_game_wins') + 1,
            )
            locked_game.winner_id = top.participant_id
        locked_game.status = self.STATUS_FINISHED
        locked_game.finished_at = timezone.now()
        locked_game.save(update_fields=['winner', 'status', 'finished_at'])

        self.status = locked_game.status
        self.winner_id = locked_game.winner_id
        self.finished_at = locked_game.finished_at


class MiniGameResult(models.Model):
    mini_game = models.ForeignKey(MiniGame, on_delete=models.CASCADE, related_name='results')
    participant = models.ForeignKey(CompetitionParticipant, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('mini_game', 'participant')

    def __str__(self):
        return f'{self.participant.user.username}: {self.score} pts'
