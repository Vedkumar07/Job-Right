#!/usr/bin/env python3
"""Single-user localhost server. Run continuously to collect twice daily."""
from __future__ import annotations
import argparse, base64, csv, hmac, io, json, mimetypes, os, secrets, signal, sqlite3, threading, time, urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import core
import automation
import application_profile
import platform_ingest
TOKEN=secrets.token_urlsafe(32)
STOP=threading.Event()
PORT=8877
MAX_BODY=8*1024*1024
EXTENSION_WRITES=('/api/extension-history','/api/reserve-submit','/api/helper-heartbeat','/api/extension-heartbeat','/api/import-browser-jobs')

def scheduler():
    while not STOP.is_set():
        try:
            with core.connection() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES('heartbeat',?)",(json.dumps(core.now()),))
                enabled=core.setting(db,'scheduler_enabled',True)
                due=db.execute('SELECT COUNT(*) FROM sources WHERE enabled=1 AND next_due<=?',(time.time(),)).fetchone()[0]
            if enabled and due:core.collect()
        except Exception as e:print('Collector:',str(e),flush=True)
        STOP.wait(30)

def ranked_jobs(db):
    profile=core.get_profile(db);result=[]
    for r in db.execute('''SELECT jobs.*,applications.status AS application_status,sources.last_success AS source_verified FROM jobs LEFT JOIN applications ON jobs.id=applications.job_id LEFT JOIN sources ON sources.id=jobs.source_id WHERE active=1'''):
        row=dict(r);row['match']=core.score_job(row,profile)
        text=row['location'].lower()
        india=any(x in text for x in ('india','bengaluru','bangalore','hyderabad','mumbai','pune','chennai','delhi','noida','gurugram','gurgaon','kolkata','ahmedabad'))
        global_remote=any(x in text for x in ('worldwide','global','anywhere','work from anywhere'))
        scope=text
        for marker in ('remote','hybrid','distributed','work from home','wfh','anywhere','worldwide','global'):
            scope=scope.replace(marker,' ')
        scope=' '.join(scope.replace('(',' ').replace(')',' ').replace(';',' ').replace(',',' ').replace('-',' ').split())
        # Many feeds mark a role remote because it allows WFH within a country.
        # A named foreign location is not an India-friendly remote role.
        if row['remote'] and (india or global_remote or not scope):row['priority']=0
        elif india:row['priority']=1
        else:row['priority']=2
        result.append(row)
    # Geographic preference is intentional: remote, then India, then worldwide.
    # Rank by role relevance inside each preferred geography group.
    result.sort(key=lambda j:(j['priority'],not j['match'].get('relevant',True),-(j['match']['score'] or 0),j['title'].lower()))
    return result

def record_application(db,job_id,status):
    if status not in ('saved','opened','awaiting_captcha','in_progress','autofilled','needs_review','submission_attempted','submitted','failed','applied','dismissed'):raise core.Problem('Unsupported application status.')
    if not db.execute('SELECT id FROM jobs WHERE id=?',(job_id,)).fetchone():raise core.Problem('Job was not found.')
    current=db.execute('SELECT status FROM applications WHERE job_id=?',(job_id,)).fetchone()
    if current and (current[0] in ('submitted','applied') and status not in ('submitted','applied') or current[0]=='submission_attempted' and status not in ('submitted','submission_attempted')):return
    db.execute('INSERT INTO applications(job_id,status,updated) VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,updated=excluded.updated',(job_id,status,core.now()))

def automation_state(db,jobs=None):
    helper=core.setting(db,'helper_status',{})
    connected=isinstance(helper,dict) and helper.get('session')==TOKEN and 0<=time.time()-float(helper.get('server_seen',0))<150
    ranked=jobs if jobs is not None else ranked_jobs(db)
    queue=automation.queue(db,ranked)
    statuses={row[0]:row[1] for row in db.execute('SELECT status,COUNT(*) FROM applications GROUP BY status')}
    return {'enabled':core.setting(db,'autopilot_enabled',True),'auto_submit':core.setting(db,'auto_submit',True),
            'helper_connected':connected,'last_seen':helper.get('server_seen') if connected else None,
            'queued':len(queue.get('jobs',[])),'blocked':sum(statuses.get(k,0) for k in ('needs_review','awaiting_captcha','failed')),
            'submitted':statuses.get('submitted',0)+statuses.get('applied',0),
            'unanswered':db.execute('SELECT COUNT(*) FROM application_questions WHERE answered=0').fetchone()[0],
            'capabilities':['public ATS collection','resume-specific matching','native application form automation','YC/Naukri visible job capture','explicit answer reuse'],
            'helper_error':str(helper.get('error',''))[:300] if isinstance(helper,dict) else '',
            'run_requested_at':core.setting(db,'run_requested_at')}

