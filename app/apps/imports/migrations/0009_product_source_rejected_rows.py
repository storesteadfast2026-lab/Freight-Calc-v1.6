import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0008_external_data_review_historical_selection'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProductSourceRejectedRow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_row_number', models.PositiveIntegerField()),
                ('column_count', models.PositiveIntegerField(blank=True, null=True)),
                ('raw_values', models.JSONField(blank=True, default=list)),
                ('validation_errors', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('external_file', models.ForeignKey(
                    limit_choices_to={'file_type': 'PRODUCTS'},
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='product_rejected_rows',
                    to='imports.externaldatafile',
                )),
            ],
            options={'ordering': ['source_row_number']},
        ),
        migrations.AddConstraint(
            model_name='productsourcerejectedrow',
            constraint=models.UniqueConstraint(
                fields=('external_file', 'source_row_number'),
                name='imports_product_rejected_file_row_uniq',
            ),
        ),
    ]
