"""Public-source job collection and deterministic resume matching. No paid API required."""
from __future__ import annotations
import concurrent.futures, datetime as dt, hashlib, html, io, ipaddress, json, os, re, socket, sqlite3, subprocess, tempfile, threading, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser, zipfile
from html.parser import HTMLParser
from pathlib import Path
from functools import lru_cache
BASE=Path(__file__).resolve().parent
DATA=Path(os.environ.get('RADAR_DATA_DIR',str(BASE/'data')))
AGENT='RoleRadar/1.0 (+local personal job search; public postings only)'
SKILLS=['python','javascript','typescript','java','c++','c#','go','rust','ruby','php','swift','kotlin','sql','react','next.js','vue','angular','node.js','django','flask','fastapi','spring','rails','html','css','tailwind','graphql','rest','postgresql','mysql','mongodb','redis','elasticsearch','aws','azure','gcp','docker','kubernetes','terraform','linux','git','ci/cd','jenkins','github actions','spark','kafka','airflow','dbt','snowflake','databricks','pandas','numpy','pytorch','tensorflow','machine learning','deep learning','nlp','llm','computer vision','data analysis','data science','statistics','mathematics','excel','power bi','tableau','looker','figma','sketch','ux','ui','user research','product design','product management','agile','scrum','jira','leadership','communication','stakeholder management','project management','sales','salesforce','hubspot','customer success','account management','business development','marketing','seo','sem','google analytics','copywriting','content writing','social media','email marketing','finance','accounting','financial modelling','audit','tax','sap','oracle','tally','operations','supply chain','procurement','logistics','recruiting','human resources','payroll','training','legal','compliance','risk management','cybersecurity','networking','penetration testing','security','testing','qa','selenium','playwright','cypress','junit','jest','autocad','solidworks','mechanical engineering','electrical engineering','civil engineering','manufacturing','quality control','healthcare','nursing','clinical research','pharmacovigilance','biotechnology','teaching','education','research','customer service','business analysis','technical writing','documentation','budgeting','negotiation','presentation','a/b testing','conversion optimisation','investment','banking','insurance','retail','hospitality','administration','public relations']
ALIASES={'reactjs':'react','react.js':'react','nodejs':'node.js','node js':'node.js','nextjs':'next.js','postgres':'postgresql','amazon web services':'aws','google cloud':'gcp','ms excel':'excel','human resource':'human resources','hr management':'human resources','scikit-learn':'machine learning','scikit learn':'machine learning','powerbi':'power bi','golang':'go','search engine optimization':'seo','search engine optimisation':'seo','user experience':'ux','user interface':'ui','generative ai':'llm'}
# Scan each description once rather than once per skill. Lookahead retains
# overlapping phrases such as both 'penetration testing' and 'testing'.
_ALIAS_PATTERN=re.compile(r'(?<![a-z0-9])(?:'+'|'.join(re.escape(s) for s in sorted(ALIASES,key=len,reverse=True))+r')(?![a-z0-9])')
_SKILL_PATTERN=re.compile(r'(?<![a-z0-9])(?=('+'|'.join(re.escape(s) for s in sorted(SKILLS,key=len,reverse=True))+r')(?![a-z0-9]))')

class Problem(Exception): pass

def now():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
class ManagedConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

def connection():
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    db=sqlite3.connect(DATA/'radar.sqlite3',timeout=30,factory=ManagedConnection); db.row_factory=sqlite3.Row;db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA foreign_keys=ON');return db

def init():
    with connection() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, company TEXT NOT NULL, kind TEXT NOT NULL, board TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Unknown', enabled INTEGER NOT NULL DEFAULT 1, last_attempt TEXT,last_success TEXT,error TEXT,failures INTEGER DEFAULT 0,next_due REAL DEFAULT 0,job_count INTEGER DEFAULT 0, UNIQUE(kind,board));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,source_id INTEGER REFERENCES sources(id),company TEXT,title TEXT,location TEXT,description TEXT,url TEXT,apply_url TEXT,remote INTEGER DEFAULT 0,employment TEXT,posted TEXT,first_seen TEXT,last_seen TEXT,active INTEGER DEFAULT 1,category TEXT,salary TEXT,UNIQUE(source_id,url));
