# Dockerfile for the Emvera finance app
# Emvera targets Django 6.0, which requires Python 3.12+.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies first for better layer caching.
# psycopg2-binary, Pillow and cryptography all ship manylinux wheels,
# so no system build toolchain is required.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the application source.
COPY . .

# Collect static assets. settings.py reads DJANGO_SECRET_KEY at import time,
# so provide a throwaway value for this build-only step (never used at runtime).
RUN DJANGO_SECRET_KEY=build-only-not-a-real-secret python manage.py collectstatic --noinput

EXPOSE 8000

# Run migrations then serve with gunicorn. DJANGO_SECRET_KEY (and any other
# runtime config) is supplied via the environment / .env at `docker run` time.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
