from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0003_product_stock_reference_sources'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='externaldatafile',
            options={
                'ordering': ['-uploaded_at'],
                'permissions': [
                    ('validate_external_data_file', 'Can validate external data files'),
                    ('activate_fuel', 'Can activate fuel rates'),
                    ('rollback_fuel', 'Can rollback fuel rates'),
                    ('download_external_data_file', 'Can download external data files'),
                ],
            },
        ),
    ]