CREATE TABLE IF NOT EXISTS profile(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications(job_id TEXT PRIMARY KEY,status TEXT NOT NULL,updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,job_id TEXT UNIQUE,title TEXT,url TEXT,score INTEGER,created TEXT,seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS autofill_history(id TEXT PRIMARY KEY,url TEXT,title TEXT,status TEXT,details TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS application_questions(id TEXT PRIMARY KEY,question TEXT,options TEXT,section TEXT,record_index INTEGER DEFAULT 0,kind TEXT,job_id TEXT,url TEXT,created TEXT,last_seen TEXT,occurrences INTEGER DEFAULT 1,answer TEXT,answered INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS submission_reservations(job_id TEXT PRIMARY KEY,revision TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS automation_attempts(job_id TEXT,revision TEXT,status TEXT,updated TEXT,PRIMARY KEY(job_id,revision));
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,started TEXT,finished TEXT,status TEXT,sources INTEGER DEFAULT 0,new_jobs INTEGER DEFAULT 0,errors INTEGER DEFAULT 0);
''')
        db.execute("INSERT OR IGNORE INTO settings VALUES('scheduler_enabled','true')")
        db.execute("INSERT OR IGNORE INTO settings VALUES('threshold','55')")
        db.execute("INSERT OR IGNORE INTO settings VALUES('interval_hours','12')")
        if db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]==0:
            for x in json.loads((BASE/'sources.json').read_text()): db.execute('INSERT OR IGNORE INTO sources(company,kind,board,category) VALUES(:company,:kind,:board,:category)',x)

def clean(value):
    text=html.unescape(html.unescape(str(value or '')))
    return re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',text)).strip()
@lru_cache(maxsize=16384)
def _cached_terms(text):
    # Descriptions from collectors are already plain text. Cache immutable facts;
    # callers receive their own set and cannot mutate another job's match data.
    text=' '+clean(text).lower()+' '
    text=_ALIAS_PATTERN.sub(lambda match:ALIASES[match.group(0)],text)
    return frozenset(match.group(1) for match in _SKILL_PATTERN.finditer(text))
def terms(text):
    return set(_cached_terms(str(text or '')))

def experience(text):
    vals=re.findall(r'(?<!\d)(\d{1,2})\+?\s*(?:years?|yrs?)\b',text.lower());return max(map(int,vals),default=0)
def get_profile(db):
    row=db.execute('SELECT data FROM profile WHERE id=1').fetchone();return json.loads(row[0]) if row else {}
def setting(db,key,default=None):
    row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else default

def validate_lanes(value,old):
    import role_matching
    try:return role_matching.validate_lanes(value,old,terms)
    except ValueError as error:raise Problem(str(error)) from None

def lane_profiles(profile):
    import role_matching
    return role_matching.lane_profiles(profile,terms)

def profile_for_job(profile,job,lane_id=None):
    import role_matching
    return role_matching.profile_for_job(profile,job,terms,lane_id)

def analyse_resume(text):
    import role_matching
    return role_matching.analyse_resume(text,terms)

def score_job(job,profile):
    import role_matching
    return role_matching.score_job(job,profile,terms)

def parse_resume(data,name):
    if len(data)>5*1024*1024:raise Problem('Resume must be 5 MB or smaller.')
    suffix=Path(name).suffix.lower()
    if suffix in ('.txt','.md'):text=data.decode('utf-8-sig',errors='replace')
    elif suffix=='.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                info=z.getinfo('word/document.xml')
                if info.file_size>10*1024*1024:raise Problem('Document expands beyond the size limit.')
                text=clean(z.read(info).decode('utf-8'))
        except (zipfile.BadZipFile,KeyError):raise Problem('Invalid DOCX document.')
    elif suffix=='.pdf':
        if not data.startswith(b'%PDF'):raise Problem('This file is not a PDF.')
        try:
            with tempfile.TemporaryDirectory() as folder:
                pdf=Path(folder)/'resume.pdf';pdf.write_bytes(data)
                result=subprocess.run(['pdftotext','-layout',str(pdf),'-'],capture_output=True,timeout=20,check=True)
                text=result.stdout.decode('utf-8',errors='replace')
        except FileNotFoundError:raise Problem('PDF extraction requires pdftotext. Upload DOCX/TXT or paste your resume instead.')
        except (subprocess.SubprocessError,OSError):raise Problem('Could not extract this PDF. Paste the text instead.')
    else:raise Problem('Use a PDF, DOCX, TXT, or Markdown resume.')
    if len(text.strip())<40:raise Problem('Too little resume text found. Scanned PDFs need OCR; paste the resume text instead.')
    return text[:100000]

class Page(HTMLParser):
    def __init__(self):super().__init__();self.scripts=[];self.links=[];self.capturing=False;self.buffer=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='script' and attrs.get('type','').lower()=='application/ld+json':self.capturing=True;self.buffer=[]
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])
    def handle_data(self,data):
        if self.capturing:self.buffer.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.capturing:self.scripts.append(''.join(self.buffer));self.capturing=False

def public_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise Problem('Only public HTTPS URLs are supported.')
    try:
        for result in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
            ip=ipaddress.ip_address(result[4][0])
            if not ip.is_global:raise Problem('Private and local network addresses are not allowed.')
    except socket.gaierror as e:raise Problem('DNS lookup failed for '+p.hostname) from e
    return url
class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,as_json=True):
    public_url(url)
    req=urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept':'application/json' if as_json else 'text/html,application/xhtml+xml'})
    try:
        with urllib.request.build_opener(Redirect()).open(req,timeout=18) as r:
            data=r.read(8*1024*1024+1)
            if len(data)>8*1024*1024:raise Problem('Source response exceeds 8 MB.')
            data=data.decode('utf-8',errors='replace');return json.loads(data) if as_json else data
    except urllib.error.HTTPError as e:raise Problem(f'Source returned HTTP {e.code}; no login or CAPTCHA bypass attempted.') from e
    except (urllib.error.URLError,TimeoutError,json.JSONDecodeError) as e:raise Problem('Source unavailable or response format changed.') from e

def canonical_url(url):
    p=urllib.parse.urlsplit(url);q=[(k,v) for k,v in urllib.parse.parse_qsl(p.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k not in ('gh_src','source','ref')]
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urllib.parse.urlencode(q),''))
def safe_link(url):
    try:
        p=urllib.parse.urlsplit(url or '');return bool(p.scheme=='https' and p.hostname and not p.username and not p.password)
    except ValueError:return False

def normalise(source,title,location,description,url,**kwargs):
    url=canonical_url(url)
    if not title or not safe_link(url):return None
    apply=kwargs.get('apply_url') or url
    if not safe_link(apply):apply=url
    return {'id':hashlib.sha256(url.encode()).hexdigest()[:24],'source_id':source['id'],'company':clean(source['company']), 'title':clean(title)[:300], 'location':clean(location)[:400] or 'Not specified','description':clean(description)[:50000],'url':url,'apply_url':apply,'remote':int(bool(kwargs.get('remote') or re.search(r'\bremote\b',str(location),re.I))),'employment':clean(kwargs.get('employment','Full-time'))[:80],'posted':str(kwargs.get('posted') or '')[:50],'category':source['category'],'salary':clean(kwargs.get('salary',''))[:300]}

def greenhouse(s):
    data=fetch(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(s['board'])}/jobs?content=true")
    if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):raise Problem('Unrecognised Greenhouse response.')
    return [normalise(s,x.get('title'),x.get('location',{}).get('name'),x.get('content'),x.get('absolute_url',''),posted=x.get('first_published') or x.get('updated_at')) for x in data['jobs']]
def lever(s):
    result=[];skip=0
    while True:
        rows=fetch(f"https://api.lever.co/v0/postings/{urllib.parse.quote(s['board'])}?mode=json&limit=100&skip={skip}")
        if not isinstance(rows,list):raise Problem('Unrecognised Lever response.')
        for x in rows:
            cats=x.get('categories') or {};sal=x.get('salaryRange') or {}
            result.append(normalise(s,x.get('text'),cats.get('location'),(x.get('descriptionPlain') or '')+' '+ ' '.join(clean(a.get('content')) for a in x.get('lists',[])),x.get('hostedUrl',''),apply_url=x.get('applyUrl'),employment=cats.get('commitment'),posted=dt.datetime.fromtimestamp(x.get('createdAt',0)/1000,dt.timezone.utc).isoformat() if x.get('createdAt') else '',salary=f"{sal.get('min','')}–{sal.get('max','')} {sal.get('currency','')} {sal.get('interval','')}" if sal else ''))
        if len(rows)<100:break
        skip+=100
        if skip>=20000:raise Problem('Pagination limit reached; partial scan not committed.')
    return result

def ashby(s):
    data=fetch(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(s['board'])}?includeCompensation=true")
    if not isinstance(data,dict) or not isinstance(data.get('jobs'),list):raise Problem('Unrecognised Ashby response.')
    return [normalise(s,x.get('title'),x.get('location'),x.get('descriptionPlain') or x.get('descriptionHtml'),x.get('jobUrl',''),apply_url=x.get('applyUrl'),remote=x.get('isRemote'),employment=x.get('employmentType'),posted=x.get('publishedAt'),salary=(x.get('compensation') or {}).get('compensationTierSummary','')) for x in data['jobs'] if x.get('isListed',True)]

def smartrecruiters(s):
    result=[];offset=0
    while True:
        data=fetch(f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(s['board'])}/postings?limit=100&offset={offset}")
        if not isinstance(data,dict) or not isinstance(data.get('content'),list):raise Problem('Unrecognised SmartRecruiters response.')
        rows=data['content']
        for x in rows:
            # Fetch full descriptions; failure aborts source rather than closing unseen jobs.
            detail=fetch(f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(s['board'])}/postings/{urllib.parse.quote(str(x['id']))}")
            sections=detail.get('jobAd',{}).get('sections',{});description=' '.join(v.get('text','') for v in sections.values() if isinstance(v,dict));loc=x.get('location') or {}
            result.append(normalise(s,x.get('name'),', '.join(str(loc[k]) for k in ('city','region','country') if loc.get(k)),description,detail.get('postingUrl') or f"https://jobs.smartrecruiters.com/{s['board']}/{x['id']}",apply_url=detail.get('applyUrl'),employment=(x.get('typeOfEmployment') or {}).get('label'),posted=x.get('releasedDate'),remote=loc.get('remote',False)))
            time.sleep(.12)
        offset+=len(rows)
        if offset>=int(data.get('totalFound',offset)) or not rows:break
        if offset>=20000:raise Problem('Pagination limit reached; partial scan not committed.')
    return result

def walk_json(value):
    if isinstance(value,list):
        for x in value:yield from walk_json(x)
    elif isinstance(value,dict):
        types=value.get('@type',[]);types=types if isinstance(types,list) else [types]
        if 'JobPosting' in types:yield value
        for k,v in value.items():
            if k in ('@graph','mainEntity','itemListElement','item'):yield from walk_json(v)

def jsonld_jobs(s,body,page_url):
    page=Page();page.feed(body);result=[]
    for script in page.scripts:
        try:objects=list(walk_json(json.loads(script)))
        except (json.JSONDecodeError,TypeError):continue
        for x in objects:
            valid=x.get('validThrough','')
            if valid and str(valid)[:10]<dt.date.today().isoformat():continue
            locations=x.get('jobLocation',[]);locations=locations if isinstance(locations,list) else [locations];names=[]
            for loc in locations:
                addr=loc.get('address',{}) if isinstance(loc,dict) else {}
                if isinstance(addr,str):names.append(addr)
                elif isinstance(addr,dict):names.append(', '.join(str(addr[k]) for k in ('addressLocality','addressRegion','addressCountry') if addr.get(k)))
            salary=x.get('baseSalary') or {};salary=clean(json.dumps(salary)) if salary else ''
            item=normalise(s,x.get('title'),' / '.join(names),x.get('description'),urllib.parse.urljoin(page_url,x.get('url') or page_url),posted=x.get('datePosted'),employment=x.get('employmentType'),remote=x.get('jobLocationType')=='TELECOMMUTE',salary=salary)
            if item:result.append(item)
    return result,page.links

def discover_ats(s,links,page_url):
    discovered=[]
    for href in links:
        link=urllib.parse.urljoin(page_url,href);p=urllib.parse.urlsplit(link)
        pieces=[x for x in p.path.split('/') if x]
        hosts={'boards.greenhouse.io':'greenhouse','job-boards.greenhouse.io':'greenhouse','jobs.lever.co':'lever','jobs.ashbyhq.com':'ashby','jobs.smartrecruiters.com':'smartrecruiters'}
        if p.hostname in hosts and pieces and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',pieces[0]):
            discovered.append((s['company'],hosts[p.hostname],pieces[0],s['category']))
    if discovered:
        with connection() as db:
            for row in set(discovered):db.execute('INSERT OR IGNORE INTO sources(company,kind,board,category) VALUES(?,?,?,?)',row)
    return len(set(discovered))

def career_page(s):
    # Bounded same-host crawl. Unsupported or JS-only boards remain visible as gaps.
    start=s['board'];public_url(start);origin=urllib.parse.urlsplit(start);robots=urllib.robotparser.RobotFileParser();robots.set_url(f'https://{origin.netloc}/robots.txt')
    try:robots.parse(fetch(robots.url,False).splitlines())
    except Problem as e:
        if 'HTTP 404' in str(e):robots.parse([])
        else:raise Problem('Could not establish robots permission; source skipped.') from e
    queue=[start];seen=set();result=[];discovered=0
    while queue and len(seen)<30:
        url=queue.pop(0)
        if url in seen:continue
        seen.add(url)
        if not robots.can_fetch(AGENT,url):continue
        if seen!={start}:time.sleep(max(1,robots.crawl_delay(AGENT) or 0))
        body=fetch(url,False);jobs,links=jsonld_jobs(s,body,url);result.extend(jobs);discovered+=discover_ats(s,links,url)
        for href in links:
            link=urllib.parse.urljoin(url,href);p=urllib.parse.urlsplit(link)
            if p.scheme=='https' and p.netloc==origin.netloc and re.search(r'careers?|jobs?|positions?|openings?',p.path,re.I) and not p.query and link not in seen:queue.append(link)
    if not result and discovered:raise Problem(f'Discovered {discovered} linked ATS sources and added them to the registry for the next scan. This page itself has no JobPosting data.')
    if not result:raise Problem('No public JobPosting JSON-LD found within 30 pages. Use a direct job URL or an ATS board; JS/login-only pages need a separate connector.')
    return result
COLLECTORS={'greenhouse':greenhouse,'lever':lever,'ashby':ashby,'smartrecruiters':smartrecruiters,'career_page':career_page}

def collect_source(source):
    try:
        rows=[j for j in COLLECTORS[source['kind']](source) if j]
        return source,rows,None
    except Exception as e:return source,[],str(e)[:500]

COLLECTION_LOCK=threading.Lock()
def collect(force=False):
    import fcntl
    if not COLLECTION_LOCK.acquire(blocking=False):raise Problem('A collection is already running.')
    lock=None;run_id=None
    try:
        lock=open(DATA/'collector.lock','a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Problem('Another collector process is already running.')
        with connection() as db:
            interval=int(setting(db,'interval_hours',12))*3600
            sources=[dict(x) for x in db.execute('SELECT * FROM sources WHERE enabled=1 AND (? OR next_due<=?)',(int(force),time.time()))];run_id=db.execute('INSERT INTO runs(started,status) VALUES(?,?)',(now(),'running')).lastrowid
        added=0;errors=0
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for source,rows,error in pool.map(collect_source,sources):
                stamp=now()
                with connection() as db:
                    if error:
                        failures=source['failures']+1;db.execute('UPDATE sources SET last_attempt=?,error=?,failures=?,next_due=? WHERE id=?',(stamp,error,failures,time.time()+min(86400,interval*2**min(failures-1,5)),source['id']));errors+=1;continue
                    # Absence from a complete ATS feed closes a job; a bounded web crawl cannot prove closure.
                    if source['kind']!='career_page':db.execute('UPDATE jobs SET active=0 WHERE source_id=?',(source['id'],))
                    for row in rows:
                        row.update(first_seen=stamp,last_seen=stamp)
                        exists=db.execute('SELECT 1 FROM jobs WHERE id=?',(row['id'],)).fetchone();added+=int(not exists)
                        db.execute('''INSERT INTO jobs(id,source_id,company,title,location,description,url,apply_url,remote,employment,posted,first_seen,last_seen,active,category,salary) VALUES(:id,:source_id,:company,:title,:location,:description,:url,:apply_url,:remote,:employment,:posted,:first_seen,:last_seen,1,:category,:salary) ON CONFLICT(id) DO UPDATE SET title=excluded.title,description=excluded.description,location=excluded.location,apply_url=excluded.apply_url,remote=excluded.remote,employment=excluded.employment,last_seen=excluded.last_seen,active=1,salary=excluded.salary''',row)
                    db.execute('UPDATE sources SET last_attempt=?,last_success=?,error=NULL,failures=0,next_due=?,job_count=? WHERE id=?',(stamp,stamp,time.time()+interval,len(rows),source['id']))
            with connection() as db:db.execute('UPDATE runs SET finished=?,status=?,sources=?,new_jobs=?,errors=? WHERE id=?',(now(),'completed_with_errors' if errors else 'completed',len(sources),added,errors,run_id))
        create_notifications();return {'sources':len(sources),'new_jobs':added,'errors':errors}
    except Exception:
        if run_id:
            with connection() as db:db.execute('UPDATE runs SET finished=?,status=? WHERE id=?',(now(),'failed',run_id))
        raise
    finally:
        if lock:lock.close()
        COLLECTION_LOCK.release()

def create_notifications():
    # Finish the read snapshot before scoring. Promoting an active WAL reader
    # to a writer after the collector commits raises SQLITE_BUSY_SNAPSHOT;
    # busy_timeout cannot retry that snapshot upgrade.
    with connection() as db:
        profile=get_profile(db)
        if not lane_profiles(profile):return
        threshold=setting(db,'threshold',55)
        jobs=[dict(row) for row in db.execute('SELECT * FROM jobs WHERE active=1').fetchall()]
    notifications=[]
    for row in jobs:
        match=score_job(row,profile)
        if match.get('relevant',True) and match['score'] is not None and match['score']>=threshold:
            notifications.append((row['id'],row['title']+' · '+row['company'],row['apply_url'],match['score'],now()))
    with connection() as db:
        # Obtain the writer lock before checking freshness; keep only this
        # small insert transaction locked, never the resume matching pass.
        db.execute('BEGIN IMMEDIATE')
        if get_profile(db)!=profile or setting(db,'threshold',55)!=threshold:return
        db.executemany('''INSERT OR IGNORE INTO notifications(job_id,title,url,score,created)
            SELECT ?,?,?,?,? WHERE EXISTS(SELECT 1 FROM jobs WHERE id=? AND active=1)''',
            [row+(row[0],) for row in notifications])

def validate_source(value):
    company=str(value.get('company','')).strip()[:100];kind=value.get('kind','');board=str(value.get('board','')).strip();category=value.get('category','Unknown')
    if not company or kind not in COLLECTORS:raise Problem('Company and a supported source type are required.')
    if category not in ('YC startup','Startup','MNC','Unknown'):raise Problem('Choose a supported company category.')
    if kind=='career_page':
        p=urllib.parse.urlsplit(board)
        if not safe_link(board) or p.port not in (None,443):raise Problem('Use a public HTTPS career page URL.')
        # Network validation occurs at fetch time, so offline source registration is possible.
        if p.hostname in ('localhost','localhost.localdomain'):raise Problem('Local URLs are not allowed.')
    elif not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',board):raise Problem('Use the ATS board identifier, not a full URL.')
    return {'company':company,'kind':kind,'board':board,'category':category}
