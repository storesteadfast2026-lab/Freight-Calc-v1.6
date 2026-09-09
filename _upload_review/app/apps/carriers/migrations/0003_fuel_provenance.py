import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('carriers', '0002_excel_flags'),
        ('imports', '0002_fuel_admin_import'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='fuel_levy_source',
            field=models.CharField(default='LEGACY_WORKBOOK', max_length=30),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='fuel_levy_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='fuel_data_file',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='carrier_configs',
                to='imports.externaldatafile',
            ),
        ),
    ]
