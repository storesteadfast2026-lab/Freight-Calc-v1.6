from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0007_external_data_review_correction_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='externaldatareviewitem',
            name='selected_historical_suburb_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
