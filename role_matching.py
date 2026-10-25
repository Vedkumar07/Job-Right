"""Resume-specific role lanes and explainable relevance, entirely local.

Lanes are alternate user-provided resumes, not fabricated candidate personas.
The best enabled lane is selected independently for each job.
"""
from copy import deepcopy
import base64
import math
import re
from pathlib import Path
from functools import lru_cache

FAMILIES = {
    'software': ('software engineer', 'software developer', 'sde', 'application developer', 'web developer', 'programmer', 'full stack', 'fullstack', 'backend', 'back end', 'frontend', 'front end', 'python engineer', 'java engineer', 'javascript engineer', 'developer'),
    'infrastructure': ('devops', 'dev ops', 'sre', 'site reliability', 'cloud engineer', 'platform engineer', 'infrastructure engineer', 'cloud infrastructure', 'systems engineer', 'system administrator', 'linux administrator', 'release engineer'),
    'data engineering': ('data engineer', 'analytics engineer', 'etl developer', 'database engineer', 'database administrator', 'big data engineer'),
    'data science': ('data scientist', 'machine learning', 'ml engineer', 'ai engineer', 'research scientist', 'applied scientist', 'deep learning'),
    'analytics': ('data analyst', 'business analyst', 'business intelligence', 'analytics analyst', 'reporting analyst'),
    'quality': ('qa', 'quality assurance', 'test engineer', 'testing engineer', 'automation tester', 'sdet', 'quality engineer'),
    'security': ('security engineer', 'cybersecurity', 'security analyst', 'penetration tester', 'soc analyst', 'information security'),
    'design': ('designer', 'product design', 'ux', 'ui', 'user experience', 'user interface'),
    'product': ('product manager', 'product management', 'product owner'),
    'finance': ('finance', 'financial', 'accountant', 'accounting', 'auditor', 'audit', 'investment analyst', 'tax analyst'),
    'sales': ('sales', 'account executive', 'account manager', 'business development', 'sales development', 'sdr', 'bdr'),
    'marketing': ('marketing', 'seo', 'sem', 'content writer', 'copywriter', 'social media', 'growth marketer'),
    'people': ('recruiter', 'recruiting', 'human resources', 'talent acquisition', 'hr manager', 'hr executive'),
    'customer': ('customer success', 'customer support', 'customer service', 'support specialist'),
    'operations': ('operations', 'supply chain', 'logistics', 'procurement'),
    'mechanical': ('mechanical', 'manufacturing', 'automotive', 'solidworks'),
    'electrical': ('electrical', 'electronics', 'embedded', 'firmware'),
    'civil': ('civil engineer', 'construction', 'structural engineer', 'quantity surveyor'),
    'health': ('nursing', 'nurse', 'clinical', 'medical', 'pharmacovigilance', 'healthcare'),
    'legal': ('legal', 'lawyer', 'counsel', 'paralegal'),
}
FAMILY_SKILLS = {
    'software': {'python','javascript','typescript','java','react','node.js','django','flask','fastapi','html','css','c++','c#','rust','go','spring','rails','graphql'},
    'infrastructure': {'aws','azure','gcp','docker','kubernetes','terraform','linux','ci/cd','jenkins','github actions','networking'},
    'data engineering': {'sql','spark','kafka','airflow','dbt','snowflake','databricks'},
    'data science': {'machine learning','deep learning','nlp','llm','pytorch','tensorflow','computer vision','statistics'},
    'analytics': {'data analysis','sql','excel','power bi','tableau','looker'},
    'quality': {'testing','qa','selenium','playwright','cypress','junit','jest'},
    'security': {'cybersecurity','penetration testing','security','risk management'},
    'design': {'figma','sketch','ux','ui','user research','product design'},
    'finance': {'finance','accounting','financial modelling','audit','tax','tally'},
    'sales': {'sales','salesforce','hubspot','account management','business development'},
    'marketing': {'marketing','seo','sem','copywriting','content writing','social media','email marketing'},
    'people': {'recruiting','human resources','payroll'},
    'mechanical': {'autocad','solidworks','mechanical engineering','manufacturing'},
    'electrical': {'electrical engineering'}, 'civil': {'civil engineering'},
    'health': {'nursing','clinical research','pharmacovigilance','healthcare'},
}
GENERIC = {'communication','leadership','education','research','git','documentation','agile','scrum','jira','presentation','negotiation','stakeholder management','project management','budgeting','training','administration'}
STOP = {'the','and','for','with','role','job','position','senior','junior','engineer','engineering','developer','associate','specialist','intern','internship','graduate','trainee','entry','level','manager'}

