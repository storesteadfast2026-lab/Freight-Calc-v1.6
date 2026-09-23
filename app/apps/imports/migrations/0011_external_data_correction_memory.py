import hashlib
import json

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _fingerprint(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=str,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def backfill_product_repair_memory(apps, schema_editor):
    RejectedRow = apps.get_model('imports', 'ProductSourceRejectedRow')
    CorrectionMemory = apps.get_model('imports', 'ExternalDataCorrectionMemory')
    approved_rows = (
        RejectedRow.objects.filter(repair_status='APPROVED')
        .select_related('external_file')
        .order_by('reviewed_at', 'pk')
    )
    for row in approved_rows.iterator():
        source_data = {
            'column_count': row.column_count,
            'raw_values': row.raw_values or [],
        }
        approved_data = row.proposed_data or {}
        memory, _ = CorrectionMemory.objects.update_or_create(
            workflow_key='product_rejected_rows',
            client_id=row.external_file.client_id,
            source_fingerprint=_fingerprint(source_data),
            defaults={
                'record_key': str(approved_data.get('code') or '').strip().upper(),
                'proposal_fingerprint': _fingerprint(approved_data),
                'source_data': source_data,
                'approved_data': approved_data,
                'approval_note': row.review_note or '',
                'origin_external_file_id': row.external_file_id,
                'approved_by_id': row.reviewed_by_id,
                'last_used_at': row.reviewed_at,
                'use_count': 1,
                'is_active': True,
            },
        )
        if row.reviewed_at:
            CorrectionMemory.objects.filter(pk=memory.pk).update(approved_at=row.reviewed_at)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('imports', '0010_product_source_repair_review'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExternalDataCorrectionMemory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('workflow_key', models.CharField(db_index=True, max_length=80)),
                ('record_key', models.CharField(blank=True, db_index=True, max_length=255)),
                ('source_fingerprint', models.CharField(db_index=True, max_length=64)),
                ('proposal_fingerprint', models.CharField(db_index=True, max_length=64)),
                ('source_data', models.JSONField(blank=True, default=dict)),
                ('approved_data', models.JSONField(blank=True, default=dict)),
                ('approval_note', models.TextField(blank=True)),
                ('approved_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('use_count', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_external_data_corrections', to=settings.AUTH_USER_MODEL)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='external_data_correction_memories', to='clients.client')),
                ('origin_external_file', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='originated_correction_memories', to='imports.externaldatafile')),
            ],
            options={
                'ordering': ['workflow_key', 'record_key', '-approved_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='externaldatacorrectionmemory',
            constraint=models.UniqueConstraint(fields=('workflow_key', 'client', 'source_fingerprint'), name='imp_corrmem_source_uniq'),
        ),
        migrations.AddIndex(
            model_name='externaldatacorrectionmemory',
            index=models.Index(fields=['workflow_key', 'client', 'record_key', 'is_active'], name='imp_corrmem_lookup_idx'),
        ),
        migrations.RunPython(backfill_product_repair_memory, migrations.RunPython.noop),
    ]
