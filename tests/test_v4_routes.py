import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import core
import server

class V4RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=core.DATA;core.DATA=Path(self.tmp.name);core.init()
        self.handler=object.__new__(server.Handler)
        self.resume='Backend engineer with Python Django PostgreSQL Redis and REST API experience. '+('Projects and development. '*3)
    def tearDown(self):core.DATA=self.old;self.tmp.cleanup()
    def action(self,path,value):return self.handler.handle_action(path,value)
    def test_lane_only_profile_shared_identity_and_file_preservation(self):
        attachment={'name':'backend.txt','data':base64.b64encode(self.resume.encode()).decode(),'type':'text/plain'}
        lane=self.action('/api/lane',{'name':'Backend','roles':'Backend engineer','resume':self.resume,'years':0,'resume_file':attachment})
        self.action('/api/profile',{'name':'Actual Applicant','email':'candidate@example.com','resume':'','years':0})
        boot=server.bootstrap();self.assertEqual(boot['backend_version'],4)
        self.assertEqual(boot['profile']['name'],'Actual Applicant')
        self.assertEqual(boot['lanes'][0]['id'],lane['id']);self.assertNotIn('resume_file',boot['lanes'][0])
        self.action('/api/lane',{'id':lane['id'],'name':'Backend revised','roles':'Backend','resume':self.resume,'enabled':True})
        with core.connection() as db:self.assertEqual(core.get_profile(db)['lanes'][0]['resume_file'],attachment)
        self.action('/api/delete-lane',{'id':lane['id']})
        with core.connection() as db:self.assertEqual(core.lane_profiles(core.get_profile(db)),[])
    def test_profile_save_does_not_overwrite_concurrent_learned_answer(self):
        self.action('/api/profile',{'name':'Before','email':'before@example.com','phone':'123','location':'India','roles':'Backend','resume':self.resume})
        original=server.automation.profile_extras
        def write_answer_then_validate(value,old):
            with core.connection() as db:
                p=core.get_profile(db);p['answers']=[{'question':'Notice period','answer':'30 days','source':'user-entered'}]
                db.execute('UPDATE profile SET data=?',(json.dumps(p),))
            return original(value,old)
        with patch.object(server.automation,'profile_extras',side_effect=write_answer_then_validate):
            with self.assertRaises(core.Problem):self.action('/api/profile',{'name':'After','email':'after@example.com','phone':'456','location':'India','roles':'Backend','resume':self.resume})
        with core.connection() as db:
            profile=core.get_profile(db)
            self.assertEqual(profile['name'],'Before')
            self.assertEqual(profile['answers'][0]['answer'],'30 days')
    def test_helper_heartbeat_session_expiry_and_no_token_in_bootstrap(self):
        self.action('/api/helper-heartbeat',{'version':'4','active_tabs':1})
        boot=server.bootstrap();self.assertTrue(boot['automation_state']['helper_connected'])
        self.assertNotIn(server.TOKEN,json.dumps(boot))
        with patch.object(server,'TOKEN','after-restart'):self.assertFalse(server.bootstrap()['automation_state']['helper_connected'])
        with patch.object(server.time,'time',return_value=10**12):self.assertFalse(server.bootstrap()['automation_state']['helper_connected'])
    def test_bootstrap_bounds_dashboard_payload_size(self):
        with core.connection() as db:
            for i in range(1001):db.execute('INSERT INTO jobs(id,source_id,company,title,description,location,url,apply_url,active) VALUES(?,1,?,?,?,?,?,?,1)',(f'job-{i}','Example','Engineer','x'*9000,'Remote India',f'https://example.com/{i}',f'https://example.com/{i}'))
        boot=server.bootstrap()
        self.assertEqual(boot['job_total'],1001);self.assertTrue(boot['jobs_truncated']);self.assertEqual(len(boot['jobs']),1000)
        self.assertLessEqual(max(len(row['description']) for row in boot['jobs']),4000)
    def test_run_does_not_enable_submission_when_fill_only_selected(self):
        self.action('/api/lane',{'name':'Backend','roles':'Backend','resume':self.resume})
        self.action('/api/settings',{'auto_submit':False,'autopilot_enabled':False})
        out=self.action('/api/automation/run',{})
        self.assertTrue(out['ok'])
        with core.connection() as db:
            self.assertTrue(core.setting(db,'autopilot_enabled'));self.assertFalse(core.setting(db,'auto_submit'))
    def test_browser_jobs_atomic_dedupe_known_hosts_only(self):
        job={'title':'Junior Backend Engineer','company':'Example Startup','location':'Remote India','description':self.resume,'url':'https://www.naukri.com/job-listings-backend-engineer-123?session=secret&campaign=x#apply'}
        out=self.action('/api/import-browser-jobs',{'platform':'naukri','jobs':[job]});self.assertEqual(out['imported'],1)
        self.assertEqual(self.action('/api/import-browser-jobs',{'platform':'naukri','jobs':[job]})['imported'],0)
        with self.assertRaises(core.Problem):self.action('/api/import-browser-jobs',{'platform':'naukri','jobs':[job,{**job,'url':'https://naukri.com.evil.example/job-listings-hijack'}]})
        with core.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
            self.assertNotIn('secret',db.execute('SELECT url FROM jobs').fetchone()[0])
            self.assertEqual(db.execute("SELECT enabled FROM sources WHERE kind='browser'").fetchone()[0],0)
    def test_browser_yc_listing_and_port_rejection(self):
        job={'title':'Software Engineer','url':'https://www.workatastartup.com/jobs/123'}
        self.assertEqual(self.action('/api/import-browser-jobs',{'platform':'yc','jobs':[job]})['imported'],1)
        with self.assertRaises(core.Problem):self.action('/api/import-browser-jobs',{'platform':'yc','jobs':[{**job,'url':'https://www.workatastartup.com:9999/jobs/123'}]})

if __name__=='__main__':unittest.main()