@lru_cache(maxsize=32768)
def normalized(text):
    return re.sub(r'[^a-z0-9+#]+',' ',str(text).lower()).strip()

def phrase_in(phrase, text):
    return (' '+normalized(phrase)+' ') in (' '+normalized(text)+' ')

@lru_cache(maxsize=16384)
def families(text):
    return frozenset(name for name, phrases in FAMILIES.items() if any(phrase_in(p,text) for p in phrases))

def infer_families(resume, skills):
    # Strong domain evidence rather than a generic word in an education section.
    found = set(families('\n'.join(str(resume).splitlines()[:12])))
    found.update(name for name, words in FAMILY_SKILLS.items() if len(set(skills)&words)>=2)
    return found

def analyse_resume(resume, terms):
    skills=sorted(terms(resume)); detected=infer_families(resume,skills)
    suggested={'software':'Software Engineer / Backend','infrastructure':'DevOps / SRE / Cloud Engineer','data engineering':'Data Engineer','data science':'Machine Learning Engineer','analytics':'Data Analyst','quality':'QA / Test Automation','security':'Security Engineer','design':'UI / UX Designer'}
    return {'skills':skills,'role_families':sorted(detected),'suggested_roles':[suggested.get(x,x.title()) for x in sorted(detected)],
            'notice':'Detected from your text. Confirm target roles, experience and factual answers before applying.'}

def validate_lanes(value, old, terms):
    if 'lanes' not in value:
        return {key:deepcopy(old[key]) for key in ('lanes','active_lane_id') if key in old}
    lanes=value['lanes']
    if not isinstance(lanes,list) or len(lanes)>20:
        raise ValueError('Use at most 20 role lanes.')
    old_by_id={str(l.get('id','')):l for l in old.get('lanes',[]) if isinstance(l,dict)}
    cleaned=[]; seen=set(); total_bytes=0
    for index,lane in enumerate(lanes):
        if not isinstance(lane,dict):raise ValueError('Each role lane must be an object.')
        lane_id=str(lane.get('id') or 'lane-'+str(index+1)).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',lane_id) or lane_id in seen:raise ValueError('Role lane IDs must be unique simple identifiers.')
        seen.add(lane_id)
        resume=str(lane.get('resume','')).strip()
        if len(resume)>100000 or len(resume)<40:raise ValueError('Each resume needs 40–100000 characters of extracted text.')
        name=str(lane.get('name','')).strip()[:100] or 'Resume '+str(index+1)
        roles=str(lane.get('roles','')).strip()[:500]
        try:years=float(lane.get('years',old.get('years',0)))
        except (TypeError,ValueError):raise ValueError('Lane experience must be a number.') from None
        if not math.isfinite(years) or not 0<=years<=60:raise ValueError('Lane experience must be between 0 and 60 years.')
        enabled=lane.get('enabled',True)
        if not isinstance(enabled,bool):raise ValueError('Lane enabled must be true or false.')
        item={'id':lane_id,'name':name,'roles':roles,'resume':resume,'skills':sorted(terms(resume)),
              'years':years,'location':str(lane.get('location',old.get('location',''))).strip()[:300],'enabled':enabled}
        file=lane.get('resume_file')
        if not file and old_by_id.get(lane_id,{}).get('resume')==resume:file=old_by_id[lane_id].get('resume_file')
        if file:
            if not isinstance(file,dict):raise ValueError('Invalid lane resume attachment.')
            try:raw=base64.b64decode(file.get('data',''),validate=True)
            except (ValueError,TypeError):raise ValueError('Invalid resume attachment encoding.') from None
            if not raw or len(raw)>5*1024*1024:raise ValueError('Each resume attachment must be at most 5 MB.')
            total_bytes+=len(raw)
            if total_bytes>6*1024*1024:raise ValueError('Total resume attachments exceed 6 MB. Use smaller files or resume text.')
            filename=Path(str(file.get('name','resume.txt'))).name[:200]
            if Path(filename).suffix.lower() not in ('.pdf','.docx','.txt','.md'):raise ValueError('Resume attachments must be PDF, DOCX, TXT or Markdown.')
            if filename.lower().endswith('.pdf') and not raw.startswith(b'%PDF'):raise ValueError('Resume attachment is not a PDF.')
            item['resume_file']={'name':filename,'data':file['data'],'type':str(file.get('type','application/octet-stream'))[:100]}
            item['resume_filename']=filename
        cleaned.append(item)
    active=str(value.get('active_lane_id',old.get('active_lane_id','')))
    if active and active not in seen:active=''
    return {'lanes':cleaned,'active_lane_id':active}

