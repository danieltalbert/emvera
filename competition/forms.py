"""Form definitions for the competition app."""

from django import forms
from .models import Competition


class CompetitionForm(forms.ModelForm):
    class Meta:
        model = Competition
        fields = ['name', 'description', 'starting_balance', 'investment_goal', 'mini_game_bonus', 'max_players', 'uses_paper_trading']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Friday Night Investing'}),
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Optional — describe the competition rules or theme'}),
            'starting_balance': forms.NumberInput(attrs={'min': 100, 'step': 100}),
            'investment_goal': forms.NumberInput(attrs={'min': 500, 'step': 100}),
            'mini_game_bonus': forms.NumberInput(attrs={'min': 10, 'step': 10}),
            'max_players': forms.NumberInput(attrs={'min': 2, 'max': 20}),
        }
        labels = {
            'starting_balance': 'Starting Balance ($)',
            'investment_goal': 'Portfolio Goal ($)',
            'mini_game_bonus': 'Mini-Game Bonus ($)',
            'max_players': 'Max Players',
            'uses_paper_trading': 'Paper-trading mode',
        }
        help_texts = {
            'starting_balance': 'Virtual starting amount each player receives.',
            'investment_goal': 'First player to reach this wins the competition.',
            'mini_game_bonus': 'Amount added to the winner\'s portfolio for each mini-game.',
            'uses_paper_trading': 'Rank players by live paper-trading portfolio value instead of mini-games.',
        }
