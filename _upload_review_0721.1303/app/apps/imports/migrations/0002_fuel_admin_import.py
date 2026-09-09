import apps.imports.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='externaldatafile',
            name='source_method',
            field=models.CharField(
                choices=[
                    ('ADMIN_UPLOAD', 'Admin upload'),
                    ('ADMIN_WEB_FETCH', 'Admin web fetch'),
                    ('COMMAND', 'Management command'),
                ],
                default='ADMIN_UPLOAD',
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='source_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='uploaded_file',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to=apps.imports.models.external_data_upload_to,
            ),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='file_size_bytes',
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='mime_type',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='sha256',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='validation_summary',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='validated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='validated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='external_files_validated',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='imported_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='external_files_imported',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='activated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='activated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='external_files_activated',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='rolled_back_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='rolled_back_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='external_files_rolled_back',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='externaldatafile',
            name='previous_active_file',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='replacement_files',
                to='imports.externaldatafile',
            ),
        ),
        migrations.AlterField(
            model_name='externaldatafile',
            name='stored_path',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AlterField(
            model_name='externaldatafile',
            name='status',
            field=models.CharField(
                choices=[
                    ('UPLOADED', 'Uploaded'),
                    ('DOWNLOADED', 'Downloaded'),
                    ('VALIDATED', 'Validated'),
                    ('VALIDATION_FAILED', 'Validation failed'),
                    ('ACTIVE', 'Active'),
                    ('IMPORT_FAILED', 'Import failed'),
                    ('ROLLED_BACK', 'Rolled back'),
                    ('IMPORTED', 'Imported'),
                    ('ERROR', 'Error'),
                    ('ARCHIVED', 'Archived'),
                ],
                db_index=True,
                default='UPLOADED',
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name='externaldatafile',
            name='uploaded_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='external_files_uploaded',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
