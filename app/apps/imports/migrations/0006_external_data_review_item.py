from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('imports', '0005_externaldatafile_ftp_drop_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExternalDataReviewItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('row_key', models.CharField(max_length=255)),
                ('entity_type', models.CharField(blank=True, max_length=50)),
                ('source_data', models.JSONField(blank=True, default=dict)),
                ('current_data', models.JSONField(blank=True, default=dict)),
                ('diagnostic_data', models.JSONField(blank=True, default=dict)),
                ('proposed_action', models.CharField(blank=True, max_length=50)),
                ('decision', models.CharField(default='PENDING', max_length=50)),
                ('notes', models.TextField(blank=True)),
                ('is_current', models.BooleanField(db_index=True, default=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('applied_result', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('external_file', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='external_data_review_items',
                    to='imports.externaldatafile',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='external_data_reviews',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['external_file', 'row_key'],
            },
        ),
        migrations.AddConstraint(
            model_name='externaldatareviewitem',
            constraint=models.UniqueConstraint(
                fields=('external_file', 'row_key'),
                name='imports_review_file_row_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='externaldatareviewitem',
            index=models.Index(
                fields=['external_file', 'decision', 'is_current'],
                name='imp_review_file_dec_idx',
            ),
        ),
    ]
