from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0012_product_reconciliation_workspace'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='productreconciliationdecision',
            name='row_action',
            field=models.CharField(
                choices=[
                    ('UPDATE', 'Update operational Product'),
                    ('DELETE', 'Remove operational Product'),
                ],
                default='UPDATE',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='productreconciliationdecision',
            name='applied_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='productreconciliationdecision',
            name='apply_batch_id',
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddField(
            model_name='productreconciliationdecision',
            name='applied_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='applied_product_reconciliation_decisions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='productreconciliationdecision',
            name='decision_status',
            field=models.CharField(
                choices=[
                    ('DRAFT', 'Draft'),
                    ('READY', 'Ready for preview'),
                    ('APPLIED', 'Applied'),
                ],
                db_index=True,
                default='DRAFT',
                max_length=20,
            ),
        ),
    ]
