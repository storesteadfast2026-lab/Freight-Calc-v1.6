from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0006_external_data_review_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='externaldatareviewitem',
            name='corrected_suburb',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='externaldatareviewitem',
            name='corrected_state',
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name='externaldatareviewitem',
            name='corrected_postcode',
            field=models.CharField(blank=True, max_length=10),
        ),
    ]
