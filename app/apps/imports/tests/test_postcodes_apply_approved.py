from django.contrib.auth import get_user_model
from django.test import TestCase
from apps.clients.models import Client
from apps.imports.models import ExternalDataFile, ExternalDataReviewItem
from apps.imports.services.postcodes_apply import PostcodesApplyBlocked, apply_approved_postcodes, build_postcodes_apply_plan, rollback_latest_postcodes_apply
from apps.imports.services.review import sync_postcodes_review_items
from apps.locations.models import Suburb

class PostcodesApplyApprovedTests(TestCase):
    def setUp(self):
        self.client_obj=Client.objects.create(code='STH',name='Stenhoj Australia',active=True)
        self.user=get_user_model().objects.create_user(username='reviewer',password='x')
    def _file(self,source_row,created_rows=None):
        return ExternalDataFile.objects.create(client=self.client_obj,file_type='SUBURBS',source_method='FTP_DROP',original_filename='postcodes.csv',status='ACTIVE',validation_summary={'new_rows_preview':[source_row]},import_summary={'created_rows':created_rows or []})
    def test_approved_add_already_created_is_not_duplicated(self):
        created=Suburb.objects.create(suburb_name='STREAM HILL',state='NSW',postcode='2526')
        f=self._file({'suburb':'STREAM HILL','state':'NSW','postcode':'2526','action':'ADD'},[{'suburb_id':created.pk,'suburb':'STREAM HILL','state':'NSW','postcode':'2526'}]); sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f); item.decision='ACCEPT_SOURCE'; item.save(update_fields=['decision'])
        p=build_postcodes_apply_plan(f.pk); approved=[r for r in p['items'] if r['decision']=='ACCEPT_SOURCE']; self.assertEqual(approved[0]['display_action'],'ALREADY ADDED')
        apply_approved_postcodes(f.pk,actor=self.user); self.assertEqual(Suburb.objects.filter(suburb_name='STREAM HILL',state='NSW',postcode='2526').count(),1)
    def test_replace_merges_duplicate_and_preserves_historical_id(self):
        old=Suburb.objects.create(suburb_name='WANNIASSA',state='ACT',postcode='2903'); created=Suburb.objects.create(suburb_name='WANIASSA',state='ACT',postcode='2903')
        f=self._file({'suburb':'WANIASSA','state':'ACT','postcode':'2903','action':'ADD','possible_alias':'WANNIASSA'},[{'suburb_id':created.pk,'suburb':'WANIASSA','state':'ACT','postcode':'2903'}]); sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f); item.selected_historical_suburb_id=old.pk; item.decision='ACCEPT_SOURCE'; item.save(update_fields=['selected_historical_suburb_id','decision'])
        result=apply_approved_postcodes(f.pk,actor=self.user); old.refresh_from_db(); self.assertEqual(old.suburb_name,'WANIASSA'); self.assertFalse(Suburb.objects.filter(pk=created.pk).exists()); self.assertEqual(Suburb.objects.filter(suburb_name='WANIASSA',state='ACT',postcode='2903').count(),1); self.assertEqual(result['change_count'],1)
    def test_pending_is_not_applied(self):
        old=Suburb.objects.create(suburb_name='ALBANY',state='WA',postcode='6330'); created=Suburb.objects.create(suburb_name='ALBANY',state='WA',postcode='6331')
        f=self._file({'suburb':'ALBANY','state':'WA','postcode':'6331','action':'ADD'},[{'suburb_id':created.pk,'suburb':'ALBANY','state':'WA','postcode':'6331'}]); sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f); item.selected_historical_suburb_id=old.pk; item.decision='PENDING'; item.save(update_fields=['selected_historical_suburb_id','decision'])
        self.assertEqual(build_postcodes_apply_plan(f.pk)['approved_count'],0)
        with self.assertRaises(PostcodesApplyBlocked): apply_approved_postcodes(f.pk,actor=self.user)
        old.refresh_from_db(); self.assertEqual(old.postcode,'6330'); self.assertTrue(Suburb.objects.filter(pk=created.pk).exists())
    def test_replace_rollback_restores_pre_apply_state(self):
        old=Suburb.objects.create(suburb_name='NEW FARM',state='QLD',postcode='4005'); created=Suburb.objects.create(suburb_name='NEWFARM',state='QLD',postcode='4005'); cid=created.pk
        f=self._file({'suburb':'NEWFARM','state':'QLD','postcode':'4005','action':'ADD','possible_alias':'NEW FARM'},[{'suburb_id':cid,'suburb':'NEWFARM','state':'QLD','postcode':'4005'}]); sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f); item.selected_historical_suburb_id=old.pk; item.decision='ACCEPT_SOURCE'; item.save(update_fields=['selected_historical_suburb_id','decision'])
        apply_approved_postcodes(f.pk,actor=self.user); rollback_latest_postcodes_apply(f.pk,actor=self.user); old.refresh_from_db(); self.assertEqual(old.suburb_name,'NEW FARM'); self.assertEqual(Suburb.objects.get(pk=cid).suburb_name,'NEWFARM')
    def test_manual_override_without_note_is_blocked(self):
        f=self._file({'suburb':'JINGHI','state':'QLD','postcode':'4410','action':'ADD'}); sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f); item.decision='MANUAL_OVERRIDE'; item.corrected_suburb='JINGHI HEIGHTS'; item.corrected_state='QLD'; item.corrected_postcode='4410'; item.notes=''; item.save(update_fields=['decision','corrected_suburb','corrected_state','corrected_postcode','notes'])
        self.assertTrue(build_postcodes_apply_plan(f.pk)['blockers'])
        with self.assertRaises(PostcodesApplyBlocked): apply_approved_postcodes(f.pk,actor=self.user)

    def test_valid_four_digit_postcode_is_not_blocked_by_format_validation(self):
        created=Suburb.objects.create(suburb_name='STREAM HILL',state='NSW',postcode='2526')
        f=self._file(
            {'suburb':'STREAM HILL','state':'NSW','postcode':'2526','action':'ADD'},
            [{'suburb_id':created.pk,'suburb':'STREAM HILL','state':'NSW','postcode':'2526'}],
        )
        sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f)
        item.decision='ACCEPT_SOURCE'
        item.save(update_fields=['decision'])

        plan=build_postcodes_apply_plan(f.pk)
        approved=[r for r in plan['items'] if r['decision']=='ACCEPT_SOURCE']

        self.assertFalse(plan['blockers'], plan['blockers'])
        self.assertEqual(approved[0]['display_action'],'ALREADY ADDED')

    def test_invalid_postcode_format_is_blocked(self):
        f=self._file({'suburb':'BAD TEST','state':'NSW','postcode':'25A6','action':'ADD'})
        sync_postcodes_review_items(f)
        item=ExternalDataReviewItem.objects.get(external_file=f)
        item.decision='ACCEPT_SOURCE'
        item.save(update_fields=['decision'])

        plan=build_postcodes_apply_plan(f.pk)

        self.assertTrue(plan['blockers'])
        self.assertTrue(
            any('four digits' in blocker for blocker in plan['blockers']),
            plan['blockers'],
        )

