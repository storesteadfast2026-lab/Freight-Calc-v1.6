import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('imports', '0009_product_source_rejected_rows'),
    ]

    operations = [
        migrations.AddField(
            model_name='productsourcerejectedrow',
            name='proposed_data',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='productsourcerejectedrow',
            name='repair_status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending review'),
                    ('PROPOSED', 'Proposal saved'),
                    ('APPROVED', 'Approved into staging'),
                ],
                db_index=True,
                default='PENDING',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='productsourcerejectedrow',
            name='review_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='productsourcerejectedrow',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='productsourcerejectedrow',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_product_source_rejections',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='productsourcerejectedrow',
            name='staged_row',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='approved_repair',
                to='imports.productsourcerow',
            ),
        ),
    ]
