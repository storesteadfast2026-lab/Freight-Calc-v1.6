"""Validate and import the independent Translogic Customer master."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import xlrd
from django.core.files.base import ContentFile
from django.db import transaction

from apps.imports.services.audit import create_audit_event

from .models import Client, Customer, CustomerImport


HEADERS = (
    'code', 'name', 'group', 'group1', 'group2', 'their_code',
    'wh_pick_code', 'acn', 'abn', 'gst_code', 'sett_days',
    'paydays_type', 'date', 'user',
)
SOURCE_FIELDS = (
    'name', 'group', 'group1', 'group2', 'their_code', 'wh_pick_code',
    'acn', 'abn', 'gst_code', 'sett_days', 'paydays_type', 'source_date',
    'source_user', 'is_special', 'source_row_number', 'raw_data',
)
TEXT_LIMITS = {
    'code': 20, 'name': 150, 'group': 40, 'group1': 40,
    'group2': 40, 'their_code': 40, 'wh_pick_code': 40,
    'acn': 40, 'abn': 40, 'gst_code': 40, 'paydays_type': 40,
    'user': 80,
}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class CustomerImportError(ValueError):
    pass


@dataclass
class CustomerPreview:
    rows: list[dict]
    errors: list[str]
    duplicates: list[str]
    new: list[str]
    changed: list[str]
    unchanged: list[str]
    missing: list[str]
    links: list[str]
    special: list[str]

    @property
    def total_rows(self):
        return len(self.rows) + len(self.errors) + len(self.duplicates)


def master_state_digest() -> str:
    """Reject confirmation if the Customers or possible links changed since preview."""
    state = {
        'customers': [(c.code, c.updated_at.isoformat(), c.linked_client_id)
                      for c in Customer.objects.order_by('code')],
        'clients': list(Client.objects.order_by('code').values_list('code', 'pk', 'active')),
    }
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def parse_customers_xls(content: bytes) -> tuple[list[dict], list[str], list[str]]:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise CustomerImportError('Customer XLS is empty or exceeds 5 MB.')
    if not content.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise CustomerImportError('Upload a genuine legacy .xls Customer workbook.')
    try:
        book = xlrd.open_workbook(file_contents=content, encoding_override='cp1252')
    except (xlrd.XLRDError, OSError, ValueError, IndexError) as exc:
        raise CustomerImportError(f'Cannot read Customer XLS: {exc}') from exc
    if book.nsheets != 1:
        raise CustomerImportError('Expected one Customer worksheet.')
    sheet = book.sheet_by_index(0)
    if sheet.ncols != 14 or tuple(str(sheet.cell_value(0, i)).strip().lower() for i in range(14)) != HEADERS:
        raise CustomerImportError('Customer workbook must have the 14 expected columns in their original order.')
    rows, errors, duplicates, seen = [], [], [], set()
    for index in range(1, sheet.nrows):
        cells = [sheet.cell(index, col) for col in range(14)]
        raw = {key: cell.value for key, cell in zip(HEADERS, cells)}
        values = {key: str(raw[key]).strip() for key in HEADERS if key not in {'date', 'sett_days'}}
        code = values['code'].upper()
        values['code'] = code
        issue = None
        if not code or not values['name']:
            issue = 'Code and name are required.'
        elif any(len(values[key]) > limit for key, limit in TEXT_LIMITS.items()):
            issue = 'A field exceeds its supported length.'
        if issue:
            errors.append(f'Row {index + 1}: {issue}')
            continue
        if code in seen:
            duplicates.append(f'Row {index + 1}: duplicate code {code}.')
            continue
        seen.add(code)
        try:
            days = raw['sett_days']
            if days == '':
                days = None
            elif isinstance(days, bool) or float(days) < 0 or float(days) > 65535 or not float(days).is_integer():
                raise ValueError('sett_days must be a whole number between 0 and 65535')
            else:
                days = int(float(days))
            serial = raw['date']
            source_date = None
            if serial != '':
                if cells[12].ctype not in (xlrd.XL_CELL_DATE, xlrd.XL_CELL_NUMBER):
                    raise ValueError('date must be an Excel date')
                stamp = xlrd.xldate_as_datetime(serial, book.datemode)
                if stamp.time().isoformat() != '00:00:00':
                    raise ValueError('date must not include a time')
                source_date = stamp.date()
        except (ValueError, TypeError, OverflowError, xlrd.XLDateError) as exc:
            errors.append(f'Row {index + 1}: {exc}')
            continue
        rows.append({
            'code': code, 'name': values['name'], 'group': values['group'],
            'group1': values['group1'], 'group2': values['group2'],
            'their_code': values['their_code'], 'wh_pick_code': values['wh_pick_code'],
            'acn': values['acn'], 'abn': values['abn'], 'gst_code': values['gst_code'],
            'sett_days': days, 'paydays_type': values['paydays_type'],
            'source_date': source_date, 'source_user': values['user'],
            'is_special': code == '*', 'source_row_number': index + 1,
            'raw_data': raw,
        })
    if not rows:
        raise CustomerImportError('No valid Customer rows were found.')
    return rows, errors, duplicates


def preview_customers(content: bytes) -> CustomerPreview:
    rows, errors, duplicates = parse_customers_xls(content)
    existing = {customer.code: customer for customer in Customer.objects.all()}
    clients = {client.code: client for client in Client.objects.filter(active=True)}
    new, changed, unchanged, links = [], [], [], []
    for row in rows:
        code = row['code']
        current = existing.get(code)
        if current is None:
            new.append(code)
        elif any(getattr(current, key) != row[key] for key in SOURCE_FIELDS):
            changed.append(code)
        else:
            unchanged.append(code)
        if code != '*' and code in clients and (current is None or current.linked_client_id is None):
            links.append(code)
    codes = {row['code'] for row in rows}
    return CustomerPreview(rows, errors, duplicates, new, changed, unchanged,
                           sorted(set(existing) - codes), links,
                           [row['code'] for row in rows if row['is_special']])


def import_customers(content: bytes, *, filename: str, actor=None,
                     expected_digest: str | None = None,
                     expected_state: str | None = None, request=None) -> CustomerImport:
    """Confirm an exact preview; make all Customer and history changes atomically."""
    if expected_digest and hashlib.sha256(content).hexdigest() != expected_digest:
        raise CustomerImportError('The validated Customer file has changed. Validate it again.')
    with transaction.atomic():
        # Serialise imports against one another without creating a Client.
        list(Client.objects.select_for_update().values_list('pk', flat=True))
        if expected_state and master_state_digest() != expected_state:
            raise CustomerImportError('Customer records changed after preview. Validate the file again.')
        preview = preview_customers(content)
        if preview.errors or preview.duplicates:
            raise CustomerImportError('Invalid or duplicate rows: correct the XLS before importing.')
        existing = {customer.code: customer for customer in Customer.objects.select_for_update()}
        clients = {client.code: client for client in Client.objects.filter(active=True)}
        linked = []
        for row in preview.rows:
            code = row['code']
            customer = existing.get(code)
            if customer is None:
                customer = Customer(code=code)
                existing[code] = customer
            for key in SOURCE_FIELDS:
                setattr(customer, key, row[key])
            match = clients.get(code) if code != '*' else None
            if match and customer.linked_client_id is None:
                already_linked = Customer.objects.filter(linked_client=match).exclude(code=code).exists()
                if already_linked:
                    raise CustomerImportError(f'Calculator Customer {code} is linked to a different Customer.')
                customer.linked_client = match
                linked.append(code)
            customer.full_clean()
            if code in preview.new or code in preview.changed or code in linked:
                customer.save()
        history = CustomerImport.objects.create(
            filename=Path(filename).name[:255],
            sha256=hashlib.sha256(content).hexdigest(),
            uploaded_by=actor if getattr(actor, 'is_authenticated', False) else None,
            total_rows=preview.total_rows,
            created_count=len(preview.new), updated_count=len(preview.changed),
            unchanged_count=len(preview.unchanged), missing_count=len(preview.missing),
            invalid_count=0, duplicate_count=0, special_count=len(preview.special),
            details={'new': preview.new, 'changed': preview.changed,
                     'missing': preview.missing, 'linked': linked},
        )
        history.source_file.save(Path(filename).name, ContentFile(content), save=True)
        create_audit_event(
            event_type='CUSTOMER_MASTER_IMPORTED',
            message=f'Customer master imported from {history.filename}.',
            actor=actor, request=request,
            metadata={'customer_import_id': history.pk, 'sha256': history.sha256,
                      'created': history.created_count, 'updated': history.updated_count,
                      'unchanged': history.unchanged_count, 'missing': history.missing_count},
        )
        return history
