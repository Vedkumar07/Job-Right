"""Local application policy and revision-aware queue; no vendor backend dependency."""
import hashlib,json,re
import core
TERMINAL={'applied','submitted','submission_attempted'}
STATUSES={'awaiting_captcha','in_progress','autofilled','needs_review','submission_attempted','submitted','failed'}
EXTRA_FIELDS={'github':500,'current_city':150,'country':150,'state':150,'postal_code':40,'street':300,'current_company':200,'current_title':200,'cover_letter':20000}

def profile_extras(value,old):
    out={k:str(value.get(k,old.get(k,''))).strip()[:limit] for k,limit in EXTRA_FIELDS.items()}
    answers=value.get('answers',old.get('answers',[]))
    if not isinstance(answers,list) or len(answers)>1000:raise core.Problem('Use a list of up to 1,000 saved questions and answers.')
    out['answers']=[];seen={}
    for item in answers:
        if not isinstance(item,dict):raise core.Problem('Every saved answer needs a question and answer.')
        question=str(item.get('question','')).strip();answer=item.get('answer','')
        if not question or not str(answer).strip():continue
        section=str(item.get('section',''))[:50];lane_id=str(item.get('lane_id',''))[:80];company=str(item.get('company',''))[:200];job_id=str(item.get('job_id',''))[:100];index=max(0,min(49,int(item.get('index',0))));key=(re.sub(r'[^a-z0-9]+',' ',question.lower()).strip(),section,index,lane_id,company,job_id)
        if len(question)>500 or len(str(answer))>10000:raise core.Problem('A saved question or answer is too long.')
        normalized_answer=answer if isinstance(answer,bool) else str(answer).strip()
        if key in seen:
            if seen[key]!=normalized_answer:raise core.Problem('Conflicting saved answers for duplicate question: '+question[:80]+'. Keep one answer or give each question a different context.')
            continue
        seen[key]=normalized_answer;out['answers'].append(dict({'question':question,'answer':normalized_answer},**({'section':section,'index':index} if section or index else {}),**{k:v for k,v in {'lane_id':lane_id,'company':company,'job_id':job_id,'source':str(item.get('source',''))[:40]}.items() if v}))
    out['learn_answers']=value.get('learn_answers',old.get('learn_answers',True)) is not False
    return out

def revision(profile,auto_submit=True):
    # Includes the resume digest through the saved data, so resume changes invalidate stale blocked attempts.
    return hashlib.sha256(json.dumps({'profile':profile,'auto_submit':auto_submit},sort_keys=True).encode()).hexdigest()[:24]

def fact_revision(profile):
    return hashlib.sha256(json.dumps({k:v for k,v in profile.items() if k not in ('answers','learn_answers','fact_revision')},sort_keys=True).encode()).hexdigest()[:24]

def configuration(db,token,port):
    profile=core.get_profile(db);auto_submit=core.setting(db,'auto_submit',True)
    return {'profile':profile,'profiles':[{**p,'fact_revision':fact_revision(p)} for p in core.lane_profiles(profile)],'historyEndpoint':f'http://127.0.0.1:{port}/api/extension-history','historyToken':token,'automation':{'auto_submit':auto_submit,'enabled':core.setting(db,'autopilot_enabled',True),'revision':revision(profile,auto_submit),'no_daily_cap':True,'run_requested_at':core.setting(db,'run_requested_at',None),'version':'4.0.3'}}

def queue(db,ranked):
    config=configuration(db,'',8877);rev=config['automation']['revision'];threshold=core.setting(db,'threshold',55)
    if not core.setting(db,'autopilot_enabled',True) or not any(p.get('resume') for p in core.lane_profiles(config['profile'])):return {'jobs':[],'revision':rev}
    attempts={r['job_id']:r['status'] for r in db.execute('SELECT job_id,status FROM automation_attempts WHERE revision=?',(rev,))}
    reserved={r['job_id'] for r in db.execute('SELECT job_id FROM submission_reservations')}
    jobs=[]
    for j in ranked:
        match=j['match']
        if (match['score'] or 0)<threshold or match.get('relevant') is False or j.get('application_status') in TERMINAL|{'dismissed'} or j['id'] in attempts or j['id'] in reserved:continue
        selected=core.profile_for_job(config['profile'],j,match.get('lane_id'))
        if not selected.get('resume'):continue
        jobs.append({'job_id':j['id'],'title':j['title']+' · '+j['company'],'url':j['apply_url'],'score':match['score'],'revision':rev,'job_title':j['title'],'company':j['company'],'job_location':j['location'],'lane_id':selected.get('lane_id','legacy'),'lane_name':selected.get('lane_name','Default profile'),'fact_revision':fact_revision(selected)})
    return {'jobs':jobs[:20],'revision':rev}

def event(db,value):
    job_id=str(value.get('job_id',''));rev=str(value.get('revision',''))[:80];status=value['status']
    if job_id and rev and db.execute('SELECT 1 FROM jobs WHERE id=?',(job_id,)).fetchone():
        db.execute('''INSERT INTO automation_attempts(job_id,revision,status,updated) VALUES(?,?,?,?) ON CONFLICT(job_id,revision) DO UPDATE SET status=CASE WHEN automation_attempts.status='submitted' THEN 'submitted' ELSE excluded.status END,updated=excluded.updated''',(job_id,rev,status,core.now()))

def reserve(db,job_id,revision_value):
    db.execute('BEGIN IMMEDIATE')
    config=configuration(db,'',8877)
    if not config['automation']['enabled'] or not config['automation']['auto_submit']:return {'ok':False,'error':'Autopilot submission is paused.'}
    if revision_value!=config['automation']['revision']:return {'ok':False,'error':'Your profile changed. Reload this application before submitting.'}
    job=db.execute('SELECT * FROM jobs WHERE id=? AND active=1',(job_id,)).fetchone()
    if not job:return {'ok':False,'error':'Job is no longer active.'}
    match=core.score_job(dict(job),config['profile']);score=match['score']
    if score is None or match.get('relevant') is False or score<core.setting(db,'threshold',55):return {'ok':False,'error':'Job does not meet your match threshold.'}
    prior=db.execute('SELECT status FROM applications WHERE job_id=?',(job_id,)).fetchone()
    if prior and prior['status'] in TERMINAL|{'dismissed'}:return {'ok':False,'error':'A submission was already recorded for this job.'}
    added=db.execute('INSERT OR IGNORE INTO submission_reservations VALUES(?,?,?)',(job_id,revision_value,core.now())).rowcount
    if not added:return {'ok':False,'error':'Submission was already reserved. No repeat click is allowed.'}
    db.execute("INSERT INTO applications(job_id,status,updated) VALUES(?,'submission_attempted',?) ON CONFLICT(job_id) DO UPDATE SET status='submission_attempted',updated=excluded.updated",(job_id,core.now()))
    return {'ok':True}
