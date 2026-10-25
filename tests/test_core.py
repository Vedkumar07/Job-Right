import base64, io, json, os, sqlite3, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import core
class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=core.DATA;core.DATA=Path(self.tmp.name);core.init();self.source={'id':1,'company':'Example','kind':'greenhouse','board':'example','category':'Startup'}
    def tearDown(self):core.DATA=self.old;self.tmp.cleanup()
    def test_skill_boundaries_aliases(self):
        found=core.terms('React.js, NodeJS, PostgreSQL, C++, JavaScript, accounting and SalesForce')
        self.assertTrue({'react','node.js','postgresql','c++','javascript','accounting','salesforce'}<=found);self.assertNotIn('java',found);self.assertNotIn('go',core.terms('ongoing'))
    def test_skill_scan_keeps_overlapping_phrases(self):
        self.assertEqual(core.terms('Penetration testing; user experience; user interface.'),{'penetration testing','testing','ux','ui'})
        self.assertEqual(core.terms(', '.join(core.SKILLS)),set(core.SKILLS))

    def test_resume_text_docx_and_limits(self):
        text='A qualified candidate with Python, SQL and communication skills.'
        self.assertEqual(core.parse_resume(text.encode(),'cv.txt'),text)
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('word/document.xml','<w:p>'+text+'</w:p>')
        self.assertIn('Python',core.parse_resume(b.getvalue(),'cv.docx'))
        with self.assertRaises(core.Problem):core.parse_resume(b'a'*(5*1024*1024+1),'cv.txt')
        with self.assertRaises(core.Problem):core.parse_resume(b'not pdf','cv.pdf')
        with self.assertRaises(core.Problem):core.parse_resume(b'abc','cv.exe')
    def test_match_and_experience_warning(self):
        job={'title':'Python Engineer','description':'Python, SQL, AWS. Requires 5 years experience.','location':'Remote India','remote':1}
        p={'resume':'Python SQL engineer with 2 years experience and systems knowledge.','roles':'Engineer','skills':['python','sql'],'years':2,'remote':True,'location':'India'}
        result=core.score_job(job,p);self.assertEqual(result['matched'],['python','sql']);self.assertIn('aws',result['missing']);self.assertTrue(any('5+' in x for x in result['warnings']));self.assertIsNone(core.score_job(job,{})['score']);self.assertLessEqual(result['score'],100)
    def test_greenhouse_normalisation(self):
        payload={'jobs':[{'title':'Engineer','location':{'name':'Remote'},'content':'<p>Python &amp; SQL</p>','absolute_url':'https://example.com/jobs/1?utm_source=test','updated_at':'2026-10-18'}]}
        with patch('core.fetch',return_value=payload):rows=core.greenhouse(self.source)
        self.assertEqual(rows[0]['url'],'https://example.com/jobs/1');self.assertEqual(rows[0]['description'],'Python & SQL');self.assertEqual(rows[0]['remote'],1);self.assertEqual(core.clean('&amp;lt;p&amp;gt;Python&amp;lt;/p&amp;gt;'),'Python')
    def test_lever_pagination(self):
        entry={'text':'Data Analyst','categories':{'location':'India'},'descriptionPlain':'Excel and SQL','hostedUrl':'https://jobs.lever.co/example/1'}
        with patch('core.fetch',side_effect=[[entry]*100,[]]) as f:rows=core.lever(dict(self.source,kind='lever'))
        self.assertEqual(len(rows),100);self.assertIn('skip=100',f.call_args.args[0])
    def test_ashby(self):
        with patch('core.fetch',return_value={'jobs':[{'title':'Designer','location':'Remote','descriptionPlain':'Figma','jobUrl':'https://jobs.ashbyhq.com/example/1','isListed':True},{'title':'Secret','isListed':False}]}):rows=core.ashby(dict(self.source,kind='ashby'))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['title'],'Designer')
    def test_jsonld_graph_and_expired(self):
        obj={'@graph':[{'@type':'JobPosting','title':'Analyst','description':'Financial analysis','url':'/jobs/1','jobLocation':{'address':{'addressLocality':'Mumbai','addressCountry':'India'}},'validThrough':'2099-01-01'},{'@type':'JobPosting','title':'Old role','validThrough':'2000-01-01'}]}
        body='<script type="application/ld+json">'+json.dumps(obj)+'</script>'
        rows,_=core.jsonld_jobs(self.source,body,'https://example.com/careers');self.assertEqual(len(rows),1);self.assertEqual(rows[0]['location'],'Mumbai, India')
    def test_unsafe_links_and_tracking(self):
        self.assertFalse(core.safe_link('javascript:alert(1)'));self.assertIsNone(core.normalise(self.source,'Job','','','http://example.com'))
        self.assertEqual(core.canonical_url('https://EXAMPLE.com/jobs/?utm_medium=x&id=4#top'),'https://example.com/jobs?id=4')
        with patch('core.socket.getaddrinfo',return_value=[(None,None,None,None,('127.0.0.1',443))]):
            with self.assertRaises(core.Problem):core.public_url('https://local.example/jobs')
    def test_source_validation_and_discovery(self):
        with self.assertRaises(core.Problem):core.validate_source({'company':'A','kind':'lever','board':'https://x','category':'Startup'})
        self.assertEqual(core.discover_ats(self.source,['https://jobs.lever.co/newcompany/1'],'https://example.com'),1)
        with core.connection() as db:self.assertEqual(db.execute("SELECT count(*) FROM sources WHERE board='newcompany'").fetchone()[0],1)
    def test_dedupe_close_and_preserve_on_failure(self):
        with core.connection() as db:db.execute('DELETE FROM sources');db.execute("INSERT INTO sources(id,company,kind,board,category) VALUES(1,'Example','greenhouse','example','Startup')")
        job=core.normalise(self.source,'Python engineer','Remote','Python SQL','https://example.com/1')
        with patch.dict(core.COLLECTORS,{'greenhouse':lambda s:[job]}):
            self.assertEqual(core.collect(True)['new_jobs'],1);self.assertEqual(core.collect(True)['new_jobs'],0)
        with patch.dict(core.COLLECTORS,{'greenhouse':lambda s:(_ for _ in ()).throw(core.Problem('offline'))}):core.collect(True)
        with core.connection() as db:self.assertEqual(db.execute('SELECT active FROM jobs').fetchone()[0],1);self.assertEqual(db.execute('SELECT failures FROM sources').fetchone()[0],1)
        with patch.dict(core.COLLECTORS,{'greenhouse':lambda s:[]}):core.collect(True)
        with core.connection() as db:self.assertEqual(db.execute('SELECT active FROM jobs').fetchone()[0],0)
    def test_notifications_are_deduplicated(self):
        with core.connection() as db:
            p={'resume':'Python SQL engineer with useful development experience','skills':['python','sql'],'roles':'engineer','years':5,'location':'India','remote':True};db.execute('INSERT INTO profile VALUES(1,?)',(json.dumps(p),));db.execute("INSERT INTO jobs(id,source_id,company,title,description,location,url,apply_url,remote,active) VALUES('one',1,'Example','Python Engineer','Python SQL','Remote India','https://example.com/1','https://example.com/1',1,1)")
        core.create_notifications();core.create_notifications()
        with core.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)
    def test_priority_order(self):
        import server
        with core.connection() as db:
            for i,(location,remote) in enumerate([('London',0),('Bengaluru, India',0),('Remote - India',1),('Remote - USA',1),('Remote',1)]):db.execute('INSERT INTO jobs(id,source_id,company,title,description,location,remote,active) VALUES(?,1,?,?,?,?,?,1)',(str(i),'Example','Engineer','Python',location,remote))
            rows=server.ranked_jobs(db)
        self.assertEqual([r['priority'] for r in rows],[0,0,1,2,2])
        self.assertEqual({r['location'] for r in rows[:2]},{'Remote - India','Remote'})
    def test_geography_priority_precedes_relevance(self):
        import server
        with core.connection() as db:
            for i,(location,remote) in enumerate([('London',0),('Bengaluru, India',0),('Remote - India',1)]):db.execute('INSERT INTO jobs(id,source_id,company,title,description,location,remote,active) VALUES(?,1,?,?,?,?,?,1)',('geo'+str(i),'Example','Engineer','Python',location,remote))
            def score(row,profile):
                return {'relevant':row['id']=='geo0','score':100 if row['id']=='geo0' else 20}
            with patch('server.core.score_job',side_effect=score):rows=server.ranked_jobs(db)
        self.assertEqual([r['priority'] for r in rows],[0,1,2])
        self.assertEqual(rows[-1]['id'],'geo0','worldwide relevance must not outrank the preferred India/remote groups')
if __name__=='__main__':unittest.main()
