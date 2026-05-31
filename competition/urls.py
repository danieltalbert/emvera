from django.urls import path
from . import views

app_name = 'competition'

urlpatterns = [
    path('', views.lobby, name='lobby'),
    path('create/', views.create_competition, name='create'),
    path('<int:pk>/', views.competition_dashboard, name='dashboard'),
    path('<int:pk>/join/', views.join_competition, name='join'),
    path('<int:pk>/start/', views.start_competition, name='start'),
    path('<int:pk>/end/', views.end_competition, name='end'),
    path('<int:pk>/trigger-mini-game/', views.trigger_mini_game, name='trigger_mini_game'),
    path('<int:pk>/state/', views.competition_state, name='state'),
    path('<int:pk>/mini-game/<int:game_pk>/paintball/', views.paintball_game, name='paintball'),
    path('<int:pk>/mini-game/<int:game_pk>/submit-score/', views.submit_score, name='submit_score'),
    path('<int:pk>/winner/', views.competition_winner, name='winner'),

    # Paper-trading competitions: participant trading panel + order submission.
    path('<int:pk>/trade/', views.trade, name='trade'),
    path('<int:pk>/trade/order/', views.place_trade, name='place_trade'),
]
