"""Export and explicitly approve CUSTOMER assignments for legacy Products."""

import csv
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.imports.models import ExternalDataFile, ProductSourceRow
from apps.imports.services.audit import create_audit_event
from apps.imports.services.xlsx_reader import normalize_product_sku
from apps.products.identity import normalize_customer, valid_customer
from apps.products.models import Product


FIELDS = ('source_file_id', 'source_sha256', 'product_id', 'sku', 'current_customer',
          'candidate_customers', 'assigned_customer', 'approve')


class Command(BaseCommand):
    help = 'Prepare a CUSTOMER mapping CSV; apply only individually approved assignments.'

    def add_arguments(self, parser):
        parser.add_argument('--source-id', required=True, type=int)
        operation = parser.add_mutually_exclusive_group(required=True)
        operation.add_argument('--export', type=str)
        operation.add_argument('--apply', type=str)

    def handle(self, *args, **options):
        source = ExternalDataFile.objects.filter(
            pk=options['source_id'], file_type='PRODUCTS', status='VALIDATED'
        ).select_related('client').first()
        if source is None or not (source.validation_summary or {}).get('customer_column'):
            raise CommandError('Select a validated Product source with a CUSTOMER column.')
        candidates = defaultdict(set)
        for customer, sku in ProductSourceRow.objects.filter(
            external_file=source
        ).values_list('customer_code', 'product_code_normalized').iterator():
            if customer and sku:
                candidates[sku].add(customer)
        if options['export']:
            target = Path(options['export'])
            target.parent.mkdir(parents=True, exist_ok=True)
            count = 0
            with target.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                for product in Product.objects.filter(client=source.client, customer_code='').order_by('sku').iterator():
                    possible = sorted(candidates.get(normalize_product_sku(product.sku), []))
                    writer.writerow({
                        'source_file_id': source.pk, 'source_sha256': source.sha256,
                        'product_id': product.pk, 'sku': product.sku,
                        'current_customer': '', 'candidate_customers': '|'.join(possible),
                        'assigned_customer': possible[0] if len(possible) == 1 else '',
                        'approve': '',
                    })
                    count += 1
            self.stdout.write(f'{count} legacy Products exported to {target}. Review every approved row before Apply.')
            return

        with Path(options['apply']).open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(FIELDS):
                raise CommandError('The mapping CSV columns differ from the exported template.')
            entries = list(reader)
        approvals = [r for r in entries if str(r['approve']).strip().upper() == 'YES']
        if not approvals:
            raise CommandError('No approved rows (approve=YES). Nothing changed.')
        if len({r['product_id'] for r in approvals}) != len(approvals):
            raise CommandError('A Product is approved more than once. Nothing changed.')
        with transaction.atomic():
            assignments = []
            for row in approvals:
                if str(row['source_file_id']) != str(source.pk) or row['source_sha256'] != source.sha256:
                    raise CommandError('The reviewed mapping belongs to a different Source version.')
                product = Product.objects.select_for_update().filter(
                    pk=row['product_id'], client=source.client, sku=row['sku'],
                    customer_code=row['current_customer'],
                ).first()
                if product is None or product.customer_code:
                    raise CommandError(f"Product {row['product_id']} changed since export. Nothing changed.")
                choice = normalize_customer(row['assigned_customer'])
                if not valid_customer(choice) or choice not in candidates.get(normalize_product_sku(product.sku), set()):
                    raise CommandError(f'{product.sku}: CUSTOMER must match a row in this Source. Nothing changed.')
                if Product.objects.filter(client=source.client, sku=product.sku, customer_code=choice).exclude(pk=product.pk).exists():
                    raise CommandError(f'{product.sku}: CUSTOMER already has this SKU. Nothing changed.')
                assignments.append((product, choice))
            for product, choice in assignments:
                product.customer_code = choice
                product.save(update_fields=['customer_code'])
            create_audit_event(
                event_type='PRODUCT_CUSTOMER_ASSIGNMENTS_APPROVED',
                message=f'{len(assignments)} historical Product CUSTOMER assignment(s) approved.',
                client=source.client, external_file=source,
                metadata={'source_sha256': source.sha256,
                          'assignments': [{'product_id': p.pk, 'customer': c} for p, c in assignments]},
            )
        self.stdout.write(self.style.SUCCESS(f'{len(assignments)} approved CUSTOMER assignment(s) saved.'))
