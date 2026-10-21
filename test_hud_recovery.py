import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from algorithm_versions import FIELDS, descriptor, stamp_fields
from app_cancel import TaskStopped
from hud_enrichment import run_jobs
from hud_job_store import JobStore
from hud_recovery import clip_id, unfinished_request
from test_hud_enrichment import HudEnrichmentTests


class RecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.files,self.manifest=HudEnrichmentTests().fixture(self.root)
        self.registry={field:descriptor(field,{'rule':'fixture-v1'}) for field in FIELDS}
        self.store=JobStore(self.root/'jobs')
        self.request={'backend':'cpu','cpu_workers':1,'gpu_load':'fast','force':True,
            'fields':['account'],'jobs':[{'directory':str(self.root),'files':list(map(str,self.files))}],
            'recovery_root':str(self.store.root)}
        self.patch=patch('hud_recovery.current_registry',return_value=self.registry);self.patch.start();self.addCleanup(self.patch.stop)

    @staticmethod
    def fresh(fields,**kwargs):
        values={'account':{'name':'NEW_ACCOUNT','confidence':.99},'weapons':[{'id':'r301','name':'R301'}],
            'rank':{'tier':'diamond','division':'IV','confidence':.99},**kwargs}
        return HudEnrichmentTests().fresh(fields,**{field:values[field] for field in fields})

    def execute(self,request=None):
        return run_jobs(request or self.request,direct=True,emit=lambda event:None)

    def test_cancel_resume_reads_only_uncommitted_clip_and_retains_old_values(self):
        with patch('hud_enrichment.recognize_video',side_effect=[self.fresh(['account']),TaskStopped()]):
            with self.assertRaises(TaskStopped):self.execute()
        job=self.store.list_jobs()[0]
        self.assertEqual(self.store.summary(job['id'])['fields']['done'],1)
        saved=json.loads((self.root/'export.json').read_text('utf-8'))
        self.assertEqual(saved['clips'][1]['recognition']['hud_info']['account']['name'],'old_wrong_account')
        with patch('hud_enrichment.recognize_video',return_value=self.fresh(['account'])) as read:
            self.execute({**self.request,'resume_job':job['id']})
        self.assertEqual(read.call_count,1);self.assertEqual(read.call_args.args[0],self.files[1])
        self.assertEqual(self.store.load(job['id'])['status'],'completed')

    def test_atomic_output_failure_never_marks_complete_or_replaces_old_result(self):
        before=(self.root/'export.json').read_bytes()
        with patch('hud_enrichment.recognize_video',return_value=self.fresh(['account'])),patch('hud_enrichment.write_json',side_effect=OSError('commit blocked')):
            result=self.execute()
        self.assertTrue(result['errors']);self.assertEqual((self.root/'export.json').read_bytes(),before)
        self.assertEqual(self.store.summary(self.store.list_jobs()[0]['id'])['fields']['done'],0)

    def test_upgrade_uses_per_clip_fields_and_keeps_unselected_results(self):
        request={**self.request,'fields':['weapons','rank'],'job_kind':'upgrade',
            'selection':{clip_id(self.files[0]):['weapons'],clip_id(self.files[1]):['rank']}}
        with patch('hud_enrichment.recognize_video',side_effect=lambda file,fields,**kwargs:self.fresh(fields)) as read:
            result=self.execute(request)
        self.assertFalse(result['errors']);self.assertEqual({str(call.args[0]):call.args[1] for call in read.call_args_list},
            {str(self.files[0]):['weapons'],str(self.files[1]):['rank']})
        saved=json.loads((self.root/'export.json').read_text('utf-8'))
        for original,current in zip(self.manifest['clips'],saved['clips']):
            self.assertEqual(current['recognition']['hud_info']['account'],original['recognition']['hud_info']['account'])
        self.assertEqual(set(saved['clips'][0]['recognition']['field_algorithms']),{'weapons'})
        self.assertEqual(set(saved['clips'][1]['recognition']['field_algorithms']),{'rank'})

    def test_fallback_skips_child_fields_already_durably_committed(self):
        from hud_job_store import media_identity
        rows=[{'id':clip_id(file),'file':str(file),'directory':str(self.root),'source_identity':media_identity(file),'fields':['account']} for file in self.files]
        job=self.store.create(rows,self.registry)
        self.store.claim(job['id'],rows[0]['id'],['account'])
        self.store.mark_committed(job['id'],rows[0]['id'],['account'],receipt={'output':'committed'})
        filtered=unfinished_request(self.request,{'root':str(self.store.root),'id':job['id']})
        self.assertEqual(filtered['jobs'][0]['files'],[str(self.files[1])])

    def test_performance_source_recipe_change_does_not_reread_semantically_current_core(self):
        manifest=copy.deepcopy(self.manifest)
        for clip in manifest['clips']:
            clip['recognition']=stamp_fields(clip['recognition'],['account'],self.registry,updated_at='old-time')
            clip['recognition']['hud_info']['field_versions']['account']='implementation-hash-changed'
        (self.root/'export.json').write_text(json.dumps(manifest),'utf-8')
        with patch('hud_enrichment.recognize_video') as read:
            result=self.execute({**self.request,'force':False})
        self.assertFalse(result['errors']);read.assert_not_called()
        current=json.loads((self.root/'export.json').read_text('utf-8'))
        self.assertEqual(current['clips'][0]['recognition']['field_algorithms']['account']['updated_at'],'old-time')

    def extra_fixture(self):
        from apex_clipper import fingerprint
        from repair_cached_statistics import PreparedRepair,correction_key
        for index,clip in enumerate(self.manifest['clips']):clip['segment']={'start':index*20,'end':index*20+10}
        (self.root/'export.json').write_text(json.dumps(self.manifest),'utf-8')
        report={'segments':[{**clip['segment'],'counts':{'kills':1,'assists':0,'damage':100},
            'partial':{},'events':[],'native_repaired_fields':['kills','assists','damage'],
            'endpoint':{'native_counter_verified_fields':['kills','assists','damage']}} for clip in self.manifest['clips']]}
        original=self.root/'statistics.json';original.write_text(json.dumps(report),'utf-8');raw=original.read_bytes()
        target=self.root/'data/recognition-corrections'/(correction_key(raw,self.root)+'.json')
        pairs=[(clip,fingerprint(file)) for clip,file in zip(self.manifest['clips'],self.files)]
        def prepared(record,on_activity=None,computed=True):
            index=self.files.index(Path(record['files'][0]));fresh=copy.deepcopy(report)
            fresh['segments'][index]['counts']['damage']=500+index
            fresh.update(version='fixture',counter_recipe='fixture',repair_signature=hashlib.sha256(raw+b'fixturefixture').hexdigest(),correction_context=str(self.root.resolve()).replace('\\','/').lower())
            return PreparedRepair(self.root,hashlib.sha256(raw).hexdigest(),target,fresh,(index,),
                media_identities=(fingerprint(self.files[index]),),computed_fields=('statistics',) if computed else ())
        env=patch.dict(os.environ,{'APEX_DATA_ROOT':str(self.root/'data')});env.start();self.addCleanup(env.stop)
        exported=patch('repair_cached_statistics.exported_clips',return_value=pairs);exported.start();self.addCleanup(exported.stop)
        return {**self.request,'fields':['statistics']},target,prepared

    def test_extra_cancel_resume_commits_only_saved_fields_and_rebases_other_clip(self):
        request,target,prepare=self.extra_fixture();calls=[]
        def interrupted(record,on_activity=None):
            calls.append(record['files'][0])
            if len(calls)==2:raise TaskStopped()
            return prepare(record,on_activity)
        with patch('repair_cached_statistics.prepare_repair',side_effect=interrupted):
            with self.assertRaises(TaskStopped):self.execute(request)
        job=self.store.list_jobs()[0];self.assertEqual(self.store.summary(job['id'])['fields']['done'],1)
        committed=json.loads(target.read_text('utf-8'));first_index=self.files.index(Path(calls[0]))
        self.assertEqual(committed['segments'][first_index]['counts']['damage'],500+first_index)
        with patch('repair_cached_statistics.prepare_repair',side_effect=prepare) as reads:
            result=self.execute({**request,'resume_job':job['id']})
        self.assertFalse(result['errors']);self.assertEqual(reads.call_count,1)
        self.assertNotEqual(reads.call_args.args[0]['files'][0],calls[0])
        self.assertEqual([segment['counts']['damage'] for segment in json.loads(target.read_text('utf-8'))['segments']],[500,501])
        self.assertEqual(self.store.load(job['id'])['status'],'completed')

    def test_extra_provenance_commit_failure_is_retryable_after_sidecar_commit(self):
        import apex_clipper
        request,target,prepare=self.extra_fixture();write=apex_clipper.write_json;blocked=[]
        def fail_export(path,data):
            if Path(path)==self.root/'export.json' and not blocked:
                blocked.append(True);raise OSError('provenance replace blocked')
            return write(path,data)
        with patch('repair_cached_statistics.prepare_repair',side_effect=prepare),patch('apex_clipper.write_json',side_effect=fail_export):result=self.execute(request)
        self.assertTrue(result['errors']);self.assertTrue(target.is_file())
        job=self.store.list_jobs()[0];self.assertEqual(self.store.summary(job['id'])['fields']['done'],1)
        with patch('repair_cached_statistics.prepare_repair',side_effect=prepare) as reads:
            result=self.execute({**request,'resume_job':job['id']})
        self.assertFalse(result['errors']);self.assertEqual(reads.call_count,1)
        self.assertEqual(self.store.load(job['id'])['status'],'completed')

    def test_extra_cached_or_empty_read_never_forges_a_current_version_stamp(self):
        request,target,prepare=self.extra_fixture()
        def reused(record,on_activity=None):return prepare(record,on_activity,computed=False)
        with patch('repair_cached_statistics.prepare_repair',side_effect=reused):result=self.execute({**request,'force':False})
        self.assertFalse(result['errors'])
        manifest=json.loads((self.root/'export.json').read_text('utf-8'))
        self.assertTrue(all('statistics' not in clip['recognition'].get('field_algorithms',{}) for clip in manifest['clips']))

        with patch('repair_cached_statistics.prepare_repair',return_value=None):result=self.execute({**request,'force':True})
        self.assertFalse(result['errors'])
        manifest=json.loads((self.root/'export.json').read_text('utf-8'))
        self.assertTrue(all('statistics' not in clip['recognition'].get('field_algorithms',{}) for clip in manifest['clips']))

    def test_completed_reads_resume_pending_name_finalization_without_ocr(self):
        with patch('hud_enrichment.recognize_video',return_value=self.fresh(['account'])),patch('hud_recovery.finalize_names',side_effect=TaskStopped()):
            with self.assertRaises(TaskStopped):self.execute()
        job=self.store.list_jobs()[0]
        self.assertEqual(self.store.summary(job['id'])['fields']['done'],2)
        self.assertNotEqual(job['status'],'completed')
        import hud_enrichment
        with patch('hud_enrichment.recognize_video') as read,patch('hud_enrichment.reconcile_manifest_names',wraps=hud_enrichment.reconcile_manifest_names) as finalize:
            self.execute({**self.request,'resume_job':job['id']})
        read.assert_not_called();self.assertEqual(len(finalize.call_args.kwargs['targets']),2)
        self.assertEqual(self.store.load(job['id'])['status'],'completed')

    def test_child_model_signature_mismatch_fails_before_read_or_stamp(self):
        from hud_job_store import media_identity
        rows=[{'id':clip_id(file),'file':str(file),'directory':str(self.root),'source_identity':media_identity(file),'fields':['account']} for file in self.files]
        job=self.store.create(rows,self.registry);before=(self.root/'export.json').read_bytes()
        mismatch={**self.registry,'account':descriptor('account',{'rule':'different-runtime-v2'})}
        with patch('hud_recovery.current_registry',return_value=mismatch),patch('hud_enrichment.recognize_video') as read:
            with self.assertRaisesRegex(ValueError,'实际模型'):
                self.execute({**self.request,'checkpoint':{'root':str(self.store.root),'id':job['id'],'registry':self.registry}})
        read.assert_not_called();self.assertEqual((self.root/'export.json').read_bytes(),before)

    def test_extra_input_metadata_change_invalidates_done_fields_on_resume(self):
        request,target,prepare=self.extra_fixture()
        with patch('repair_cached_statistics.prepare_repair',side_effect=prepare):self.execute(request)
        job=self.store.list_jobs()[0]
        original=self.root/'statistics.json';report=json.loads(original.read_text('utf-8'));report['changed_input']=True;original.write_text(json.dumps(report),'utf-8')
        with patch('repair_cached_statistics.prepare_repair',return_value=None) as reads:
            self.execute({**request,'resume_job':job['id']})
        self.assertEqual(reads.call_count,2)
        self.assertTrue(all(row['reason']=='field-input-changed' for row in self.store.load(job['id'])['invalidated']))


if __name__=='__main__':unittest.main()
