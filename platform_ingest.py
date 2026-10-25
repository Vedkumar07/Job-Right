"""Bounded import of job cards observed in the owner's logged-in browser."""
import urllib.parse
import core

PLATFORMS={
    'naukri':{'hosts':('naukri.com',),'board':'https://www.naukri.com/','company':'Naukri · browser capture','category':'Unknown'},
    'yc':{'hosts':('ycombinator.com','workatastartup.com'),'board':'https://www.workatastartup.com/jobs','company':'YC · browser capture','category':'YC startup'},
}

def import_jobs(db,value):
    key=str(value.get('platform','')).lower()
    key={'ycombinator':'yc','workatastartup':'yc'}.get(key,key)
    platform=PLATFORMS.get(key)
    if not platform:raise core.Problem('Browser capture supports YC/Work at a Startup and Naukri.')
    jobs=value.get('jobs')
    if not isinstance(jobs,list) or len(jobs)>100:raise core.Problem('Send up to 100 observed job cards at a time.')
    checked=[]
    for item in jobs:
        if not isinstance(item,dict):raise core.Problem('Invalid observed job card.')
        url=str(item.get('url',''))
        if len(url)>2000 or not core.safe_link(url):raise core.Problem('Observed job links must use HTTPS.')
        parsed=urllib.parse.urlsplit(url);host=parsed.hostname.lower().rstrip('.')
        if parsed.port not in (None,443) or not any(host==h or host.endswith('.'+h) for h in platform['hosts']):raise core.Problem('Job link does not belong to the selected platform.')
        if key=='naukri' and not parsed.path.startswith('/job-listings-'):raise core.Problem('Naukri links must identify a job listing.')
        if key=='yc' and not ('/jobs/' in parsed.path):raise core.Problem('YC links must identify a job listing.')
        title=core.clean(item.get('title',''))[:300]
        if not title:continue
        # Job IDs are in the path on these platforms. Drop the query and
        # fragment entirely: either can contain tracking or session tokens.
        url=urllib.parse.urlunsplit((parsed.scheme.lower(),parsed.netloc.lower(),parsed.path.rstrip('/'),'',''))
        url=core.canonical_url(url)
        checked.append({'title':title,'company':core.clean(item.get('company',''))[:200] or 'Company not captured',
                        'description':core.clean(item.get('description',''))[:20000],
                        'location':core.clean(item.get('location',''))[:400], 'url':url})
    if not checked:return {'ok':True,'imported':0,'observed':0}
    db.execute('INSERT OR IGNORE INTO sources(company,kind,board,category,enabled) VALUES(?,?,?,?,0)',(platform['company'],'browser',platform['board'],platform['category']))
    source=dict(db.execute('SELECT * FROM sources WHERE kind=? AND board=?',('browser',platform['board'])).fetchone())
    stamp=core.now();added=0
    for item in checked:
        row=core.normalise(source,item['title'],item['location'],item['description'],item['url'])
        row.update(company=item['company'],first_seen=stamp,last_seen=stamp)
        added+=not bool(db.execute('SELECT 1 FROM jobs WHERE id=?',(row['id'],)).fetchone())
        db.execute('''INSERT INTO jobs(id,source_id,company,title,location,description,url,apply_url,remote,employment,posted,first_seen,last_seen,active,category,salary)
            VALUES(:id,:source_id,:company,:title,:location,:description,:url,:apply_url,:remote,:employment,:posted,:first_seen,:last_seen,1,:category,:salary)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title,company=excluded.company,location=excluded.location,
            description=CASE WHEN LENGTH(excluded.description)>LENGTH(jobs.description) THEN excluded.description ELSE jobs.description END,
            last_seen=excluded.last_seen,active=1''',row)
    db.execute('UPDATE sources SET last_attempt=?,last_success=?,error=NULL,job_count=(SELECT COUNT(*) FROM jobs WHERE source_id=? AND active=1) WHERE id=?',(stamp,stamp,source['id'],source['id']))
    return {'ok':True,'imported':added,'observed':len(checked),'platform':key}
