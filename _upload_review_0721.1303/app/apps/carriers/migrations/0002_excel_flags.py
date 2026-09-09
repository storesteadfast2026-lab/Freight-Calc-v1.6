# Generated for closer Excel FuelSurcharge mapping.
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('carriers', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='warehouse_handling_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='fixed_handling_charge',
            field=models.DecimalField(decimal_places=4, default=Decimal('0'), max_digits=12),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='zone_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='postcode_zones_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='empty_rate_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='base_status',
            field=models.CharField(default='L', max_length=5),
        ),
        migrations.AddField(
            model_name='clientcarrierconfig',
            name='order_ready_rule',
            field=models.CharField(default='GOOD', max_length=40),
        ),
    ]
