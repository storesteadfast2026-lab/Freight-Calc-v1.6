from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.clients.models import Client
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.postcodes_apply import (
    PostcodesApplyBlocked,
    apply_approved_postcodes,
    ensure_postcodes_apply_audit_event,
    postcodes_review_completion,
    rollback_latest_postcodes_apply,
)
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb


class PostcodesReviewAuditCompletionTests(TestCase):
    def setUp(self):
        self.client_obj = Client.objects.create(
            code='STH',
            name='Stenhoj Australia',
            active=True,
        )
        self.user = get_user_model().objects.create_user(
            username='reviewer',
            password='x',
        )

    def _file(self, source_row, created_rows=None):
        return ExternalDataFile.objects.create(
            client=self.client_obj,
            file_type='SUBURBS',
            source_method='FTP_DROP',
            original_filename='postcodes.csv',
            status='ACTIVE',
            validation_summary={'new_rows_preview': [source_row]},
            import_summary={'created_rows': created_rows or []},
        )

    def _replace_fixture(self):
        old = Suburb.objects.create(
            suburb_name='WHITLAM',
            state='ACT',
            postcode='2615',
        )
        created = Suburb.objects.create(
            suburb_name='WHITLAM',
            state='ACT',
            postcode='2611',
        )
        external_file = self._file(
            {
                'suburb': 'WHITLAM',
                'state': 'ACT',
                'postcode': '2611',
                'action': 'ADD',
            },
            [
                {
                    'suburb_id': created.pk,
                    'suburb': 'WHITLAM',
                    'state': 'ACT',
                    'postcode': '2611',
                }
            ],
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)
        item.selected_historical_suburb_id = old.pk
        item.decision = 'ACCEPT_SOURCE'
        item.save(
            update_fields=[
                'selected_historical_suburb_id',
                'decision',
            ]
        )
        return external_file, old

    def test_apply_creates_one_audit_event_and_marks_review_complete(self):
        external_file, old = self._replace_fixture()

        result = apply_approved_postcodes(
            external_file.pk,
            actor=self.user,
        )

        old.refresh_from_db()
        self.assertEqual(old.postcode, '2611')

        events = AuditEvent.objects.filter(
            external_file=external_file,
            event_type='POSTCODES_REVIEW_APPLIED',
        )
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.metadata['batch_id'], result['batch_id'])
        self.assertEqual(event.metadata['change_count'], 1)

        completion = postcodes_review_completion(external_file.pk)
        self.assertTrue(completion['completed'])
        self.assertEqual(completion['change_count'], 0)
        self.assertEqual(completion['audit_event_id'], event.pk)

    def test_second_apply_is_blocked_and_does_not_create_empty_batch(self):
        external_file, _ = self._replace_fixture()
        apply_approved_postcodes(external_file.pk, actor=self.user)

        external_file.refresh_from_db()
        batches_before = list(
            (external_file.import_summary or {}).get('review_apply_batches') or []
        )
        audits_before = AuditEvent.objects.filter(
            external_file=external_file,
            event_type='POSTCODES_REVIEW_APPLIED',
        ).count()

        with self.assertRaises(PostcodesApplyBlocked):
            apply_approved_postcodes(external_file.pk, actor=self.user)

        external_file.refresh_from_db()
        batches_after = list(
            (external_file.import_summary or {}).get('review_apply_batches') or []
        )
        audits_after = AuditEvent.objects.filter(
            external_file=external_file,
            event_type='POSTCODES_REVIEW_APPLIED',
        ).count()

        self.assertEqual(len(batches_after), len(batches_before))
        self.assertEqual(audits_after, audits_before)

    def test_audit_backfill_is_idempotent(self):
        external_file, _ = self._replace_fixture()
        result = apply_approved_postcodes(external_file.pk, actor=self.user)

        AuditEvent.objects.filter(
            external_file=external_file,
            event_type='POSTCODES_REVIEW_APPLIED',
        ).delete()

        first = ensure_postcodes_apply_audit_event(
            external_file.pk,
            actor=self.user,
            batch_id=result['batch_id'],
        )
        second = ensure_postcodes_apply_audit_event(
            external_file.pk,
            actor=self.user,
            batch_id=result['batch_id'],
        )

        self.assertTrue(first['created'])
        self.assertFalse(second['created'])
        self.assertEqual(first['audit_event_id'], second['audit_event_id'])
        self.assertEqual(
            AuditEvent.objects.filter(
                external_file=external_file,
                event_type='POSTCODES_REVIEW_APPLIED',
            ).count(),
            1,
        )

    def test_completion_requires_audit_event(self):
        external_file, _ = self._replace_fixture()
        apply_approved_postcodes(external_file.pk, actor=self.user)
        AuditEvent.objects.filter(
            external_file=external_file,
            event_type='POSTCODES_REVIEW_APPLIED',
        ).delete()

        completion = postcodes_review_completion(external_file.pk)

        self.assertFalse(completion['completed'])
        self.assertEqual(completion['change_count'], 0)
        self.assertIsNone(completion['audit_event_id'])

    def test_rollback_creates_audit_event_and_reopens_review(self):
        external_file, old = self._replace_fixture()
        result = apply_approved_postcodes(external_file.pk, actor=self.user)

        rollback_latest_postcodes_apply(
            external_file.pk,
            actor=self.user,
        )

        old.refresh_from_db()
        self.assertEqual(old.postcode, '2615')
        self.assertTrue(
            AuditEvent.objects.filter(
                external_file=external_file,
                event_type='POSTCODES_REVIEW_ROLLED_BACK',
                metadata__apply_batch_id=result['batch_id'],
            ).exists()
        )
        self.assertFalse(
            postcodes_review_completion(external_file.pk)['completed']
        )

    def test_first_no_change_apply_closes_review_but_repeat_is_blocked(self):
        created = Suburb.objects.create(
            suburb_name='STREAM HILL',
            state='NSW',
            postcode='2526',
        )
        external_file = self._file(
            {
                'suburb': 'STREAM HILL',
                'state': 'NSW',
                'postcode': '2526',
                'action': 'ADD',
            },
            [
                {
                    'suburb_id': created.pk,
                    'suburb': 'STREAM HILL',
                    'state': 'NSW',
                    'postcode': '2526',
                }
            ],
        )
        sync_postcodes_review_items(external_file)
        item = ExternalDataReviewItem.objects.get(external_file=external_file)
        item.decision = 'ACCEPT_SOURCE'
        item.save(update_fields=['decision'])

        first = apply_approved_postcodes(
            external_file.pk,
            actor=self.user,
        )

        self.assertEqual(first['change_count'], 0)
        self.assertEqual(first['no_change_count'], 1)
        self.assertEqual(
            AuditEvent.objects.filter(
                external_file=external_file,
                event_type='POSTCODES_REVIEW_APPLIED',
            ).count(),
            1,
        )
        self.assertTrue(
            postcodes_review_completion(external_file.pk)['completed']
        )

        with self.assertRaises(PostcodesApplyBlocked):
            apply_approved_postcodes(
                external_file.pk,
                actor=self.user,
            )