def lane_profiles(profile, terms):
    if 'lanes' in profile and profile['lanes']:
        choices=[lane for lane in profile['lanes'] if isinstance(lane,dict) and lane.get('enabled',True) and str(lane.get('resume','')).strip()]
    elif 'lanes' in profile and profile['lanes']==[]:
        # Explicitly removing the final lane must not reactivate an older resume.
        choices=[]
    else:
        choices=[{'id':'legacy','name':'Primary resume',**{k:profile[k] for k in ('resume','resume_file','roles','skills','years','location') if k in profile}}] if str(profile.get('resume','')).strip() else []
    result=[]
    for lane in choices:
        merged={k:v for k,v in profile.items() if k not in ('lanes','active_lane_id','resume_file','resume','skills','roles')}
        merged.update({k:v for k,v in lane.items() if k!='name'}); merged['lane_id']=lane.get('id','legacy');merged['lane_name']=lane.get('name','Primary resume')
        merged['skills']=list(lane.get('skills') or terms(lane.get('resume','')))
        result.append(merged)
    return result

def role_fit(title, profile):
    target=str(profile.get('roles','')).strip(); title_normal=normalized(title)
    target_families=families(target) if target else infer_families(profile.get('resume',''),profile.get('skills',[]))
    job_families=families(title)
    explicit_phrases=[p.strip() for p in re.split(r'[,;\n|]|\s+or\s+',target) if p.strip()]
    specific=[p for p in explicit_phrases if set(normalized(p).split())-STOP]
    if any(phrase_in(p,title) for p in specific):return 1.0,target_families,job_families
    common=target_families&job_families
    if common:
        # Backend-only lanes should not silently become frontend applications.
        if common=={'software'}:
            general=any(phrase_in(p,target) for p in ('sde','software engineer','software developer','full stack','fullstack'))
            front=any(phrase_in(p,title) for p in ('frontend','front end'))
            back=any(phrase_in(p,title) for p in ('backend','back end'))
            target_front=any(phrase_in(p,target) for p in ('frontend','front end'))
            target_back=any(phrase_in(p,target) for p in ('backend','back end'))
            if not general and (front and target_back and not target_front or back and target_front and not target_back):return .15,target_families,job_families
        return .9,target_families,job_families
    # Named custom roles are alternatives; do not dilute a match by the entire list.
    title_words=set(title_normal.split())-STOP
    for phrase in specific:
        words=set(normalized(phrase).split())-STOP
        if words and words<=title_words:return .8,target_families,job_families
    if job_families and target_families and not common:return 0.0,target_families,job_families
    # A truly generic requested engineering role is supported by resume domain evidence.
    if target and not specific and re.search(r'\b(engineer|developer)\b',title_normal):
        inferred=infer_families(profile.get('resume',''),profile.get('skills',[]))
        if not job_families or inferred&job_families or any(set(profile.get('skills',[]))&FAMILY_SKILLS.get(f,set()) for f in job_families):return .7,target_families,job_families
    return 0.0,target_families,job_families

@lru_cache(maxsize=16384)
def required_experience(text):
    pattern=re.compile(r'(?<!\d)(\d{1,2})(?:\s*(?:-|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:(?:relevant|professional|industry|commercial|hands on)\s+)?(?:experience|working|in\s+[a-z])',re.I)
    required=[];preferred=[]
    for match in pattern.finditer(text):
        context=text[max(0,match.start()-35):min(len(text),match.end()+35)].lower()
        (preferred if any(w in context for w in ('preferred','nice to have','ideally')) else required).append(int(match.group(1)))
    for match in re.finditer(r'experience\s*[:\-]\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)',text,re.I):required.append(int(match.group(1)))
    return max(required,default=0),max(preferred,default=0)

