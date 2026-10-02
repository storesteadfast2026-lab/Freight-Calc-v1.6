"""Export read-only aggregate state for the Calculator App continuity archive."""

import json
import re
from collections import Counter
from hashlib import sha256
from pathlib import PureWindowsPath

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.clients.models import Client, Customer
from apps.imports.models import (
    ExternalDataCorrectionMemory, ExternalDataFile, ProductCorrectionRound,
    ProductMaster, ProductReconciliationDecision,
)
from apps.imports.services.product_master import (
    new_product_warnings, reconciliation_rows_for_customer,
)
from apps.imports.services.product_reconciliation_workspace import build_workspace
from apps.products.models import Product
from apps.saved_estimates.models import SavedEstimate


def safe_filename(value):
    """Expose only a basename; never carry URL credentials or tokens into archives."""
    name = PureWindowsPath(str(value or '').split('?', 1)[0].split('#', 1)[0]).name
    if re.search(r'(?i)(password|secret|token|credential|api[_-]?key|authorization)', name):
        return '[redacted filename]'
    return name


class Command(BaseCommand):
    help = 'Print current aggregate Product and workflow state as JSON without modifying the database.'

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                if connection.vendor == 'postgresql':
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                state = self._collect()
        except Exception as exc:
            raise CommandError(f'Cannot determine live continuity state: {exc}') from exc
        self.stdout.write(json.dumps(state, sort_keys=True, ensure_ascii=False))

    @staticmethod
    def _collect():
        loader = MigrationLoader(connection)
        pending = sorted(f'{app}.{name}' for app, name in loader.disk_migrations
                         if (app, name) not in loader.applied_migrations)
        if pending:
            raise ValueError('Unapplied migrations: ' + ', '.join(pending))
        applied = sorted(f'{app}.{name}' for app, name in
                         MigrationRecorder.Migration.objects.values_list('app', 'name'))
        latest = ProductMaster.objects.order_by('-uploaded_at', '-pk').first()
        master = ProductMaster.objects.filter(status='VALIDATED').order_by('-uploaded_at', '-pk').first()
        if master:
            with master.original_file.open('rb') as file:
                actual_hash = sha256(file.read()).hexdigest()
            if actual_hash != master.sha256:
                raise ValueError(f'Product Master #{master.pk} file checksum differs')

        products = []
        for client in Client.objects.order_by('code'):
            base = Product.objects.filter(client=client)
            item = {
                'calculator_customer': client.code,
                'operational_products': base.count(),
                'active': base.filter(active=True).count(),
                'inactive': base.filter(active=False).count(),
                'product_master_rows': None, 'same': None, 'different': None,
                'source_only': None, 'operational_only': None,
                'eligible_remaining': None, 'blocked': None,
                'duplicates': None, 'invalid_rows': None,
                'comparison_status': 'no_validated_product_master',
            }
            customer = Customer.objects.filter(linked_client=client, is_special=False).first()
            if master and customer:
                if customer.code not in (master.validation_summary or {}).get('customer_counts', {}):
                    item['comparison_status'] = 'no_rows_for_customer_in_master'
                else:
                    source_rows, invalid = reconciliation_rows_for_customer(
                        master, customer, include_invalid=True,
                    )
                    source = ExternalDataFile(
                        client=client, file_type='PRODUCTS', status='VALIDATED',
                        original_filename=master.original_filename,
                    )
                    rows, summary = build_workspace(
                        source, source_rows=source_rows, pending_rejected=0,
                        include_decisions=False,
                    )
                    invalid_skus = {row['product_code_normalized'] for row in invalid}
                    eligible = {
                        row['sku'] for row in rows
                        if row['status'] == 'SOURCE_ONLY'
                        and row['sku'] not in invalid_skus
                        and not new_product_warnings(row, client)
                    }
                    item.update({
                        'product_master_rows': summary['source_rows'],
                        'same': summary['same'], 'different': summary['different'],
                        'source_only': summary['source_only'],
                        'operational_only': summary['operational_only'],
                        'eligible_remaining': len(eligible),
                        'blocked': summary['source_only'] - len(eligible),
                        'duplicates': summary['duplicate_source'],
                        'invalid_rows': len(invalid),
                        'comparison_status': 'available',
                    })
            elif master:
                item['comparison_status'] = 'no_linked_customer'
            products.append(item)

        active_files = list(ExternalDataFile.objects.filter(
            status__in=('ACTIVE', 'VALIDATED', 'IMPORTED'),
        ).select_related('client').order_by('-uploaded_at', '-pk')[:100])
        sources = [{
            'id': source.pk, 'calculator_customer': source.client.code,
            'file_type': source.file_type, 'status': source.status,
            'filename': safe_filename(source.original_filename),
            'sha256': source.sha256 or None,
            'uploaded_at': source.uploaded_at.isoformat(),
        } for source in active_files]
        return {
            'generated_at': timezone.now().isoformat(),
            'database_vendor': connection.vendor,
            'migrations_applied': applied,
            'migrations_pending': pending,
            'latest_upload': ({'id': latest.pk, 'filename': safe_filename(latest.original_filename),
                               'status': latest.status, 'sha256': latest.sha256,
                               'uploaded_at': latest.uploaded_at.isoformat()}
                              if latest else None),
            'active_product_master': ({
                'id': master.pk, 'filename': safe_filename(master.original_filename),
                'sha256': master.sha256, 'uploaded_at': master.uploaded_at.isoformat(),
                'validation_status_counts': (master.validation_summary or {}).get('status_counts', {}),
            } if master else None),
            'products_by_calculator_customer': products,
            'counts': {
                'calculator_customers': Client.objects.count(),
                'customers': Customer.objects.count(),
                'products': Product.objects.count(),
                'quotations': SavedEstimate.objects.count(),
                'product_masters': ProductMaster.objects.count(),
                'product_reconciliation_decisions': ProductReconciliationDecision.objects.count(),
                'correction_rounds': ProductCorrectionRound.objects.count(),
                'reconciliation_memory': ExternalDataCorrectionMemory.objects.count(),
                'external_data_files': ExternalDataFile.objects.count(),
                'audit_events': AuditEvent.objects.count(),
            },
            'decision_statuses': dict(Counter(ProductReconciliationDecision.objects.values_list(
                'decision_status', flat=True))),
            'correction_round_statuses': dict(Counter(ProductCorrectionRound.objects.values_list(
                'status', flat=True))),
            'active_source_count': ExternalDataFile.objects.filter(
                status__in=('ACTIVE', 'VALIDATED', 'IMPORTED')).count(),
            'source_files_recent': sources,
        }
