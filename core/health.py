"""Minimal liveness and database-readiness probes for deployment platforms."""

import logging

from django.db import connections
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def healthz(request):
    return JsonResponse({'status': 'ok'})


def readyz(request):
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        logger.exception('Database readiness probe failed.')
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ready'})