def bootstrap():
    with core.connection() as db:
        jobs=ranked_jobs(db);profile=core.get_profile(db)
        total_jobs=db.execute('SELECT COUNT(*) FROM jobs WHERE active=1').fetchone()[0]
        # Keep dashboard payload and browser memory bounded. The full ranked
        # set remains available to the server-side autopilot queue.
        visible_jobs=[]
        for row in jobs[:1000]:
            item=dict(row);item['description']=item['description'][:4000]
            visible_jobs.append(item)
        safe_profile={k:v for k,v in profile.items() if k not in ('resume_file','lanes')}
        safe_profile['lanes']=[dict({k:v for k,v in lane.items() if k!='resume_file'},resume_filename=lane.get('resume_file',{}).get('name','')) for lane in profile.get('lanes',[])]
        history=[dict(x) for x in db.execute('SELECT applications.*,jobs.company,jobs.title,jobs.apply_url FROM applications LEFT JOIN jobs ON applications.job_id=jobs.id ORDER BY updated DESC')]
        auto=[dict(x) for x in db.execute('SELECT * FROM autofill_history ORDER BY created DESC LIMIT 500')]
        return {'backend_version':4,'lanes':safe_profile['lanes'],'automation_state':automation_state(db,jobs),'job_total':total_jobs,'jobs_truncated':total_jobs>len(visible_jobs),'questions':[dict(x) for x in db.execute('SELECT * FROM application_questions ORDER BY answered,last_seen DESC')],'jobs':visible_jobs,'profile':safe_profile,'sources':[dict(x) for x in db.execute('SELECT * FROM sources ORDER BY company')], 'notifications':[dict(x) for x in db.execute('SELECT * FROM notifications ORDER BY created DESC LIMIT 200')],'history':history,'autofill_history':auto,'runs':[dict(x) for x in db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 20')],'settings':{'scheduler_enabled':core.setting(db,'scheduler_enabled',True),'threshold':core.setting(db,'threshold',55),'interval_hours':core.setting(db,'interval_hours',12),'auto_submit':core.setting(db,'auto_submit',True),'autopilot_enabled':core.setting(db,'autopilot_enabled',True),'heartbeat':core.setting(db,'heartbeat')},'collecting':core.COLLECTION_LOCK.locked(),'mode':'live','coverage_notice':'Only configured sources are checked. The internet-wide company set is not enumerable; registry entries are candidates until a successful fetch. Career-page crawls are bounded to 30 pages.'}

class Handler(BaseHTTPRequestHandler):
    server_version='RoleRadar/1.0'
    def log_message(self,fmt,*args):
        # Do not put resume content or API request bodies in access logs.
        print(self.log_date_time_string(),self.command,urllib.parse.urlsplit(self.path).path,flush=True)
    def host_ok(self):return self.headers.get('Host','') in (f'127.0.0.1:{PORT}',f'localhost:{PORT}')
    def origin_ok(self):return self.headers.get('Origin','') in ('',f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}')
    def response(self,status,data,ctype='application/json',cookie=False):
        raw=json.dumps(data).encode() if ctype=='application/json' else data if isinstance(data,bytes) else data.encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        if cookie:self.send_header('Set-Cookie',f'radar_session={TOKEN}; HttpOnly; SameSite=Strict; Path=/')
        if urllib.parse.urlsplit(self.path).path in EXTENSION_WRITES and self.headers.get('Origin','').startswith('chrome-extension://'):
            self.send_header('Access-Control-Allow-Origin',self.headers['Origin']);self.send_header('Vary','Origin')
        self.end_headers();self.wfile.write(raw)
    def session_ok(self):
        try:
            cookies=SimpleCookie(self.headers.get('Cookie',''));value=cookies.get('radar_session');return bool(value and hmac.compare_digest(value.value,TOKEN))
        except Exception:return False
    def do_OPTIONS(self):
        if not self.host_ok() or not urllib.parse.urlsplit(self.path).path in EXTENSION_WRITES:return self.response(403,{'error':'Not allowed'})
        self.send_response(204);self.send_header('Access-Control-Allow-Origin',self.headers.get('Origin',''));self.send_header('Access-Control-Allow-Methods','POST, OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type, X-Radar-Token');self.end_headers()
    def do_GET(self):
        if not self.host_ok():return self.response(403,{'error':'Invalid host'})
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/extension-config':
            if not hmac.compare_digest(self.headers.get('X-Radar-Token',''),TOKEN):return self.response(403,{'error':'Open the dashboard to reconnect the helper after restart.'})
            with core.connection() as db:result=automation.configuration(db,TOKEN,PORT)
            return self.response(200,result)
        if path=='/api/extension-queue':
            if not hmac.compare_digest(self.headers.get('X-Radar-Token',''),TOKEN):return self.response(403,{'error':'Reimport your helper profile after restarting the server.'})
            with core.connection() as db:result=automation.queue(db,ranked_jobs(db))
            return self.response(200,result)
        if path.startswith('/api/'):
            if not self.session_ok():return self.response(401,{'error':'Open the dashboard first to create a local session.'})
            if path=='/api/bootstrap':return self.response(200,bootstrap())
            if path=='/api/export-profile':
                with core.connection() as db:config=automation.configuration(db,TOKEN,PORT)
                return self.response(200,config)
            return self.response(404,{'error':'Not found'})
        files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css'}
        if path=='/extension.zip':
            import zipfile
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                for p in (core.BASE/'extension').iterdir():
                    if p.is_file():z.write(p,p.name)
            return self.response(200,buf.getvalue(),'application/zip')
        if path not in files:return self.response(404,b'Not found','text/plain')
        file=core.BASE/'web'/files[path];return self.response(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'text/plain',cookie=path in ('/','/index.html'))
    def do_POST(self):
        path=urllib.parse.urlsplit(self.path).path
        if not self.host_ok():return self.response(403,{'error':'Invalid host'})
        extension=path in EXTENSION_WRITES
        if extension:
            if not hmac.compare_digest(self.headers.get('X-Radar-Token',''),TOKEN):return self.response(403,{'error':'Reconnect helper profile from the dashboard after server restart.'})
        elif not self.origin_ok() or not self.session_ok() or self.headers.get('Sec-Fetch-Site')=='cross-site':return self.response(403,{'error':'Local session required.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>MAX_BODY:raise core.Problem('Request is empty or too large.')
            value=json.loads(self.rfile.read(length));result=self.handle_action(path,value)
            return self.response(200,result)
        except (core.Problem,ValueError,TypeError,KeyError) as e:return self.response(400,{'error':str(e)})
        except sqlite3.OperationalError as e:
            code=getattr(e,'sqlite_errorname','SQLITE_ERROR')
            print('Database request failed:',code,str(e),flush=True)
            busy=code.startswith(('SQLITE_BUSY','SQLITE_LOCKED')) or 'locked' in str(e).lower()
            return self.response(503 if busy else 500,{'error':'The database is busy. Please retry in a moment.' if busy else 'A database operation failed. Check the SQLite error in the server terminal.'})
        except Exception as e:
            print('Request failed:',type(e).__name__,flush=True);return self.response(500,{'error':'Operation failed. Check the local server log.'})
    def handle_action(self,path,value):
        if path in ('/api/helper-heartbeat','/api/extension-heartbeat'):
            with core.connection() as db:
                state={k:value[k] if isinstance(value[k],(bool,int,float)) else str(value[k])[:500] for k in ('version','enabled','auto_open','active_tabs','blocked_tabs','last_poll','error') if k in value}
                state['server_seen']=time.time();state['session']=TOKEN
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('helper_status',json.dumps(state)))
            return {'ok':True}
        if path=='/api/import-browser-jobs':
            with core.connection() as db:result=platform_ingest.import_jobs(db,value)
            return result
        if path=='/api/automation/run':
            with core.connection() as db:
                profile=core.get_profile(db)
                if not any(p.get('resume') for p in core.lane_profiles(profile)):raise core.Problem('Save a resume or enabled role lane before starting the agent.')
                db.execute("INSERT OR REPLACE INTO settings VALUES('autopilot_enabled','true')")
                db.execute("INSERT OR REPLACE INTO settings VALUES('run_requested_at',?)",(json.dumps(core.now()),))
            with core.connection() as db:state=automation_state(db)
            return {'ok':True,'queued':state['queued'],'helper_connected':state['helper_connected'],'message':'Application queue is ready. The connected Chrome helper picks it up within a minute.' if state['helper_connected'] else 'Queue enabled. Reload the Chrome extension and open the dashboard once to connect it.'}
        if path in ('/api/lane','/api/delete-lane'):
            with core.connection() as db:old_profile=core.get_profile(db)
            profile=dict(old_profile);lanes=list(profile.get('lanes',[]));lane_id=str(value.get('id','')).strip()
            if path=='/api/delete-lane':
                if not any(x.get('id')==lane_id for x in lanes):raise core.Problem('Role lane was not found.')
                lanes=[x for x in lanes if x.get('id')!=lane_id]
            else:
                if not lane_id:lane_id=secrets.token_hex(8)
                old=next((x for x in lanes if x.get('id')==lane_id),{})
                item={**old,**value,'id':lane_id}
                lanes=[x for x in lanes if x.get('id')!=lane_id]+[item]
            profile.update(core.validate_lanes({'lanes':lanes,'active_lane_id':profile.get('active_lane_id','')},old_profile))
            with core.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                if core.get_profile(db)!=old_profile:raise core.Problem('Your profile changed while saving this lane. Reload and retry.')
                db.execute('INSERT OR REPLACE INTO profile VALUES(1,?)',(json.dumps(profile),))
                db.execute('DELETE FROM notifications')
            core.create_notifications();return {'ok':True,'id':lane_id}
        if path=='/api/reserve-submit':
            with core.connection() as db:return automation.reserve(db,str(value.get('job_id','')),str(value.get('revision','')))
        if path=='/api/question-answer':
            with core.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                return application_profile.answer_question(db,str(value.get('id','')),value.get('answer',''))
        if path=='/api/resume':
            try:data=base64.b64decode(value['data'],validate=True)
            except Exception:raise core.Problem('Invalid file data.')
            name=Path(value['name']).name;text=core.parse_resume(data,name)
            return {'suggested_facts':application_profile.suggested_facts(text),'text':text,'skills':sorted(core.terms(text)),'years':core.experience(text),'resume_file':{'name':name,'data':value['data'],'type':mimetypes.guess_type(name)[0] or 'application/octet-stream'}}
        if path=='/api/profile':
            with core.connection() as db:old=core.get_profile(db)
            expected_old=old
            profile={key:str(value.get(key,'')).strip()[:limit] for key,limit in [('name',100),('email',200),('phone',80),('location',300),('roles',300),('linkedin',500),('website',500),('resume',100000)]}
            profile.update(automation.profile_extras(value,old));profile.update(application_profile.validate(value,old));profile.update(core.validate_lanes(value,old))
            if len(profile['resume'])<40 and not any(len(p.get('resume',''))>=40 for p in core.lane_profiles(profile)):raise core.Problem('Add at least 40 characters of resume text or save an enabled role lane.')
            profile['years']=max(0,min(60,int(value.get('years',0))));profile['remote']=True;profile['priority']=['remote','india','worldwide'];profile['skills']=sorted(core.terms(profile['resume']))
            if value.get('resume_file'):
                resume_file=value['resume_file'];raw=base64.b64decode(resume_file['data'],validate=True)
                if len(raw)>5*1024*1024:raise core.Problem('Resume file too large.')
                profile['resume_file']={'name':Path(str(resume_file['name'])).name[:200],'data':resume_file['data'],'type':str(resume_file.get('type','application/octet-stream'))[:100]}
            else:
                if old.get('resume_file') and old.get('resume')==profile['resume']:profile['resume_file']=old['resume_file']
            with core.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                if core.get_profile(db)!=expected_old:raise core.Problem('Your profile changed while saving. Reload and retry so recent answers or lane edits are kept.')
                db.execute('INSERT OR REPLACE INTO profile VALUES(1,?)',(json.dumps(profile),));db.execute('DELETE FROM notifications')
            core.create_notifications();return {'ok':True,'skills':profile['skills']}
        if path=='/api/delete-profile':
            with core.connection() as db:db.execute('DELETE FROM profile');db.execute('DELETE FROM notifications')
            return {'ok':True}
        if path=='/api/source':
            source=core.validate_source(value)
            with core.connection() as db:db.execute('INSERT OR IGNORE INTO sources(company,kind,board,category) VALUES(:company,:kind,:board,:category)',source)
            return {'ok':True}
        if path=='/api/import-sources':
            rows=list(csv.DictReader(io.StringIO(value.get('csv',''))))
            if not rows or len(rows)>10000:raise core.Problem('Import 1–10,000 rows with company,kind,board,category columns.')
            checked=[core.validate_source(row) for row in rows]
            with core.connection() as db:
                for row in checked:db.execute('INSERT OR IGNORE INTO sources(company,kind,board,category) VALUES(:company,:kind,:board,:category)',row)
            return {'ok':True,'rows':len(checked)}
        if path=='/api/toggle-source':
            with core.connection() as db:db.execute('UPDATE sources SET enabled=? WHERE id=?',(int(bool(value['enabled'])),int(value['id'])))
            return {'ok':True}
        if path=='/api/settings':
            threshold=max(0,min(100,int(value.get('threshold',55))))
            with core.connection() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES('autopilot_enabled',?)",(json.dumps(bool(value.get('autopilot_enabled',core.setting(db,'autopilot_enabled',True)))),))
                db.execute("INSERT OR REPLACE INTO settings VALUES('auto_submit',?)",(json.dumps(bool(value.get('auto_submit',core.setting(db,'auto_submit',True)))),))
                db.execute("INSERT OR REPLACE INTO settings VALUES('threshold',?)",(json.dumps(threshold),));db.execute("INSERT OR REPLACE INTO settings VALUES('scheduler_enabled',?)",(json.dumps(bool(value.get('scheduler_enabled',True))),))
            return {'ok':True}
        if path=='/api/collect':
            if core.COLLECTION_LOCK.locked():return {'ok':True,'already_running':True}
            def start():
                try:core.collect(force=True)
                except core.Problem:pass
            threading.Thread(target=start,daemon=True).start();return {'ok':True,'started':True}
        if path=='/api/application':
            with core.connection() as db:record_application(db,str(value['job_id']),str(value['status']))
            return {'ok':True}
        if path=='/api/read-notifications':
            with core.connection() as db:db.execute('UPDATE notifications SET seen=1')
            return {'ok':True}
        if path=='/api/extension-history':
            url=str(value.get('url',''))[:2000]
            if not core.safe_link(url):raise core.Problem('Invalid application URL.')
            event_id=str(value.get('id',''))[:100] or secrets.token_hex(12)
            title=str(value.get('title','Application form'))[:300];status=str(value.get('status','needs_review'))
            if status not in automation.STATUSES:raise core.Problem('Invalid helper event.')
            with core.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM autofill_history WHERE id=?',(event_id,)).fetchone():return {'ok':True}
                automation.event(db,value)
                application_profile.record_questions(db,value)
                db.execute('INSERT OR IGNORE INTO autofill_history(id,url,title,status,details,created) VALUES(?,?,?,?,?,?)',(event_id,url,title,status,json.dumps(value.get('details',{})),core.now()))
                if value.get('job_id') and db.execute('SELECT 1 FROM jobs WHERE id=?',(str(value['job_id']),)).fetchone():record_application(db,str(value['job_id']),status)
                for job in db.execute('SELECT id,apply_url,url FROM jobs WHERE active=1'):
                    if core.canonical_url(url) in (core.canonical_url(job['apply_url']),core.canonical_url(job['url'])):record_application(db,job['id'],status)
            return {'ok':True}
        raise core.Problem('Unknown action.')

def main():
    global PORT
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8877);p.add_argument('--once',action='store_true');p.add_argument('--no-scheduler',action='store_true');args=p.parse_args();PORT=args.port;core.init()
    with core.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS autofill_history(id TEXT PRIMARY KEY,url TEXT,title TEXT,status TEXT,details TEXT,created TEXT)')
        # A restarted process cannot continue an old in-memory scan.
        db.execute("UPDATE runs SET status='interrupted',finished=? WHERE status='running'",(core.now(),))
    if args.once:print(json.dumps(core.collect()));return
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    if not args.no_scheduler:threading.Thread(target=scheduler,daemon=True).start()
    print(f'Role Radar: http://127.0.0.1:{PORT} | 12-hour collector {"OFF" if args.no_scheduler else "ON while this process runs"}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:STOP.set();server.server_close()
if __name__=='__main__':main()
