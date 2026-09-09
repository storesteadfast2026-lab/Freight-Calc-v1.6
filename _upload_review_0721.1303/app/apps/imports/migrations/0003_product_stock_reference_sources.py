# Generated for STH product/stock reference source imports.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0002_fuel_admin_import'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductSourceRow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_row_number', models.PositiveIntegerField()),
                ('product_code_raw', models.CharField(max_length=255)),
                ('product_code_normalized', models.CharField(db_index=True, max_length=255)),
                ('name', models.CharField(blank=True, max_length=500)),
                ('description', models.TextField(blank=True)),
                ('category', models.CharField(blank=True, max_length=255)),
                ('length_mm', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('width_mm', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('height_mm', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('cubic_m3', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('quantity', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pallet', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('comment', models.TextField(blank=True)),
                ('source_status', models.CharField(blank=True, max_length=100)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('validation_errors', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('external_file', models.ForeignKey(
                    limit_choices_to={'file_type': 'PRODUCTS'},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='product_source_rows',
                    to='imports.externaldatafile',
                )),
            ],
            options={
                'ordering': ['source_row_number'],
            },
        ),
        migrations.CreateModel(
            name='StockSourceRow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_row_number', models.PositiveIntegerField()),
                ('movement_number', models.CharField(blank=True, max_length=100)),
                ('stock_date_raw', models.CharField(blank=True, max_length=100)),
                ('customer', models.CharField(blank=True, max_length=100)),
                ('product_code_raw', models.CharField(max_length=255)),
                ('product_code_normalized', models.CharField(db_index=True, max_length=255)),
                ('sql_name', models.CharField(blank=True, max_length=500)),
                ('quantity', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pallet', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('group1', models.CharField(blank=True, max_length=255)),
                ('location', models.CharField(blank=True, max_length=255)),
                ('stock_class', models.CharField(blank=True, max_length=255)),
                ('sql_stock_ref', models.CharField(blank=True, max_length=255)),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('cubic_m3', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('depot', models.CharField(blank=True, max_length=255)),
                ('sql_group', models.CharField(blank=True, max_length=255)),
                ('sql_group1', models.CharField(blank=True, max_length=255)),
                ('expiry_raw', models.CharField(blank=True, max_length=100)),
                ('pallet_ref', models.CharField(blank=True, max_length=255)),
                ('serial_no', models.CharField(blank=True, max_length=255)),
                ('source_status', models.CharField(blank=True, max_length=100)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('validation_errors', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('external_file', models.ForeignKey(
                    limit_choices_to={'file_type': 'STOCK'},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='stock_source_rows',
                    to='imports.externaldatafile',
                )),
            ],
            options={
                'ordering': ['source_row_number'],
            },
        ),
        migrations.AddConstraint(
            model_name='productsourcerow',
            constraint=models.UniqueConstraint(
                fields=('external_file', 'source_row_number'),
                name='imports_product_source_file_row_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='productsourcerow',
            index=models.Index(
                fields=['external_file', 'product_code_normalized'],
                name='imp_prod_file_sku_idx',
            ),
        ),
        migrations.AddConstraint(
            model_name='stocksourcerow',
            constraint=models.UniqueConstraint(
                fields=('external_file', 'source_row_number'),
                name='imports_stock_source_file_row_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='stocksourcerow',
            index=models.Index(
                fields=['external_file', 'product_code_normalized'],
                name='imp_stock_file_sku_idx',
            ),
        ),
    ]
