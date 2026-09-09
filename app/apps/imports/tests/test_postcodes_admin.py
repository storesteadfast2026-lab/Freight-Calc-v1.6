from django.contrib import admin
from django.test import SimpleTestCase

from apps.imports.admin import ExternalDataFileAdmin
from apps.imports.models import ExternalDataFile


class PostcodesAdminPresentationTests(SimpleTestCase):
    def setUp(self):
        self.model_admin = ExternalDataFileAdmin(ExternalDataFile, admin.site)

    def _postcodes_file(self):
        return ExternalDataFile(
            file_type='SUBURBS',
            source_method='FTP_DROP',
            original_filename='postcodes.csv',
            sha256='a' * 64,
            status='ACTIVE',
            validation_summary={
                'source_format': 'FTP_POSTCODES',
                'rows_read': 18097,
                'candidate_rows': 18095,
                'existing_confirmed_in_current_source': 18079,
                'new_rows_to_add': 2,
                'existing_not_in_current_source_preserved': 3075,
                'excluded_rows_count': 1,
                'activation_policy': 'ADD_ONLY_PRESERVE_EXISTING',
                'existing_action': 'PRESERVE_UNCHANGED',
                'new_action': 'ADD',
                'not_in_source_action': 'PRESERVE_EXISTING',
                'freightzone_required_for_add': False,
                'multi_postcode_suburb_state_groups': 632,
                'warnings': ['One diagnostic warning.'],
                'new_rows_preview': [
                    {'suburb': 'COLOVALE', 'state': 'NSW', 'postcode': '2575', 'action': 'ADD', 'possible_alias': 'COLO VALE', 'existing_same_suburb_state_postcodes': []},
                    {'suburb': 'ALBANY', 'state': 'WA', 'postcode': '6331', 'action': 'ADD', 'possible_alias': '', 'existing_same_suburb_state_postcodes': ['6330']},
                ],
                'excluded_rows': [
                    {'source_row': 99, 'suburb': 'INVALID', 'state': 'SA', 'postcode': '0000', 'reason': 'invalid Australian postcode 0000'},
                ],
            },
            import_summary={
                'created_count': 2,
                'updated_count': 0,
                'deleted_count': 0,
                'renamed_count': 0,
                'activation_policy': 'ADD_ONLY_PRESERVE_EXISTING',
                'created_rows_origin': 'FTP_POSTCODES',
            },
        )

    def test_suburbs_uses_postcodes_renderer(self):
        html = str(self.model_admin.validation_summary_display(self._postcodes_file()))
        self.assertIn('POSTCODES VALIDATION', html)
        self.assertIn('COLOVALE', html)
        self.assertIn('COLO VALE', html)
        self.assertIn('ALBANY', html)
        self.assertIn('Excluded rows', html)
        self.assertIn('Activation result', html)
        self.assertNotIn('FUEL VALIDATION', html)
        self.assertNotIn('No fuel configuration changes were detected', html)

    def test_suburbs_fieldsets_include_activation_summary(self):
        fieldsets = self.model_admin.get_fieldsets(None, self._postcodes_file())
        fields = [field for _title, options in fieldsets for field in options.get('fields', ())]
        self.assertIn('import_summary_display', fields)

    def test_suburbs_import_summary_is_compact(self):
        html = str(self.model_admin.import_summary_display(self._postcodes_file()))
        self.assertIn('Created', html)
        self.assertIn('Updated', html)
        self.assertIn('ADD_ONLY_PRESERVE_EXISTING', html)

    def test_fuel_still_uses_fuel_renderer(self):
        fuel_file = ExternalDataFile(
            file_type='FUEL',
            source_method='FTP_DROP',
            original_filename='fuel.csv',
            sha256='b' * 64,
            validation_summary={
                'rows_valid': 1,
                'rows_invalid': 0,
                'preview': [],
                'warnings': [],
                'errors': [],
            },
        )
        html = str(self.model_admin.validation_summary_display(fuel_file))
        self.assertIn('FUEL VALIDATION', html)
        self.assertNotIn('POSTCODES VALIDATION', html)
