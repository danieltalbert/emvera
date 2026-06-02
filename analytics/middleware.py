"""
PageViewMiddleware — records one PageView per relevant request.

Design goals:
- Cheap: a single INSERT after the response is built; timing is measured around
  the rest of the stack. Any logging error is swallowed so analytics can never
  break a user request.
- Relevant only: we skip the admin, static/media, the analytics dashboard
  itself, and non-GET / non-HTML responses, so the table reflects real
  viewer-facing navigation rather than asset chatter.
- Privacy-conscious: anonymous visitors are tracked by a salted hash of their
  session key (never the raw key, never an IP), which is enough to count
  distinct visitors and build per-session features for clustering.
"""
from __future__ import annotations

import hashlib
import time

from django.conf import settings
from django.utils import timezone


# Path prefixes we never want in the analytics table.
_SKIP_PREFIXES = ('/admin', '/static', '/media', '/analytics', '/favicon')

# Map the first URL segment to a friendly section label for dashboards.
_SECTION_BY_PREFIX = {
    'investments': 'Investments',
    'debt-management': 'Debt Management',
    'data': 'Data & Accounts',
    'competition': 'Competition',
    'paper-trading': 'Paper Trading',
    'accounts': 'Account',
}


def _section_for(path: str) -> str:
    seg = path.strip('/').split('/', 1)[0]
    return _SECTION_BY_PREFIX.get(seg, 'Other')


def _session_hash(request) -> str:
    """Stable, non-reversible per-session id. Salted with SECRET_KEY so the
    stored value can't be correlated back to the raw session key."""
    key = request.session.session_key
    if not key:
        return ''
    salted = f'{settings.SECRET_KEY}:{key}'.encode('utf-8')
    return hashlib.sha256(salted).hexdigest()


class PageViewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        try:
            self._log(request, response, time.monotonic() - start)
        except Exception:
            # Never let analytics logging break the actual response.
            pass
        return response

    def _log(self, request, response, elapsed_s):
        if request.method != 'GET':
            return
        path = request.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return
        # Only count real HTML page views, not JSON/CSV/redirect chatter.
        content_type = response.get('Content-Type', '')
        if response.status_code != 200 or 'text/html' not in content_type:
            return

        # Import here so app loading / migrations don't import the model early.
        from .models import PageView

        now = timezone.now()
        user = getattr(request, 'user', None)
        is_auth = bool(user and user.is_authenticated)

        PageView.objects.create(
            user=user if is_auth else None,
            session_hash=_session_hash(request),
            path=path[:255],
            section=_section_for(path),
            method=request.method,
            status_code=response.status_code,
            response_ms=int(elapsed_s * 1000),
            is_authenticated=is_auth,
            timestamp=now,
            hour=now.hour,
            weekday=now.weekday(),
        )
