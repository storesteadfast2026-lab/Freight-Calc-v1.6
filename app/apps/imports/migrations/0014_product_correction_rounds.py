from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('imports', '0013_product_reconciliation_apply'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductCorrectionRound',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(default='DRAFT', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('apply_batch_id', models.CharField(blank=True, max_length=32)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('external_file', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='product_correction_rounds', to='imports.externaldatafile')),
            ],
        ),
        migrations.CreateModel(
            name='ProductCorrectionDecision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sku', models.CharField(max_length=255)),
                ('field_decisions', models.JSONField(default=dict)),
                ('custom_values', models.JSONField(blank=True, default=dict)),
                ('notes', models.TextField()),
                ('confirm_source_dimensions', models.BooleanField(default=False)),
                ('source_fingerprint', models.CharField(max_length=64)),
                ('before_values', models.JSONField(default=dict)),
                ('after_values', models.JSONField(blank=True, default=dict)),
                ('reviewed_at', models.DateTimeField(auto_now=True)),
                ('reviewed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('round', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='decisions', to='imports.productcorrectionround')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('round', 'sku'), name='imp_product_corr_round_sku_uniq')]},
        ),
    ]
