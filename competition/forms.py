from decimal import Decimal

from django import forms
from .models import Competition


MIN_STARTING_BALANCE = Decimal('100.00')
MIN_INVESTMENT_GOAL = Decimal('500.00')
MIN_MINI_GAME_BONUS = Decimal('10.00')
MIN_PLAYERS = 2
MAX_PLAYERS = 20


class CompetitionForm(forms.ModelForm):
    class Meta:
        model = Competition
        fields = ['name', 'description', 'starting_balance', 'investment_goal', 'mini_game_bonus', 'max_players']
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
        }
        help_texts = {
            'starting_balance': 'Virtual starting amount each player receives.',
            'investment_goal': 'First player to reach this wins the competition.',
            'mini_game_bonus': 'Amount added to the winner\'s portfolio for each mini-game.',
        }

    def clean_starting_balance(self):
        starting_balance = self.cleaned_data['starting_balance']
        if starting_balance < MIN_STARTING_BALANCE:
            raise forms.ValidationError('Starting balance must be at least $100.')
        return starting_balance

    def clean_investment_goal(self):
        investment_goal = self.cleaned_data['investment_goal']
        if investment_goal < MIN_INVESTMENT_GOAL:
            raise forms.ValidationError('Portfolio goal must be at least $500.')
        return investment_goal

    def clean_mini_game_bonus(self):
        mini_game_bonus = self.cleaned_data['mini_game_bonus']
        if mini_game_bonus < MIN_MINI_GAME_BONUS:
            raise forms.ValidationError('Mini-game bonus must be at least $10.')
        return mini_game_bonus

    def clean_max_players(self):
        max_players = self.cleaned_data['max_players']
        if max_players < MIN_PLAYERS or max_players > MAX_PLAYERS:
            raise forms.ValidationError('Max players must be between 2 and 20.')
        return max_players
