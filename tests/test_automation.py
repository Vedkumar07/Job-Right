import json,tempfile,unittest
from pathlib import Path
import automation,core,server
class AutopilotTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=core.DATA;core.DATA=Path(self.tmp.name);core.init();self.handler=object.__new__(server.Handler)
  with core.connection() as db:
   self.profile={'name':'Example','email':'example@example.com','resume':'Python SQL engineer with experience building applications.','skills':['python','sql'],'roles':'engineer','location':'India','years':5,'remote':True}
   db.execute('INSERT INTO profile VALUES(1,?)',(json.dumps(self.profile),));db.execute("INSERT INTO jobs(id,source_id,company,title,description,location,url,apply_url,remote,active) VALUES('job-1',1,'Example','Python Engineer','Python SQL','Remote India','https://example.com/1','https://example.com/1',1,1)")
 def tearDown(self):core.DATA=self.old;self.tmp.cleanup()
 def queue(self):
  with core.connection() as db:return automation.queue(db,server.ranked_jobs(db))
 def test_profile_answers_are_validated_and_preserved(self):
  value=dict(self.profile,answers=[{'question':'Do you need sponsorship?','answer':'No'}],current_city='Mumbai')
  self.handler.handle_action('/api/profile',value)
  with core.connection() as db:profile=core.get_profile(db)
  self.assertEqual(profile['answers'],value['answers']);self.assertEqual(profile['current_city'],'Mumbai')
  with self.assertRaises(core.Problem):automation.profile_extras({'answers':[{'question':'Work authorization?','answer':'Yes'},{'question':'Work authorization','answer':'No'}]},profile)
 def test_duplicate_answer_rows_with_same_answer_are_collapsed(self):
  result=automation.profile_extras({'answers':[{'question':'Fall 2026','answer':'Available'},{'question':'Fall 2026','answer':'Available'}]}, {})
  self.assertEqual(result['answers'],[{'question':'Fall 2026','answer':'Available'}])
  with self.assertRaisesRegex(core.Problem,'Conflicting saved answers'):
   automation.profile_extras({'answers':[{'question':'Fall 2026','answer':'Available'},{'question':'Fall 2026','answer':'Not available'}]}, {})
 def test_reservation_prevents_duplicate_submission_across_revisions(self):
  q=self.queue();self.assertEqual(len(q['jobs']),1)
  with core.connection() as db:self.assertTrue(automation.reserve(db,'job-1',q['revision'])['ok'])
  with core.connection() as db:self.assertFalse(automation.reserve(db,'job-1',q['revision'])['ok'])
  self.assertEqual(self.queue()['jobs'],[])
  with core.connection() as db:
   p=core.get_profile(db);p['answers']=[{'question':'Example','answer':'Yes'}];db.execute('UPDATE profile SET data=?',(json.dumps(p),))
  self.assertEqual(self.queue()['jobs'],[])
 def test_stale_profile_and_paused_policy_cannot_submit(self):
  with core.connection() as db:self.assertFalse(automation.reserve(db,'job-1','old-revision')['ok'])
  q=self.queue()
  with core.connection() as db:db.execute("INSERT INTO settings VALUES('auto_submit','false')")
  with core.connection() as db:self.assertFalse(automation.reserve(db,'job-1',q['revision'])['ok'])
 def test_dismissed_job_cannot_be_reserved(self):
  q=self.queue()
  with core.connection() as db:server.record_application(db,'job-1','dismissed')
  with core.connection() as db:
   result=automation.reserve(db,'job-1',q['revision'])
   self.assertFalse(result['ok'])
   self.assertIn('already recorded',result['error'])
 def test_blocked_attempt_retries_only_after_answers_change(self):
  q=self.queue()
  self.handler.handle_action('/api/extension-history',{'id':'event-1','job_id':'job-1','revision':q['revision'],'url':'https://example.com/1','title':'Example','status':'needs_review','details':{'remaining':['Custom question']}})
  self.assertEqual(self.queue()['jobs'],[])
  with core.connection() as db:
   p=core.get_profile(db);p['answers']=[{'question':'Custom question','answer':'My saved answer'}];db.execute('UPDATE profile SET data=?',(json.dumps(p),))
  self.assertEqual(len(self.queue()['jobs']),1)
 def test_confirmed_submission_does_not_regress_to_blocked(self):
  event={'job_id':'job-1','revision':self.queue()['revision'],'url':'https://example.com/1','title':'Example','details':{}}
  self.handler.handle_action('/api/extension-history',dict(event,id='one',status='submitted'))
  self.handler.handle_action('/api/extension-history',dict(event,id='two',status='needs_review'))
  with core.connection() as db:self.assertEqual(db.execute('SELECT status FROM applications').fetchone()[0],'submitted')
  self.assertEqual(self.queue()['jobs'],[])
 def test_disabled_autopilot_has_no_queue(self):
  with core.connection() as db:db.execute("INSERT INTO settings VALUES('autopilot_enabled','false')")
  self.assertEqual(self.queue()['jobs'],[])
if __name__=='__main__':unittest.main()
