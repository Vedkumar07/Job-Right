import base64, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import core,server
class ActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=core.DATA;core.DATA=Path(self.tmp.name);core.init();self.handler=object.__new__(server.Handler)
    def tearDown(self):core.DATA=self.old;self.tmp.cleanup()
    def act(self,path,value):return self.handler.handle_action(path,value)
    def test_resume_profile_delete(self):
        text='Python engineer with SQL and 3 years experience building services.'
        file=base64.b64encode(text.encode()).decode()
        parsed=self.act('/api/resume',{'name':'cv.txt','data':file});self.assertEqual(parsed['text'],text)
        self.act('/api/profile',{'name':'Alex','resume':text,'years':3,'resume_file':parsed['resume_file']})
        with core.connection() as db:p=core.get_profile(db)
        self.assertEqual(p['priority'],['remote','india','worldwide']);self.assertEqual(p['resume_file']['data'],file)
        self.assertNotIn('resume_file',server.bootstrap()['profile'])
        self.act('/api/delete-profile',{})
        with core.connection() as db:self.assertEqual(core.get_profile(db),{})
    def test_profile_save_while_collector_commits(self):
        with core.connection() as db:
            for i in range(3):
                db.execute("INSERT INTO jobs(id,source_id,company,title,description,location,url,apply_url,remote,active) VALUES(?,1,'Example','Python Engineer','Python SQL','Remote India',?,?,1,1)",(str(i),f'https://example.com/{i}',f'https://example.com/{i}'))
        real_score=core.score_job
        committed=False
        def concurrent_score(job,profile):
            nonlocal committed
            if not committed:
                with core.connection() as other:
                    other.execute("UPDATE settings SET value='false' WHERE key='scheduler_enabled'")
                committed=True
            return real_score(job,profile)
        with patch('core.score_job',side_effect=concurrent_score):
            result=self.act('/api/profile',{'name':'Example','resume':'Python SQL engineer with several years building useful products.','roles':'engineer','years':5,'location':'India'})
        self.assertTrue(result['ok'])
        with core.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],3)
            self.assertEqual(core.get_profile(db)['name'],'Example')

    def test_notifications_do_not_restore_deleted_profile_matches(self):
        with core.connection() as db:
            db.execute("INSERT INTO profile VALUES(1,?)",(json.dumps({'name':'Example','resume':'Python engineer with SQL and experience building applications','skills':['python','sql'],'roles':'engineer','years':5,'remote':True}),))
            db.execute("INSERT INTO jobs(id,source_id,company,title,description,location,url,apply_url,remote,active) VALUES('one',1,'Example','Python Engineer','Python SQL','Remote India','https://example.com/1','https://example.com/1',1,1)")
        real_score=core.score_job
        def delete_during_matching(job,profile):
            with core.connection() as other:other.execute('DELETE FROM profile')
            return real_score(job,profile)
        with patch('core.score_job',side_effect=delete_during_matching):core.create_notifications()
        with core.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],0)

    def test_settings(self):
        self.act('/api/settings',{'scheduler_enabled':False,'threshold':72})
        with core.connection() as db:self.assertFalse(core.setting(db,'scheduler_enabled'));self.assertEqual(core.setting(db,'threshold'),72);self.assertEqual(core.setting(db,'interval_hours'),12)
    def test_source_csv_atomic(self):
        with core.connection() as db:before=db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]
        with self.assertRaises(core.Problem):self.act('/api/import-sources',{'csv':'company,kind,board,category\nA,lever,valid,Startup\nB,bad,invalid,Startup'})
        with core.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sources').fetchone()[0],before)
        self.act('/api/import-sources',{'csv':'company,kind,board,category\nA,lever,valid,Startup'})
        with core.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sources').fetchone()[0],before+1)
    def test_extension_history_idempotency(self):
        event={'id':'evt-1','url':'https://example.com/jobs/1','title':'Engineer','status':'needs_review','details':{'filled':['email'],'remaining':['Custom question']}}
        self.act('/api/extension-history',event);self.act('/api/extension-history',event)
        self.assertEqual(len(server.bootstrap()['autofill_history']),1)
        with self.assertRaises(core.Problem):self.act('/api/extension-history',dict(event,url='javascript:alert(1)'))
    def test_lock_prevents_overlap(self):
        core.COLLECTION_LOCK.acquire()
        try:
            with self.assertRaises(core.Problem):core.collect()
        finally:core.COLLECTION_LOCK.release()
    def test_smartrecruiters_description(self):
        source={'id':1,'company':'Example','kind':'smartrecruiters','board':'example','category':'MNC'}
        payload={'content':[{'id':'1','name':'Accountant','location':{'city':'Mumbai','country':'India'},'typeOfEmployment':{'label':'Full-time'}}],'totalFound':1}
        detail={'postingUrl':'https://jobs.smartrecruiters.com/example/1','jobAd':{'sections':{'jobDescription':{'text':'<p>Excel SAP accounting</p>'}}}}
        with patch('core.fetch',side_effect=[payload,detail]),patch('core.time.sleep'):jobs=core.smartrecruiters(source)
        self.assertEqual(jobs[0]['description'],'Excel SAP accounting')
    def test_robots_denied_skips(self):
        source={'id':1,'company':'Example','kind':'career_page','board':'https://example.com/careers','category':'MNC'}
        with patch('core.public_url'),patch('core.fetch',return_value='User-agent: *\nDisallow: /') as fetch:
            with self.assertRaises(core.Problem):core.career_page(source)
            self.assertEqual(fetch.call_count,1)
if __name__=='__main__':unittest.main()