def score_lane(job,profile,terms):
    title=str(job.get('title',''));description=str(job.get('description',''));required=terms(title+' '+description)
    wanted=set(profile.get('skills') or terms(profile.get('resume','')));matched=sorted(wanted&required);missing=sorted(required-wanted)
    useful=required-GENERIC; useful_match=wanted&useful;coverage=len(useful_match)/max(1,len(useful))
    fit,target_families,job_families=role_fit(title,profile)
    try:years=max(0,float(profile.get('years',0)))
    except (ValueError,TypeError):years=0
    loc=str(profile.get('location','')).lower();job_location=str(job.get('location','')).lower();remote=bool(job.get('remote'))
    geography=bool(any(x.strip() and x.strip() in job_location for x in loc.split(','))) or bool(profile.get('remote',True) and remote)
    reasons=[];warnings=[]
    if fit>=.6:reasons.append('Job title fits this resume’s target role'+(' ('+', '.join(sorted(target_families&job_families))+')' if target_families&job_families else ''))
    else:warnings.append('Job title is outside this resume’s target roles; shared generic skills do not establish a match.')
    if useful:reasons.append(f'{len(useful_match)} of {len(useful)} role-specific detected skills overlap')
    else:warnings.append('No role-specific skill keywords detected; review the full description.')
    if geography:reasons.append('Location or remote preference matches')
    value=round(45*fit+45*coverage+(10 if geography else 0))
    relevant=fit>=.6 and (coverage>=.15 or not useful)
    if fit<.6:value=min(value,34)
    if useful and not useful_match:value=min(value,40)
    minimum,preferred=required_experience(description)
    if minimum>years:
        warnings.append(f'Description mentions {minimum}+ years; your profile lists {years:g}.')
        gap=minimum-years;value=max(0,value-min(30,10*gap))
        if gap>=2:relevant=False;value=min(value,39)
    if preferred>years:warnings.append(f'{preferred}+ years appears preferred, not verified as mandatory.')
    senior=bool(re.search(r'\b(?:senior|sr\.?|staff|principal|director|head of|engineering manager)\b',title,re.I) or re.search(r'(?:tech(?:nical)? lead|team lead|engineering lead)\b',title,re.I))
    explicit_junior=bool(re.search(r'\b(?:junior|entry.level|graduate|intern|trainee|associate)\b',title,re.I))
    if senior and years<2 and not explicit_junior:
        relevant=False;value=min(value,35);warnings.append('Senior-level title conflicts with the experience entered for this resume.')
    if remote:warnings.append('Remote does not imply worldwide eligibility; verify work authorisation and country restrictions.')
    warnings.append('Explainable relevance score, not a hiring probability. Employer eligibility is not verified.')
    return {'score':max(0,min(100,value)),'matched':matched,'missing':missing,'reasons':reasons,'warnings':warnings,
            'lane_id':profile.get('lane_id','legacy'),'lane_name':profile.get('lane_name','Primary resume'),'relevant':relevant,
            'role_fit':round(fit,2),'required_years':minimum,'skill_coverage':round(coverage,3)}

def score_job(job,profile,terms):
    choices=lane_profiles(profile,terms)
    if not choices:return {'score':None,'matched':[],'missing':[],'reasons':['Add or enable a resume lane to calculate a match.'],'warnings':[],'relevant':False,'role_fit':0,'lane_id':None,'lane_name':None,'lane_matches':[]}
    scores=[score_lane(job,p,terms) for p in choices]
    best=max(scores,key=lambda m:(m['relevant'],m['score'],m['role_fit']))
    return {**best,'lane_matches':scores}

def profile_for_job(profile,job,terms,lane_id=None):
    choices=lane_profiles(profile,terms)
    if lane_id is not None:return next((p for p in choices if p['lane_id']==lane_id),{})
    if not choices:return {}
    best=score_job(job,profile,terms)
    return next((p for p in choices if p['lane_id']==best['lane_id']),{})
