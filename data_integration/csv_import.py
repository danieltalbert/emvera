"""
CSV → Transaction importer.

Accepts the canonical columns documented on the upload page
(`date`, `amount`, `category`, `description`) plus a handful of common
aliases banks export. Validates each row independently so a single bad
row doesn't kill an otherwise good file.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .models import Transaction

AMOUNT_FIELD = Transaction._meta.get_field('amount')
MAX_TRANSACTION_AMOUNT = Decimal(
    f'{"9" * (AMOUNT_FIELD.max_digits - AMOUNT_FIELD.decimal_places)}.'
    f'{"9" * AMOUNT_FIELD.decimal_places}'
)

COLUMN_ALIASES = {
    'date': {'date', 'transaction date', 'posted date', 'post date'},
    'amount': {'amount', 'value', 'debit', 'transaction amount'},
    'category': {'category', 'type', 'tag'},
    'description': {'description', 'memo', 'details', 'name'},
}

DATE_FORMATS = (
    '%Y-%m-%d',
    '%m/%d/%Y',
    '%d/%m/%Y',
    '%m-%d-%Y',
    '%Y/%m/%d',
)


@dataclass
class ImportResult:
    created: int = 0
    skipped: int = 0
    row_errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.skipped


def _resolve_columns(header: list[str]) -> dict[str, str]:
    """Map canonical names → actual header strings present in the file."""
    lowered = {h.strip().lower(): h for h in header}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                mapping[canonical] = lowered[alias]
                break
    return mapping


def _parse_date(raw: str) -> date | None:
    raw = (raw or '').strip()
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal | None:
    raw = (raw or '').strip().replace('$', '').replace(',', '')
    if not raw:
        return None
    # Handle parenthesised negatives, e.g. "(42.50)".
    if raw.startswith('(') and raw.endswith(')'):
        raw = '-' + raw[1:-1]
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    if amount > MAX_TRANSACTION_AMOUNT or amount < -MAX_TRANSACTION_AMOUNT:
        return None
    return amount


def import_transactions(file_obj, account) -> ImportResult:
    """Parse a CSV file-like object and create Transaction rows under `account`."""
    raw = file_obj.read()
    try:
        text = raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw
    except UnicodeDecodeError:
        result = ImportResult()
        result.row_errors.append('CSV file must be UTF-8 encoded.')
        return result
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        result = ImportResult()
        result.row_errors.append('CSV file is empty or has no header row.')
        return result

    columns = _resolve_columns(reader.fieldnames)
    missing = [c for c in ('date', 'amount', 'category') if c not in columns]
    if missing:
        result = ImportResult()
        result.row_errors.append(
            f'Missing required column(s): {", ".join(missing)}. '
            f'Got headers: {", ".join(reader.fieldnames)}.'
        )
        return result

    result = ImportResult()
    rows_to_create: list[Transaction] = []

    for line_no, row in enumerate(reader, start=2):  # start=2 → header is line 1
        d = _parse_date(row.get(columns['date'], ''))
        amount = _parse_amount(row.get(columns['amount'], ''))
        category = (row.get(columns['category'], '') or '').strip()
        description = ''
        if 'description' in columns:
            description = (row.get(columns['description'], '') or '').strip()

        if d is None:
            result.skipped += 1
            result.row_errors.append(f'Line {line_no}: invalid or missing date.')
            continue
        if amount is None:
            result.skipped += 1
            result.row_errors.append(f'Line {line_no}: invalid or missing amount.')
            continue
        if not category:
            result.skipped += 1
            result.row_errors.append(f'Line {line_no}: missing category.')
            continue

        rows_to_create.append(
            Transaction(
                account=account,
                date=d,
                amount=amount,
                category=category[:100],
                description=description[:255],
                source='csv',
            )
        )

    if rows_to_create:
        Transaction.objects.bulk_create(rows_to_create)
        result.created = len(rows_to_create)

    # Cap the error list so a malformed 10k-row file doesn't flood the page.
    if len(result.row_errors) > 50:
        extra = len(result.row_errors) - 50
        result.row_errors = result.row_errors[:50]
        result.row_errors.append(f'... and {extra} more issue(s).')

    return result
