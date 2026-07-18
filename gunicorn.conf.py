"""Gunicorn runtime settings shared by Docker and process-based hosts."""

import os

bind = f'0.0.0.0:{os.environ.get("PORT", "8000")}'
workers = int(os.environ.get('WEB_CONCURRENCY', '3'))
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '60'))
accesslog = '-'
errorlog = '-'
capture_output = True

# Periodic worker replacement limits the lifetime of an unexpected leak while
# jitter prevents all workers from restarting at the same request boundary.
max_requests = int(os.environ.get('GUNICORN_MAX_REQUESTS', '1000'))
max_requests_jitter = int(os.environ.get('GUNICORN_MAX_REQUESTS_JITTER', '100'))
