from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Competition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('lobby', 'Waiting for Players'), ('active', 'In Progress'), ('finished', 'Finished')], default='lobby', max_length=20)),
                ('starting_balance', models.DecimalField(decimal_places=2, default=1000.0, max_digits=12)),
                ('investment_goal', models.DecimalField(decimal_places=2, default=5000.0, max_digits=12)),
                ('mini_game_bonus', models.DecimalField(decimal_places=2, default=50.0, max_digits=8)),
                ('max_players', models.PositiveIntegerField(default=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='created_competitions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='CompetitionParticipant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('portfolio_value', models.DecimalField(decimal_places=2, default=1000.0, max_digits=12)),
                ('mini_game_wins', models.PositiveIntegerField(default=0)),
                ('bonus_earned', models.DecimalField(decimal_places=2, default=0.0, max_digits=10)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('competition', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='competition.competition')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-portfolio_value'],
                'unique_together': {('competition', 'user')},
            },
        ),
        migrations.CreateModel(
            name='MiniGame',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('game_type', models.CharField(choices=[('paintball', 'Paintball')], default='paintball', max_length=30)),
                ('status', models.CharField(choices=[('active', 'Active'), ('finished', 'Finished')], default='active', max_length=20)),
                ('bonus_amount', models.DecimalField(decimal_places=2, default=50.0, max_digits=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('competition', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mini_games', to='competition.competition')),
                ('winner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='mini_game_wins_set', to='competition.competitionparticipant')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MiniGameResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.IntegerField(default=0)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('mini_game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='results', to='competition.minigame')),
                ('participant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='competition.competitionparticipant')),
            ],
            options={
                'unique_together': {('mini_game', 'participant')},
            },
        ),
    ]
