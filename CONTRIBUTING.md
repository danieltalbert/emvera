# Contributing

## Before changing code

Keep each change narrow and state its user-facing outcome. Authentication, owner scoping, financial calculations, integrations, and database migrations require focused regression tests and an explicit risk note in the pull request.

## Local checks

```powershell
$env:DJANGO_SECRET_KEY = 'local-test-key'
$env:DJANGO_ALLOWED_HOSTS = 'testserver,localhost,127.0.0.1'
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python -m pip check
ruff format --check .
ruff check .
```

For template changes, verify a desktop and mobile viewport, keyboard focus, visible headings, labels, overflow, and browser-console errors.

## Code conventions

- Follow Django conventions and use four-space indentation in Python.
- Use `snake_case` for functions, fields, routes, and templates; use `PascalCase` for classes and forms.
- Scope every query for user-owned data through the authenticated user or an already owner-scoped parent.
- Keep provider SDK calls in the relevant integration adapter rather than templates or domain views.
- Add comments for security boundaries and non-obvious decisions; avoid comments that merely restate the code.
- Never log secrets, raw access tokens, passwords, TOTP values, or full provider payloads.

## Pull requests

Use the pull-request template. Include exact commands and results, environment or migration changes, and visual evidence for UI work. Do not combine unrelated refactors with a security or financial-logic fix.
