"""Reusable application facts and an inbox of actual unanswered form fields."""
import hashlib,json,re
import core
TEXT_FIELDS={'professional_summary':12000,'phone_country_code':12,'available_start_date':20,'notice_period_days':8,'expected_salary':40,'salary_currency':12,'salary_period':30,'work_authorization_country':100,'authorized_to_work':20,'sponsorship_now':20,'sponsorship_future':20,'willing_relocate':20,'willing_travel':20,'employment_type':80}
RECORD_FIELDS={'work_history':('company','title','location','start_date','end_date','description'),'education':('school','degree','field','start_date','end_date','grade')}

def validate(value,old):
 out={key:str(value.get(key,old.get(key,''))).strip()[:limit] for key,limit in TEXT_FIELDS.items()}
 for key in ('authorized_to_work','sponsorship_now','sponsorship_future','willing_relocate','willing_travel'):
  if out[key] not in ('','yes','no'):raise core.Problem('Choose Yes, No, or leave unspecified for '+key.replace('_',' '))
 for key,fields in RECORD_FIELDS.items():
  rows=value.get(key,old.get(key,[]))
  if not isinstance(rows,list) or len(rows)>50:raise core.Problem('Use up to 50 '+key.replace('_',' ')+' entries.')
  out[key]=[]
  for row in rows:
   if not isinstance(row,dict):raise core.Problem('Invalid '+key.replace('_',' ')+' entry.')
   clean={field:str(row.get(field,'')).strip()[:8000 if field=='description' else 500] for field in fields}
   if not any(clean.values()):continue
   clean['current']=bool(row.get('current',False));out[key].append(clean)
 skill_years=value.get('skill_years',old.get('skill_years',{}))
 if not isinstance(skill_years,dict) or len(skill_years)>200:raise core.Problem('Skill experience must be a skill-to-years mapping.')
 out['skill_years']={}
 for skill,years in skill_years.items():
  try:years=float(years)
  except (ValueError,TypeError):raise core.Problem('Enter a numeric experience duration for '+str(skill))
  if not 0<=years<=60:raise core.Problem('Skill experience must be between 0 and 60 years.')
  out['skill_years'][str(skill).strip().lower()[:100]]=years
 return out

