import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch

from apps.audit.models import AuditEvent
from apps.carriers.models import Carrier, CarrierService, ClientCarrierConfig
from apps.clients.models import Client
from apps.imports.models import ExternalDataFile
from apps.imports.services.fuel import (
    FuelImportError,
    activate_fuel_file,
    calculate_sha256,
    reapply_active_fuel_rates,
    rollback_fuel_file,
    validate_fuel_file,
)


VALID_CSV = b"""master_rate,info,rate,updated,expires,warnings\n1420,Purple,0.095,01/01/2099,31/12/2099,\n1115,,0.26,,,\n"""


class FuelImportTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_dir.name, FUEL_RATE_MAX='1.0')
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.user = get_user_model().objects.create_user(
            username='fuel-admin', password='password', is_staff=True, is_superuser=True
        )
        self.client_obj = Client.objects.create(code='STH', name='Stenhoj Australia', active=True)
        carrier = Carrier.objects.create(code='TEAMEX', name='Team Global Express')
        service = CarrierService.objects.create(carrier=carrier, service_code='ROAD')
        self.config = ClientCarrierConfig.objects.create(
            client=self.client_obj,
            carrier_service=service,
            ratecard='1420',
            fuel_levy=Decimal('0.080000'),
            fuel_levy_source='LEGACY_WORKBOOK',
        )

    def create_fuel_file(self, content=VALID_CSV, status='UPLOADED', filename='fuel.csv'):
        external_file = ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type='FUEL',
            source_method='ADMIN_UPLOAD',
            original_filename=filename,
            status=status,
            uploaded_by=self.user,
            file_size_bytes=len(content),
            sha256=calculate_sha256(content),
            mime_type='text/csv',
        )
        external_file.uploaded_file.save(filename, ContentFile(content), save=True)
        external_file.stored_path = external_file.uploaded_file.name
        external_file.save(update_fields=['stored_path'])
        return external_file

    def test_validate_activate_and_rollback(self):
        external_file = self.create_fuel_file()

        validation = validate_fuel_file(external_file, actor=self.user)
        external_file.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATED')
        self.assertEqual(validation['rows_valid'], 2)
        self.assertEqual(validation['configs_to_update'], 1)

        result = activate_fuel_file(external_file, actor=self.user)
        external_file.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(external_file.status, 'ACTIVE')
        self.assertEqual(result['configs_updated'], 1)
        self.assertEqual(self.config.fuel_levy, Decimal('0.095000'))
        self.assertEqual(self.config.fuel_levy_source, 'ADMIN_UPLOAD')
        self.assertEqual(self.config.fuel_data_file_id, external_file.pk)
        self.assertTrue(AuditEvent.objects.filter(event_type='FUEL_IMPORT_ACTIVATED').exists())

        rollback = rollback_fuel_file(external_file, actor=self.user, reason='Test rollback')
        external_file.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(rollback['configs_restored'], 1)
        self.assertEqual(external_file.status, 'ROLLED_BACK')
        self.assertEqual(self.config.fuel_levy, Decimal('0.080000'))
        self.assertEqual(self.config.fuel_levy_source, 'LEGACY_WORKBOOK')
        self.assertIsNone(self.config.fuel_data_file_id)
        self.assertTrue(AuditEvent.objects.filter(event_type='FUEL_IMPORT_ROLLED_BACK').exists())

    def test_validation_rejects_missing_columns_without_changing_config(self):
        external_file = self.create_fuel_file(b'master_rate,rate\n1420,0.1\n')
        with self.assertRaises(FuelImportError):
            validate_fuel_file(external_file, actor=self.user)
        external_file.refresh_from_db()
        self.config.refresh_from_db()
        self.assertEqual(external_file.status, 'VALIDATION_FAILED')
        self.assertEqual(self.config.fuel_levy, Decimal('0.080000'))
        self.assertTrue(AuditEvent.objects.filter(event_type='FUEL_VALIDATION_FAILED').exists())

    def test_duplicate_active_file_cannot_be_activated_again(self):
        first = self.create_fuel_file()
        validate_fuel_file(first, actor=self.user)
        activate_fuel_file(first, actor=self.user)

        second = self.create_fuel_file(filename='fuel-copy.csv')
        validation = validate_fuel_file(second, actor=self.user)
        self.assertEqual(validation['duplicate_file_id'], first.pk)
        with self.assertRaises(FuelImportError):
            activate_fuel_file(second, actor=self.user)

    def test_active_fuel_is_reapplied_after_config_rebuild(self):
        external_file = self.create_fuel_file()
        validate_fuel_file(external_file, actor=self.user)
        activate_fuel_file(external_file, actor=self.user)

        self.config.fuel_levy = Decimal('0.010000')
        self.config.fuel_levy_source = 'LEGACY_WORKBOOK'
        self.config.fuel_data_file = None
        self.config.save(update_fields=['fuel_levy', 'fuel_levy_source', 'fuel_data_file'])

        result = reapply_active_fuel_rates(self.client_obj)
        self.config.refresh_from_db()
        self.assertEqual(result['configs_reapplied'], 1)
        self.assertEqual(self.config.fuel_levy, Decimal('0.095000'))
        self.assertEqual(self.config.fuel_data_file_id, external_file.pk)


    def test_admin_fetch_page_and_fetch_operation(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse('admin:imports_externaldatafile_fetch_fuel'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'https://www.poscat.com.au/fuelsc/fuel.csv')

        with patch(
            'apps.imports.services.fuel.download_source',
            return_value=(VALID_CSV, 'text/csv'),
        ):
            response = self.client.post(
                reverse('admin:imports_externaldatafile_fetch_fuel'),
                {'client': self.client_obj.pk, 'notes': 'Manual weekly check'},
            )
        self.assertEqual(response.status_code, 302)
        downloaded = ExternalDataFile.objects.get(source_method='ADMIN_WEB_FETCH')
        self.assertEqual(downloaded.status, 'VALIDATED')
        self.assertTrue(AuditEvent.objects.filter(event_type='FUEL_FETCH_COMPLETED').exists())

    def test_expired_file_requires_superuser_force_and_justification(self):
        expired = b"""master_rate,info,rate,updated,expires,warnings\n1420,Purple,0.10,01/01/2020,02/01/2020,Expired\n"""
        external_file = self.create_fuel_file(expired)
        validate_fuel_file(external_file, actor=self.user)
        with self.assertRaises(FuelImportError):
            activate_fuel_file(external_file, actor=self.user)
        result = activate_fuel_file(
            external_file,
            actor=self.user,
            force_expired=True,
            justification='Approved for controlled historical validation.',
        )
        self.assertTrue(result['forced_expired_activation'])
