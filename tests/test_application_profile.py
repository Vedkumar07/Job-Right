import application_profile as facts,core
import test_automation
class ApplicationFactsTests(test_automation.AutopilotTests):
 def test_question_sync_and_resume(self):
  revision=self.queue()['revision']
  event={'id':'q-event','job_id':'job-1','revision':revision,'url':'https://example.com/1','status':'needs_review','details':{'questions':[{'label':'Employer name','section':'work','index':1}]}}
  self.handler.handle_action('/api/extension-history',event)
  self.handler.handle_action('/api/extension-history',event)
  self.assertEqual(self.queue()['jobs'],[])
  with core.connection() as db:
   rows=db.execute('SELECT * FROM application_questions').fetchall()
   self.assertEqual(len(rows),1);self.assertEqual(rows[0]['occurrences'],1)
   facts.answer_question(db,rows[0]['id'],'Example employer')
   p=core.get_profile(db)
   self.assertEqual(p['answers'][0]['section'],'work');self.assertEqual(p['answers'][0]['index'],1)
   self.assertEqual(p['resume'],self.profile['resume'])
  self.assertNotEqual(self.queue()['revision'],revision)
  self.assertEqual(len(self.queue()['jobs']),1)
 def test_structured_profile_validation(self):
  p=facts.validate({'work_history':[{'company':'Example','current':True}],'skill_years':{'Python':2.5},'authorized_to_work':'yes'}, {})
  self.assertEqual(facts.validate({},p),p)
  self.assertEqual(p['skill_years'],{'python':2.5})
  with self.assertRaises(core.Problem):facts.validate({'authorized_to_work':'probably'},p)
  with self.assertRaises(core.Problem):facts.validate({'skill_years':{'Python':100}},p)
 def test_resume_extraction_does_not_infer_eligibility(self):
  extracted=facts.suggested_facts('Engineer in India\nemail@example.com https://github.com/example')
  self.assertEqual(extracted['email'],'email@example.com')
  self.assertNotIn('authorized_to_work',extracted)
