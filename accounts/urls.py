from django.urls import path
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('login/',    views.user_login,    name='login'),
    path('logout/',   auth_views.LogoutView.as_view(next_page='/accounts/login/'),              name='logout'),
    path('register/', views.register,                                                           name='register'),

    # Password management
    path('password-change/', views.change_password, name='password_change'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'password-reset-confirm/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'password-reset/complete/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),

    # Profile
    path('profile/', views.profile, name='profile'),
    path('change-password/', views.change_password, name='change_password'),
    path('onboarding/', views.onboarding, name='onboarding'),

    # 2FA
    path('two-factor/setup/', views.two_factor_setup, name='two_factor_setup'),
    path('two-factor/verify/', views.two_factor_verify, name='two_factor_verify'),
    path('two-factor/settings/', views.two_factor_settings, name='two_factor_settings'),
]
