import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, ExpressionWrapper, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.require_2fa import require_2fa

from .forms import CompetitionForm
from .models import Competition, CompetitionParticipant, MiniGame, MiniGameResult

MAX_MINI_GAME_SCORE = 5000


def _competition_leaderboard(competition):
    total_value = ExpressionWrapper(
        F('portfolio_value') + F('bonus_earned'),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    return (
        competition.participants.select_related('user')
        .annotate(leaderboard_total=total_value)
        .order_by('-leaderboard_total', '-portfolio_value', '-bonus_earned', 'joined_at')
    )


@login_required
@require_2fa
def lobby(request):
    my_competitions = Competition.objects.filter(participants__user=request.user).exclude(
        status=Competition.STATUS_FINISHED
    )
    joined_competition_ids = my_competitions.values('pk')
    open_competitions = Competition.objects.filter(status=Competition.STATUS_LOBBY).exclude(
        pk__in=joined_competition_ids
    )
    active_competitions = Competition.objects.filter(status=Competition.STATUS_ACTIVE).exclude(
        pk__in=joined_competition_ids
    )
    finished = Competition.objects.filter(status=Competition.STATUS_FINISHED)[:5]

    return render(
        request,
        'competition/lobby.html',
        {
            'open_competitions': open_competitions,
            'active_competitions': active_competitions,
            'my_competitions': my_competitions,
            'finished': finished,
        },
    )


@login_required
@require_2fa
def create_competition(request):
    if request.method == 'POST':
        form = CompetitionForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                competition = form.save(commit=False)
                competition.created_by = request.user
                competition.save()
                CompetitionParticipant.objects.create(
                    competition=competition,
                    user=request.user,
                    portfolio_value=competition.starting_balance,
                )
            messages.success(
                request, f'"{competition.name}" created! Share the link so others can join.'
            )
            return redirect('competition:dashboard', pk=competition.pk)
    else:
        form = CompetitionForm()
    return render(request, 'competition/create.html', {'form': form})


@login_required
@require_2fa
@require_POST
def join_competition(request, pk):
    with transaction.atomic():
        competition = get_object_or_404(
            Competition.objects.select_for_update(),
            pk=pk,
            status=Competition.STATUS_LOBBY,
        )
        if competition.participants.filter(user=request.user).exists():
            messages.info(request, f'You are already in "{competition.name}".')
            return redirect('competition:dashboard', pk=competition.pk)
        if competition.participants.count() >= competition.max_players:
            messages.error(request, 'This competition is full.')
            return redirect('competition:lobby')
        try:
            with transaction.atomic():
                CompetitionParticipant.objects.create(
                    competition=competition,
                    user=request.user,
                    portfolio_value=competition.starting_balance,
                )
        except IntegrityError:
            messages.info(request, f'You are already in "{competition.name}".')
            return redirect('competition:dashboard', pk=competition.pk)
    messages.success(request, f'You joined "{competition.name}"!')
    return redirect('competition:dashboard', pk=competition.pk)


@login_required
@require_2fa
@require_POST
def start_competition(request, pk):
    with transaction.atomic():
        competition = get_object_or_404(
            Competition.objects.select_for_update(),
            pk=pk,
            created_by=request.user,
            status=Competition.STATUS_LOBBY,
        )
        if competition.participants.count() < 2:
            messages.error(request, 'You need at least 2 players to start.')
            return redirect('competition:dashboard', pk=competition.pk)
        competition.start()
    messages.success(request, 'Competition started! Let the games begin.')
    return redirect('competition:dashboard', pk=competition.pk)


@login_required
@require_2fa
def competition_dashboard(request, pk):
    competition = get_object_or_404(Competition, pk=pk)
    try:
        participant = competition.participants.get(user=request.user)
    except CompetitionParticipant.DoesNotExist:
        participant = None

    active_mini_game = competition.mini_games.filter(status=MiniGame.STATUS_ACTIVE).first()
    already_played = False
    if active_mini_game and participant:
        already_played = active_mini_game.results.filter(participant=participant).exists()

    leaderboard = _competition_leaderboard(competition)

    return render(
        request,
        'competition/dashboard.html',
        {
            'competition': competition,
            'participant': participant,
            'leaderboard': leaderboard,
            'active_mini_game': active_mini_game,
            'already_played': already_played,
            'is_creator': competition.created_by == request.user,
        },
    )


@login_required
@require_2fa
def competition_state(request, pk):
    """Polling endpoint — returns JSON snapshot of competition state."""
    competition = get_object_or_404(Competition, pk=pk)
    active_mini_game = competition.mini_games.filter(status=MiniGame.STATUS_ACTIVE).first()

    try:
        participant = competition.participants.get(user=request.user)
        already_played = bool(
            active_mini_game and active_mini_game.results.filter(participant=participant).exists()
        )
    except CompetitionParticipant.DoesNotExist:
        already_played = False

    leaderboard = [
        {
            'username': p.user.username,
            'portfolio_value': float(p.portfolio_value),
            'bonus_earned': float(p.bonus_earned),
            'total_value': float(p.total_value),
            'mini_game_wins': p.mini_game_wins,
        }
        for p in _competition_leaderboard(competition)
    ]

    return JsonResponse(
        {
            'status': competition.status,
            'leaderboard': leaderboard,
            'active_mini_game': {
                'id': active_mini_game.pk,
                'game_type': active_mini_game.game_type,
                'already_played': already_played,
            }
            if active_mini_game
            else None,
            'winner_url': f'/competition/{pk}/winner/'
            if competition.status == Competition.STATUS_FINISHED
            else None,
        }
    )


@login_required
@require_2fa
@require_POST
def trigger_mini_game(request, pk):
    with transaction.atomic():
        competition = get_object_or_404(
            Competition.objects.select_for_update(),
            pk=pk,
            created_by=request.user,
            status=Competition.STATUS_ACTIVE,
        )
        if competition.mini_games.filter(status=MiniGame.STATUS_ACTIVE).exists():
            messages.warning(request, 'A mini-game is already in progress.')
            return redirect('competition:dashboard', pk=pk)
        MiniGame.objects.create(
            competition=competition,
            game_type=MiniGame.GAME_PAINTBALL,
            bonus_amount=competition.mini_game_bonus,
        )
    messages.success(request, 'Paintball mini-game launched!')
    return redirect('competition:dashboard', pk=pk)


@login_required
@require_2fa
def paintball_game(request, pk, game_pk):
    competition = get_object_or_404(Competition, pk=pk, status=Competition.STATUS_ACTIVE)
    mini_game = get_object_or_404(
        MiniGame, pk=game_pk, competition=competition, status=MiniGame.STATUS_ACTIVE
    )
    participant = get_object_or_404(
        CompetitionParticipant, competition=competition, user=request.user
    )

    if mini_game.results.filter(participant=participant).exists():
        messages.info(request, 'You already played this round.')
        return redirect('competition:dashboard', pk=pk)

    return render(
        request,
        'competition/paintball.html',
        {
            'competition': competition,
            'mini_game': mini_game,
            'participant': participant,
        },
    )


@login_required
@require_2fa
@require_POST
def submit_score(request, pk, game_pk):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        if 'score' not in data:
            raise ValueError
        raw_score = data['score']
        if isinstance(raw_score, bool):
            raise ValueError
        if isinstance(raw_score, int):
            score = raw_score
        elif isinstance(raw_score, str) and raw_score.isdecimal():
            score = int(raw_score)
        else:
            raise ValueError
        if score < 0 or score > MAX_MINI_GAME_SCORE:
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid score.'})

    with transaction.atomic():
        competition = get_object_or_404(
            Competition.objects.select_for_update(),
            pk=pk,
            status=Competition.STATUS_ACTIVE,
        )
        mini_game = get_object_or_404(
            MiniGame.objects.select_for_update(),
            pk=game_pk,
            competition=competition,
            status=MiniGame.STATUS_ACTIVE,
        )
        participant = get_object_or_404(
            CompetitionParticipant,
            competition=competition,
            user=request.user,
        )

        try:
            with transaction.atomic():
                MiniGameResult.objects.create(
                    mini_game=mini_game,
                    participant=participant,
                    score=score,
                )
        except IntegrityError:
            return JsonResponse({'ok': False, 'error': 'Already submitted.'})

        all_played = mini_game.results.count() >= competition.participants.count()
        if all_played:
            mini_game.resolve()
            _check_winner(competition)

    return JsonResponse({'ok': True, 'score': score})


def _check_winner(competition):
    """Finish competition if any participant has reached the goal."""
    leader = _competition_leaderboard(competition).first()
    if leader and leader.total_value >= competition.investment_goal:
        competition.finish()


@login_required
@require_2fa
@require_POST
def end_competition(request, pk):
    with transaction.atomic():
        competition = get_object_or_404(
            Competition.objects.select_for_update(),
            pk=pk,
            created_by=request.user,
            status=Competition.STATUS_ACTIVE,
        )
        for mini_game in competition.mini_games.select_for_update().filter(
            status=MiniGame.STATUS_ACTIVE
        ):
            mini_game.resolve()
        competition.finish()
    return redirect('competition:winner', pk=pk)


@login_required
@require_2fa
def competition_winner(request, pk):
    competition = get_object_or_404(Competition, pk=pk, status=Competition.STATUS_FINISHED)
    leaderboard = _competition_leaderboard(competition)
    winner = leaderboard.first()
    return render(
        request,
        'competition/winner.html',
        {
            'competition': competition,
            'leaderboard': leaderboard,
            'winner': winner,
            'is_winner': winner and winner.user == request.user,
        },
    )
