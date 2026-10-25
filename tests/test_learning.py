import json
import unittest
import core
import automation
import application_profile as facts
from test_automation import AutopilotTests

class LearningTests(AutopilotTests):
 def test_trusted_user_answers_learned_once_and_secrets_excluded(self):
  event={'job_id':'job-1','details':{'answers':[
   {'question':'What is your full name?','answer':'Example Person','source':'user-entered'},
   {'question':'Why our company?','answer':'My own saved reason','source':'user-entered','lane_id':'backend'},
   {'question':'Password','answer':'never store','source':'user-entered'},
   {'question':'Random inference','answer':'guessed','source':'inferred'}]}}
  with core.connection() as db:
   self.assertEqual(facts.learn_answers(db,event),1)
   self.assertEqual(facts.learn_answers(db,event),0)
   p=core.get_profile(db)
  self.assertEqual(len(p['answers']),1)
  why=next(a for a in p['answers'] if a['question']=='Why our company?')
  self.assertEqual(why['job_id'],'job-1');self.assertEqual(why['company'],'Example');self.assertEqual(why['lane_id'],'backend')
  self.assertFalse(any('name' in a['question'].lower() for a in p['answers']))
 def test_learning_requires_managed_known_job_and_honors_opt_out(self):
  event={'job_id':'not-a-job','details':{'answers':[{'question':'Full name','answer':'Example','source':'user-entered'}]}}
  with core.connection() as db:
   self.assertEqual(facts.learn_answers(db,event),0)
   p=core.get_profile(db);p['learn_answers']=False;db.execute('UPDATE profile SET data=?',(json.dumps(p),))
   self.assertEqual(facts.learn_answers(db,dict(event,job_id='job-1')),0)
 def test_queue_uses_its_matched_resume_not_global_resume(self):
  p=dict(self.profile,lanes=[{'id':'backend','name':'Backend lane','roles':'backend engineer','resume':'Python SQL backend engineer','skills':['python','sql'],'years':5,'enabled':True}, {'id':'analyst','name':'Analyst lane','roles':'data analyst','resume':'Excel Tableau analyst','skills':['excel','tableau'],'years':5,'enabled':True}])
  with core.connection() as db:
   db.execute('UPDATE profile SET data=?',(json.dumps(p),))
   db.execute("UPDATE jobs SET title='Backend Engineer'")
  q=self.queue();self.assertEqual(len(q['jobs']),1)
  self.assertEqual(q['jobs'][0]['lane_id'],'backend')
  self.assertNotIn('profile',q['jobs'][0])
  with core.connection() as db:config=automation.configuration(db,'token',8877)
  selected=next(p for p in config['profiles'] if p['lane_id']=='backend')
  self.assertEqual(selected['resume'],'Python SQL backend engineer')
  self.assertEqual(selected['name'],'Example')
 def test_disabled_lanes_have_no_queue(self):
  with core.connection() as db:
   p=core.get_profile(db);p['lanes']=[{'id':'paused','name':'Paused','resume':p['resume'],'enabled':False}];db.execute('UPDATE profile SET data=?',(json.dumps(p),))
  self.assertEqual(self.queue()['jobs'],[])
 def test_saved_answer_scope_is_preserved_by_validation(self):
  p=automation.profile_extras({'answers':[{'question':'Why this role?','answer':'My reason','job_id':'job-1','lane_id':'backend','company':'Example','source':'user-entered'}]}, {})
  self.assertEqual(p['answers'][0]['job_id'],'job-1');self.assertEqual(p['answers'][0]['lane_id'],'backend')
if __name__=='__main__':unittest.main()
