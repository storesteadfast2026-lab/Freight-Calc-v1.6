from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('saved_estimates', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='savedestimate',
            name='reference',
            field=models.CharField(max_length=64, unique=True),
        ),
    ]
