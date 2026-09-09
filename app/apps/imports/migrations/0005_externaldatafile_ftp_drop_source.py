from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0004_external_data_file_permissions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='externaldatafile',
            name='source_method',
            field=models.CharField(
                choices=[
                    ('ADMIN_UPLOAD', 'Admin upload'),
                    ('ADMIN_WEB_FETCH', 'Admin web fetch'),
                    ('FTP_DROP', 'FTP uploaded_data drop'),
                    ('COMMAND', 'Management command'),
                ],
                default='ADMIN_UPLOAD',
                max_length=30,
            ),
        ),
    ]
