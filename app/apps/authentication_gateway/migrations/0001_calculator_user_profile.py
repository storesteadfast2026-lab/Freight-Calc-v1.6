# Generated for STH Freight Calculator user access Version 1.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('clients', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CalculatorUserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('CUSTOMER_USER', 'Customer User'), ('INTERNAL_USER', 'Internal User')], max_length=30)),
                ('client_scope', models.CharField(choices=[('SINGLE_CLIENT', 'Single client'), ('ALL_CLIENTS', 'All clients'), ('SELECTED_CLIENTS', 'Selected clients')], max_length=30)),
                ('calculator_access', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('allowed_clients', models.ManyToManyField(blank=True, help_text='Used only for Internal User with Selected clients scope.', related_name='authorized_internal_users', to='clients.client')),
                ('client', models.ForeignKey(blank=True, help_text='Required only for Customer User.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='customer_users', to='clients.client')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='calculator_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['user__username'],
            },
        ),
        migrations.AddConstraint(
            model_name='calculatoruserprofile',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        role='CUSTOMER_USER',
                        client_scope='SINGLE_CLIENT',
                        client__isnull=False,
                    )
                    | models.Q(
                        role='INTERNAL_USER',
                        client_scope__in=['ALL_CLIENTS', 'SELECTED_CLIENTS'],
                        client__isnull=True,
                    )
                ),
                name='authgw_profile_role_scope_client_valid',
            ),
        ),
    ]
