from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('login/',    views.user_login,    name='login'),
    path('logout/',   auth_views.LogoutView.as_view(next_page='/accounts/login/'),              name='logout'),
    path('register/', views.register,                                                           name='register'),

    # Password management
    path('password-change/', auth_views.PasswordChangeView.as_view(success_url='/accounts/profile/'), name='password_change'),
    path('password-reset/',  auth_views.PasswordResetView.as_view(),                               name='password_reset'),

    # Profile
    path('profile/', views.profile, name='profile'),
    path('change-password/', views.change_password, name='change_password'),
    path('onboarding/', views.onboarding, name='onboarding'),

    # 2FA
    path('two-factor/setup/', views.two_factor_setup, name='two_factor_setup'),
    path('two-factor/verify/', views.two_factor_verify, name='two_factor_verify'),
    path('two-factor/settings/', views.two_factor_settings, name='two_factor_settings'),
]
