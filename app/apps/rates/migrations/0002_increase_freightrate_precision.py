# Generated manually to preserve Excel RATES precision for STH calculator validation.

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rates', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='freightrate',
            name='minimum_charge',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='basic_charge',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='per_subsequent_basic',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='per_kg',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='overweight_charge',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='remote_charge',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='offshore_charge',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
        migrations.AlterField(
            model_name='freightrate',
            name='overlength_charge',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=14),
        ),
    ]
