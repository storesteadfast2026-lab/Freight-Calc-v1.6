from django.core.management.base import BaseCommand
from django.db import transaction

from apps.imports.models import (
    ExternalDataFile,
    ProductSourceRejectedRow,
    ProductSourceRow,
)
from apps.imports.services.audit import create_audit_event
from apps.imports.services.product_repair import _refresh_repair_summary


class Command(BaseCommand):
    help = 'Remove approved Product repair rows from staging before migration 0010 rollback.'

    def handle(self, *args, **options):
        repaired_rows_removed = 0
        with transaction.atomic():
            file_ids = list(
                ProductSourceRejectedRow.objects.exclude(repair_status='PENDING')
                .values_list('external_file_id', flat=True)
                .distinct()
            )
            for file_id in file_ids:
                external_file = ExternalDataFile.objects.select_for_update().get(pk=file_id)
                reviews = ProductSourceRejectedRow.objects.select_for_update().filter(
                    external_file=external_file
                )
                staged_ids = list(
                    reviews.exclude(staged_row_id=None)
                    .values_list('staged_row_id', flat=True)
                )
                if staged_ids:
                    ProductSourceRow.objects.filter(pk__in=staged_ids).delete()
                    repaired_rows_removed += len(staged_ids)
                reviews.update(
                    repair_status='PENDING',
                    proposed_data={},
                    review_note='',
                    reviewed_by=None,
                    reviewed_at=None,
                    staged_row=None,
                )
                _refresh_repair_summary(external_file)
                create_audit_event(
                    event_type='PRODUCT_SOURCE_REPAIR_ROLLED_BACK',
                    message=(
                        f'Product source repair reviews rolled back for file '
                        f'{external_file.pk}.'
                    ),
                    client=external_file.client,
                    external_file=external_file,
                    metadata={
                        'approved_staging_rows_removed': len(staged_ids),
                        'operational_tables_updated': False,
                    },
                )

        self.stdout.write(self.style.SUCCESS(
            f'Repair review cleanup complete: {len(file_ids)} file(s), '
            f'{repaired_rows_removed} staging object(s) removed.'
        ))
