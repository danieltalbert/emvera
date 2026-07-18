"""Top-level routes, including public landing and operational probes."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from .health import healthz, readyz

urlpatterns = [
    path('', TemplateView.as_view(template_name='landing.html'), name='home'),
    path('healthz/', healthz, name='healthz'),
    path('readyz/', readyz, name='readyz'),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('investments/', include('investments.urls')),
    path('data/', include('data_integration.urls')),
    path('debt-management/', include('debt_management.urls')),
    path('competition/', include('competition.urls')),
]
