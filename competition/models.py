"""Database models for the competition feature: Competition, its
Participants, the MiniGame instances, and per-player MiniGameResult rows."""

from django.conf import settings
from django.db import models
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
    # When True, this is a TRADING competition: each player gets a competition-
    # scoped paper-trading account and the leaderboard ranks by live paper equity
    # (see competition/services.py) instead of mini-game bonuses. Default False
    # keeps the classic mini-game behavior unchanged.
    uses_paper_trading = models.BooleanField(
        default=False,
        help_text='Rank players by live paper-trading portfolio value instead of mini-game bonuses.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def winner(self):
        return self.participants.order_by('-portfolio_value').first()

    def start(self):
        self.status = self.STATUS_ACTIVE
        self.started_at = timezone.now()
        self.save()
        # Trading competitions need a paper account per player, seeded with the
        # starting balance. Imported lazily to avoid a circular import
        # (paper_trading depends on competition for its optional FK).
        if self.uses_paper_trading:
            from .services import ensure_paper_accounts
            ensure_paper_accounts(self)

    def finish(self):
        self.status = self.STATUS_FINISHED
        self.ended_at = timezone.now()
        self.save()


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
        return (
            self.competition.participants.filter(portfolio_value__gt=self.portfolio_value).count() + 1
        )

    def __str__(self):
        return f"{self.user.username} in {self.competition.name}"


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
        null=True, blank=True,
        related_name='mini_game_wins_set',
    )
    bonus_amount = models.DecimalField(max_digits=8, decimal_places=2, default=50.00)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_game_type_display()} — {self.competition.name}"

    def resolve(self):
        """Determine winner from submitted scores, apply bonus, mark finished."""
        top = self.results.order_by('-score').first()
        if top:
            self.winner = top.participant
            top.participant.bonus_earned += self.bonus_amount
            top.participant.mini_game_wins += 1
            top.participant.save()
        self.status = self.STATUS_FINISHED
        self.finished_at = timezone.now()
        self.save()


class MiniGameResult(models.Model):
    mini_game = models.ForeignKey(MiniGame, on_delete=models.CASCADE, related_name='results')
    participant = models.ForeignKey(CompetitionParticipant, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('mini_game', 'participant')

    def __str__(self):
        return f"{self.participant.user.username}: {self.score} pts"
