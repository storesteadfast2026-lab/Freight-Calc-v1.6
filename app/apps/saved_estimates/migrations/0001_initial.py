import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('clients', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedEstimate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference', models.CharField(max_length=32, unique=True)),
                ('created_by_label', models.CharField(max_length=254)),
                ('schema_version', models.PositiveSmallIntegerField(default=1)),
                ('input_snapshot', models.JSONField()),
                ('result_snapshot', models.JSONField()),
                ('destination_label', models.CharField(blank=True, max_length=220)),
                ('total_weight_kg', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ('total_cubic_m3', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ('best_estimate_ex_gst', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('selected_option_index', models.PositiveIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='saved_estimates', to='clients.client')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='saved_freight_estimates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='savedestimate',
            index=models.Index(fields=['client', '-created_at'], name='saved_est_client_created'),
        ),
        migrations.AddIndex(
            model_name='savedestimate',
            index=models.Index(fields=['created_by', '-created_at'], name='saved_est_user_created'),
        ),
    ]
