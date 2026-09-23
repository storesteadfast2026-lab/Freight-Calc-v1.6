from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0001_initial'),
        ('imports', '0011_external_data_correction_memory'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductReconciliationRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160)),
                ('group_key', models.CharField(db_index=True, max_length=80)),
                ('field_decisions', models.JSONField(default=dict)),
                ('notes', models.TextField(blank=True)),
                ('active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product_reconciliation_rules', to='clients.client')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_product_reconciliation_rules', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['client', 'group_key', 'name']},
        ),
        migrations.CreateModel(
            name='ProductReconciliationDecision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_code_normalized', models.CharField(db_index=True, max_length=255)),
                ('source_row_number', models.PositiveIntegerField(blank=True, null=True)),
                ('row_status', models.CharField(max_length=30)),
                ('group_key', models.CharField(db_index=True, max_length=80)),
                ('field_decisions', models.JSONField(default=dict)),
                ('custom_values', models.JSONField(blank=True, default=dict)),
                ('decision_status', models.CharField(choices=[('DRAFT', 'Draft'), ('READY', 'Ready for preview')], db_index=True, default='DRAFT', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('external_file', models.ForeignKey(limit_choices_to={'file_type': 'PRODUCTS'}, on_delete=django.db.models.deletion.CASCADE, related_name='product_reconciliation_decisions', to='imports.externaldatafile')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='product_reconciliation_decisions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['external_file', 'product_code_normalized'],
                'permissions': [('manage_product_reconciliation', 'Can manage Product reconciliation drafts')],
            },
        ),
        migrations.AddConstraint(
            model_name='productreconciliationrule',
            constraint=models.UniqueConstraint(fields=('client', 'name'), name='imp_prod_recon_rule_client_name_uniq'),
        ),
        migrations.AddConstraint(
            model_name='productreconciliationdecision',
            constraint=models.UniqueConstraint(fields=('external_file', 'product_code_normalized'), name='imp_prod_recon_file_sku_uniq'),
        ),
    ]