def suggested_facts(text):
 # Extract only explicit contact links and labelled summary text, never legal eligibility.
 result={}
 for key,pattern in [('email',r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'),('linkedin',r'https?://(?:www\.)?linkedin\.com/in/[^\s<>]+'),('github',r'https?://(?:www\.)?github\.com/[A-Za-z0-9_-]+')]:
  m=re.search(pattern,text,re.I)
  if m:result[key]=m.group(0).rstrip('.,)')
 summary=re.search(r'(?im)^\s*(?:professional summary|summary|profile|about me)\s*:?\s*\n(.+?)(?=\n\s*(?:experience|employment|education|skills|projects|certifications)\s*:?\s*(?:\n|$)|\Z)',text,re.S)
 if summary:result['professional_summary']=summary.group(1).strip()[:12000]
 return result

def record_questions(db,event):
 learn_answers(db,event)
 details=event.get('details') or {};items=details.get('questions',[])
 if not isinstance(items,list):return
 for item in items[:100]:
  if not isinstance(item,dict):continue
  question=str(item.get('label','')).strip()[:500]
  if not question:continue
  options=[str(x)[:300] for x in item.get('options',[])[:100]] if isinstance(item.get('options',[]),list) else []
  section=str(item.get('section',''))[:50]
  try:index=max(0,min(49,int(item.get('index',0))))
  except (ValueError,TypeError):index=0
  signature=json.dumps([question_key(question),section,index,sorted(options),'' if reusable_question(question_key(question)) else str(event.get('job_id',''))],sort_keys=True)
  key=hashlib.sha256(signature.encode()).hexdigest()[:24]
  db.execute('''INSERT INTO application_questions(id,question,options,section,record_index,kind,job_id,url,created,last_seen,occurrences) VALUES(?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,job_id=excluded.job_id,url=excluded.url,occurrences=application_questions.occurrences+1''',(key,question,json.dumps(options),section,index,str(item.get('kind','text'))[:40],str(event.get('job_id',''))[:100],str(event.get('url',''))[:2000],core.now(),core.now()))

def answer_question(db,question_id,answer):
 row=db.execute('SELECT * FROM application_questions WHERE id=?',(question_id,)).fetchone()
 if not row:raise core.Problem('Question was not found.')
 if not isinstance(answer,(str,bool,int,float)) or len(str(answer))>10000 or not str(answer).strip():raise core.Problem('Provide your answer before saving.')
 profile=core.get_profile(db)
 if not core.lane_profiles(profile):raise core.Problem('Save your application profile and a role resume first.')
 job=db.execute('SELECT * FROM jobs WHERE id=?',(row['job_id'],)).fetchone()
 lane=core.profile_for_job(profile,dict(job)) if job else {}
 key=question_key(row['question'])
 scope=answer_scope(key,row['job_id'],str(job['company']) if job else '',lane.get('lane_id',''))
 item={'question':row['question'],'answer':answer,'section':row['section'],'index':row['record_index'],**scope}
 def same(a):return question_key(a.get('question',''))==key and a.get('section','')==item['section'] and a.get('index',0)==item['index'] and all(a.get(k,'')==item.get(k,'') for k in ('lane_id','job_id','company'))
 profile['answers']=[x for x in profile.get('answers',[]) if not same(x)]+[item]
 db.execute('INSERT OR REPLACE INTO profile VALUES(1,?)',(json.dumps(profile),))
 for pending in db.execute('SELECT * FROM application_questions WHERE answered=0').fetchall():
  if question_key(pending['question'])==key and pending['section']==row['section'] and pending['record_index']==row['record_index'] and (reusable_question(key) or pending['job_id']==row['job_id']):
   db.execute('UPDATE application_questions SET answer=?,answered=1 WHERE id=?',(json.dumps(answer),pending['id']))
 return {'ok':True}

# Deliberately bounded equivalence classes; no fuzzy inference of eligibility.
SECRET_QUESTION=re.compile(r'password|social security|aadhaar|aadhar|passport number|bank account|credit card|\bssn\b|\botp\b|verification code',re.I)
SENSITIVE_QUESTION=re.compile(r'sponsor|visa|authori[sz]|work permit|citizen|nationality|gender|sexual|ethnic|\brace\b|religion|veteran|disabil|pronoun|salary|compensation|consent|agree|certif|attest|criminal|convict|background check|birth',re.I)

def question_key(value):
 value=re.sub(r'[^a-z0-9]+',' ',str(value).lower().replace("'",'')).strip()
 value=re.sub(r'\b(required|optional)\b','',value)
 value=re.sub(r'\s+',' ',value).strip()
 if SENSITIVE_QUESTION.search(value):return value
 for pattern,key in [(r'^(?:please )?(?:what is your |enter your |provide your |your )?(?:full |legal )?name$','full name'),(r'^(?:please )?(?:what is your |enter your |provide your |your )?(?:email|e mail)(?: address)?$','email'),(r'^(?:please )?(?:what is your |enter your |provide your |your )?(?:phone|mobile|telephone)(?: number)?$','phone')]:
  if re.fullmatch(pattern,value):return key
 match=re.fullmatch(r'(?:how many )?years?(?: of)?(?: professional)? experience (?:do you have (?:in|with)|in|with|using) (.+)',value)
 if match:return 'experience years '+match.group(1)
 match=re.fullmatch(r'(.+?) experience (?:in )?years?',value)
 if match:return 'experience years '+match.group(1)
 return value

def reusable_question(key):
 if SENSITIVE_QUESTION.search(key):return False
 return key.startswith('experience years ') or bool(re.fullmatch(r'(?:what is your |your |please provide )?(?:notice period(?: days| in days)?|available start date|earliest start date|linkedin(?: profile| url)?|github(?: profile| url)?|portfolio(?: url)?|personal website|website|professional summary|current city|city|country|postal code|zip code|employer name|company name|job title|school|university|degree|field of study|start month|start year|end month|end year)',key))

def answer_scope(key,job_id,company,lane_id):
 if reusable_question(key):return {'lane_id':lane_id} if lane_id else {}
 return {k:v for k,v in {'job_id':job_id,'company':company,'lane_id':lane_id}.items() if v}

def learn_answers(db,event):
 """Learn only actual user-entered form facts reported by the managed helper.

 Bespoke answers remain scoped to the employer/job. Legal and sensitive
 questions use exact wording and scope; they are never guessed from resume text.
 """
 details=event.get('details') or {}
 rows=details.get('answers',[])
 if not isinstance(rows,list):return 0
 profile=core.get_profile(db)
 if profile.get('learn_answers') is False:return 0
 job_id=str(event.get('job_id',''))[:100]
 job=db.execute('SELECT company FROM jobs WHERE id=?',(job_id,)).fetchone() if job_id else None
 if not job:return 0
 answers=list(profile.get('answers',[]));changed=0
 for item in rows[:50]:
  if not isinstance(item,dict) or item.get('source')!='user-entered':continue
  question=str(item.get('question','')).strip()[:500]
  answer=item.get('answer')
  if not question or SECRET_QUESTION.search(question) or not isinstance(answer,(str,bool,int,float)) or not str(answer).strip() or len(str(answer))>10000:continue
  key=question_key(question)
  if key in ('full name','email','phone'):continue
  section=str(item.get('section',''))[:50]
  try:index=max(0,min(49,int(item.get('index',0))))
  except (ValueError,TypeError):continue
  lane_id=str(item.get('lane_id',''))[:80]
  # Shared identity facts are genuinely reusable; bespoke and sensitive fields
  # must not carry an employer-specific response onto unrelated applications.
  shared=reusable_question(key)
  scope=answer_scope(key,job_id,str(job['company'])[:200],lane_id)
  learned={'question':question,'answer':answer,'source':'user-entered',**scope,**({'section':section,'index':index} if section or index else {})}
  signature=(key,section,index,scope.get('lane_id',''),scope.get('company',''),scope.get('job_id',''))
  def signature_of(a):return (question_key(a.get('question','')),a.get('section',''),int(a.get('index',0)),a.get('lane_id',''),a.get('company',''),a.get('job_id',''))
  previous=next((a for a in answers if signature_of(a)==signature),None)
  if previous and previous.get('answer')==answer:continue
  answers=[a for a in answers if signature_of(a)!=signature]
  answers.append(learned);changed+=1
  for pending in db.execute('SELECT id,question,section,record_index,job_id FROM application_questions WHERE answered=0').fetchall():
   if question_key(pending['question'])==key and pending['section']==section and pending['record_index']==index and (shared or pending['job_id']==job_id):
    db.execute('UPDATE application_questions SET answer=?,answered=1 WHERE id=?',(json.dumps(answer),pending['id']))
 if changed:
  profile['answers']=answers[-1000:]
  db.execute('INSERT OR REPLACE INTO profile VALUES(1,?)',(json.dumps(profile),))
 return changed
