import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
        ('clients', '0001_initial'),
        ('imports', '0002_fuel_admin_import'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditevent',
            name='client',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='audit_events',
                to='clients.client',
            ),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='external_file',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='audit_events',
                to='imports.externaldatafile',
            ),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='severity',
            field=models.CharField(
                choices=[
                    ('INFO', 'Info'),
                    ('WARNING', 'Warning'),
                    ('ERROR', 'Error'),
                    ('CRITICAL', 'Critical'),
                ],
                db_index=True,
                default='INFO',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='ip_address',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='request_id',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name='auditevent',
            name='event_type',
            field=models.CharField(db_index=True, max_length=80),
        ),
        migrations.AlterField(
            model_name='auditevent',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]
