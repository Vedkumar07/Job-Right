import base64
import unittest

import core


class LaneMatchingTests(unittest.TestCase):
    def profile(self):
        return {'name':'Example','email':'example@example.com','years':0,'remote':True,'location':'India','resume':'Python SQL engineer with experience building web applications.','roles':'DevOps, SDE, Backend'}

    def job(self,title,description='Python SQL Docker AWS REST API services.',**kwargs):
        return {'title':title,'description':description,'location':'Remote India','remote':True,**kwargs}

    def test_role_alternatives_sde_alias_and_irrelevant_soft_skill_overlap(self):
        p=self.profile();p['skills']=sorted(core.terms(p['resume']))
        relevant=core.score_job(self.job('Software Engineer, Backend','Python SQL development of web services.'),p)
        unrelated=core.score_job(self.job('Account Executive','Communication, leadership, education, research, Python dashboards and SQL reports.'),p)
        self.assertTrue(relevant['relevant']);self.assertGreaterEqual(relevant['score'],55)
        self.assertFalse(unrelated['relevant']);self.assertLess(unrelated['score'],40)

    def test_senior_title_and_mandatory_experience_gate(self):
        p=self.profile()
        self.assertFalse(core.score_job(self.job('Senior Backend Engineer'),p)['relevant'])
        self.assertFalse(core.score_job(self.job('Backend Engineer','Python SQL. Minimum 3 years of experience developing services.'),p)['relevant'])
        junior=core.score_job(self.job('Backend Engineer','Python SQL. 3 years experience preferred. Graduate candidates welcome.'),p)
        self.assertTrue(junior['relevant'])

    def test_company_age_not_candidate_experience(self):
        match=core.score_job(self.job('Backend Engineer','Python SQL. Founded 20 years ago. Graduates welcome.'),self.profile())
        self.assertEqual(match['required_years'],0);self.assertTrue(match['relevant'])

    def test_experience_range_uses_minimum(self):
        p={**self.profile(),'years':1}
        match=core.score_job(self.job('Backend Engineer','Python SQL. 1-3 years of experience building services.'),p)
        self.assertEqual(match['required_years'],1);self.assertTrue(match['relevant'])

    def test_best_lane_selects_own_resume_attachment_and_shared_facts(self):
        p=self.profile()
        p.update(core.validate_lanes({'lanes':[
            {'id':'backend','name':'Backend resume','roles':'Backend Engineer','resume':'Python SQL FastAPI engineer building robust backend application services.','resume_file':{'name':'backend.txt','type':'text/plain','data':base64.b64encode(b'backend original file').decode()}},
            {'id':'design','name':'Design resume','roles':'UI UX Designer','resume':'Product designer with Figma, Sketch, UI, UX and user research experience.','resume_file':{'name':'design.txt','type':'text/plain','data':base64.b64encode(b'design original file').decode()}},
        ]},p))
        job=self.job('UX Designer','Figma UI UX user research product design.')
        match=core.score_job(job,p)
        self.assertEqual(match['lane_id'],'design');self.assertEqual(len(match['lane_matches']),2)
        self.assertTrue(match['relevant']);self.assertFalse(match['lane_matches'][0]['relevant'])
        selected=core.profile_for_job(p,job)
        self.assertEqual(selected['name'],p['name']);self.assertEqual(selected['lane_name'],'Design resume');self.assertEqual(selected['email'],p['email']);self.assertEqual(selected['resume_file']['name'],'design.txt')
        self.assertNotIn('lanes',selected);self.assertNotIn('python',selected['skills'])

    def test_disable_or_remove_lanes_never_reactivates_legacy_resume(self):
        p=self.profile()
        p['lanes']=[{'id':'off','name':'Disabled','resume':p['resume'],'roles':p['roles'],'enabled':False}]
        self.assertEqual(core.lane_profiles(p),[]);self.assertIsNone(core.score_job(self.job('Backend Engineer'),p)['score'])
        p['lanes']=[]
        self.assertEqual(core.lane_profiles(p),[]);self.assertEqual(core.profile_for_job(p,self.job('Backend Engineer')),{})

    def test_legacy_profile_preserved_and_active_filter_not_global_selector(self):
        p=self.profile();self.assertEqual(core.profile_for_job(p,self.job('Backend Engineer'))['lane_id'],'legacy')
        p.update(core.validate_lanes({'lanes':[{'id':'b','name':'B','roles':'Backend','resume':p['resume']},{'id':'d','name':'D','roles':'Designer','resume':'Figma Sketch UI UX product designer conducting user research studies.'}],'active_lane_id':'d'},p))
        self.assertEqual(core.score_job(self.job('Backend Engineer'),p)['lane_id'],'b')

    def test_lane_validation_recalculates_skills_and_preserves_unchanged_file(self):
        p=self.profile();value={'lanes':[{'id':'one','name':'One','roles':'Backend','resume':p['resume'],'skills':['fictional skill'],'resume_file':{'name':'../cv.txt','data':base64.b64encode(b'original').decode()}}]}
        old={**p,**core.validate_lanes(value,p)}
        self.assertEqual(old['lanes'][0]['resume_filename'],'cv.txt');self.assertNotIn('fictional skill',old['lanes'][0]['skills'])
        value['lanes'][0].pop('resume_file')
        self.assertIn('resume_file',core.validate_lanes(value,old)['lanes'][0])
        self.assertEqual(core.validate_lanes({},old)['lanes'],old['lanes'])
        value['lanes'][0]['resume']+=' Now using Docker.'
        self.assertNotIn('resume_file',core.validate_lanes(value,old)['lanes'][0])

    def test_validate_duplicate_ids_and_invalid_facts(self):
        lane={'id':'same','resume':self.profile()['resume']}
        with self.assertRaises(core.Problem):core.validate_lanes({'lanes':[lane,lane]},self.profile())
        with self.assertRaises(core.Problem):core.validate_lanes({'lanes':[{**lane,'years':'NaN'}]},self.profile())
        with self.assertRaises(core.Problem):core.validate_lanes({'lanes':[{**lane,'enabled':'false'}]},self.profile())
        with self.assertRaises(core.Problem):core.validate_lanes({'lanes':[{**lane,'resume_file':{'data':'bad base64'}}]},self.profile())

    def test_backend_specialization_not_frontend_only(self):
        p={**self.profile(),'roles':'Backend Engineer'}
        self.assertFalse(core.score_job(self.job('Frontend Engineer','React JavaScript HTML CSS Python SQL'),p)['relevant'])
        p['roles']='SDE, Backend'
        self.assertTrue(core.score_job(self.job('Frontend Engineer','Python SQL React'),p)['relevant'])


if __name__=='__main__':unittest.main()
