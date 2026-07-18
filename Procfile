release: python manage.py migrate --noinput
web: gunicorn --config gunicorn.conf.py core.wsgi:application
