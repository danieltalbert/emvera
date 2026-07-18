from django import forms

from .models import InvestmentProjection


class InvestmentProjectionForm(forms.ModelForm):
    class Meta:
        model = InvestmentProjection
        fields = ['investment', 'projection_date', 'projected_value', 'growth_rate']
        widgets = {
            'projection_date': forms.DateInput(attrs={'type': 'date'}),
        }
