(()=>{'use strict';
if(window.__roleRadarV4){window.dispatchEvent(new Event('role-radar-fill'));return}window.__roleRadarV4=true;
const E=globalThis.RoleRadarEngine;let busy=false,timer,previous='',silentPasses=0;
const storeKey='role-radar-flow:'+location.origin;
let flow;try{flow=JSON.parse(sessionStorage.getItem(storeKey)||'{}')}catch{flow={}}
function save(){try{sessionStorage.setItem(storeKey,JSON.stringify(flow))}catch{}}
function visible(el){return !el.disabled&&el.type!=='hidden'&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden'}
function fields(){const result=[];function walk(root){result.push(...root.querySelectorAll('input,textarea,select,[role="combobox"]'));for(const el of root.querySelectorAll('*'))if(el.shadowRoot)walk(el.shadowRoot)}walk(document);return [...new Set(result)].filter(el=>!el.closest('#role-radar-status'))}
function label(el){const explicit=el.labels?.length?Array.from(el.labels).map(l=>l.textContent).join(' '):'';const aria=(el.getAttribute('aria-labelledby')||'').split(' ').map(id=>document.getElementById(id)?.textContent||'').join(' ');let fallback=el.getAttribute('aria-label')||el.placeholder||'';if(!explicit&&!aria&&!fallback){const wrapper=el.closest('fieldset,[role="group"],.field,.form-group,.application-question');fallback=wrapper?.querySelector('legend,label,h3,h4')?.textContent||''}return (explicit||aria||fallback||el.name||el.id||'').replace(/[＊*]/g,'').replace(/[_\-]/g,' ').replace(/\s+/g,' ').trim()}
function question(el){if(el.type==='radio'||el.type==='checkbox'){const group=el.closest('fieldset,[role="group"],.application-question,.field,.form-group');const heading=group?.querySelector('legend,[role="heading"],h3,h4');if(heading)return heading.textContent.replace(/[＊*]/g,'').trim()}return label(el)}
function fieldContext(el,job={}){
 const container=el.closest('fieldset,[data-section],[data-automation-id*="workExperience"],[data-automation-id*="education"],.work-experience,.education-item');
 const heading=container?.querySelector?.('legend,h2,h3,h4')?.textContent||'';
 const marker=[heading,container?.id,container?.className,container?.getAttribute?.('data-section'),container?.getAttribute?.('data-automation-id')].join(' ');
 const section=/education|academic|school/i.test(marker)?'education':/work[ -]experience|employment|work history|workexperience/i.test(marker)?'work':'';
 let index=0;
 const ordinal=heading.match(/(?:experience|employment|education|school)\s*#?\s*(\d+)/i);
 if(ordinal)index=Math.max(0,Number(ordinal[1])-1);
 else if(section&&container?.parentElement){const peers=[...container.parentElement.children].filter(node=>node.matches?.('fieldset,[data-section],.work-experience,.education-item'));const at=peers.indexOf(container);if(at>=0)index=at}
 return {...job,section,index,input_type:el.type||el.getAttribute('role')};
}
function questionInfo(el,context={}){
 const ctx=fieldContext(el,context),kind=el.type||el.getAttribute('role')||'text';let options=[];
 if(el instanceof HTMLSelectElement)options=[...el.options].filter(o=>o.value&&!o.disabled).map(o=>o.text);
 else if(kind==='radio')options=fields().filter(x=>x.type==='radio'&&x.name===el.name&&x.form===el.form).map(label);
 else if(kind==='checkbox')options=['Yes','No'];
 return {label:question(el),kind,options:[...new Set(options)],required:Boolean(el.required||el.getAttribute('aria-required')==='true'),section:ctx.section,index:ctx.index};
}
function unanswered(all,p,context){const unique=new Map();for(const el of all){if(!visible(el)||['hidden','submit','button','password','file','reset'].includes(el.type)||!empty(el)||!question(el))continue;if(el.type==='radio'&&all.some(other=>other.type==='radio'&&other.name===el.name&&other.form===el.form&&other.checked))continue;const item=questionInfo(el,context);if(item.required||el.validity?.valid===false)unique.set(JSON.stringify([item.label,item.section,item.index,item.options]),item)}return [...unique.values()]}
function expandSections(all,p){
 for(const [kind,rows] of [['work',p.work_history||[]],['education',p.education||[]]]){
  if(rows.length<2)continue;const indices=new Set(all.filter(visible).map(el=>fieldContext(el)).filter(c=>c.section===kind).map(c=>c.index));
  if(!indices.size||indices.size>=rows.length)continue;const key=kind+'-'+indices.size;
  if((flow.expansions?.[key]||0)>=2)continue;
  const add=buttons().find(b=>new RegExp('^add (?:another )?'+(kind==='work'?'(?:work experience|experience|employment)':'(?:education|school)')+'(?: entry| record)?$').test(buttonText(b)));
  if(add){flow.expansions={...(flow.expansions||{}),[key]:(flow.expansions?.[key]||0)+1};save();add.click();return true}
 }return false;
}
function captchaWaiting(){const solved=[...document.querySelectorAll('textarea[name*="captcha-response"],input[name="cf-turnstile-response"]')].some(x=>Boolean(x.value));return E.interactiveCaptcha([...document.querySelectorAll('iframe')].map(frame=>({src:frame.src,title:frame.title,visible:visible(frame),width:frame.getBoundingClientRect?.().width||0,height:frame.getBoundingClientRect?.().height||0})),solved)}
function empty(el){if(el.type==='file')return !el.files?.length;if(el.type==='checkbox'||el.type==='radio')return !el.checked;const text=String(el.value||'').trim();return !text||/^(select|choose|please select|select an option|select one|please choose)(\.\.\.)?$/i.test(text)}
function setValue(el,value){const proto=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:el instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype;const setter=Object.getOwnPropertyDescriptor(proto,'value')?.set;if(setter)setter.call(el,String(value));else el.value=String(value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));el.dispatchEvent(new Event('blur',{bubbles:true}))}
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function fillControl(el,answer){const value=answer.value;
if(el.type==='checkbox'){const bool=E.yesNo(value);if(bool===null)return false;if(el.checked!==bool)el.click();return el.checked===bool}
if(el.type==='radio'){const group=fields().filter(x=>x.type==='radio'&&x.name===el.name&&x.form===el.form),options=group.map(x=>({label:label(x),value:x.value,el:x}));const found=E.choice(value,options);if(!found)return false;if(!found.el.checked)found.el.click();return found.el.checked}
if(el instanceof HTMLSelectElement){const found=E.choice(value,[...el.options].filter(x=>!x.disabled&&x.value).map(x=>({label:x.text,value:x.value})),answer.kind);if(!found)return false;setValue(el,found.value);return el.value===found.value}
if(el.getAttribute('role')==='combobox'){el.click();if(el instanceof HTMLInputElement)setValue(el,value);await delay(400);const found=E.choice(value,[...document.querySelectorAll('[role="option"]')].filter(visible).map(x=>({label:x.textContent,value:x.getAttribute('data-value')||x.textContent,el:x})));if(!found)return false;found.el.click();return true}
const target=answer.kind==='date'&&el.type==='month'?String(value).slice(0,7):value;setValue(el,target);return String(el.value)===String(target)}
function fileFor(p){if(p.resume_file){const raw=atob(p.resume_file.data);return new File([Uint8Array.from(raw,c=>c.charCodeAt(0))],p.resume_file.name,{type:p.resume_file.type||'application/octet-stream'})}return new File([p.resume],'resume.txt',{type:'text/plain'})}
function upload(el,p){if(!empty(el))return true;const file=fileFor(p);const accept=(el.accept||'').toLowerCase();if(accept&&!accept.split(',').some(part=>{const a=part.trim();return a.startsWith('.')?file.name.toLowerCase().endsWith(a):a.endsWith('/*')?file.type.startsWith(a.slice(0,-1)):a===file.type}))return false;try{const dt=new DataTransfer();dt.items.add(file);el.files=dt.files;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return el.files.length===1}catch{return false}}
function activeApplication(all){return all.some(el=>(visible(el)||el.type==='file')&&!['submit','button','reset','hidden'].includes(el.type))}
function blockers(){const out=[];if([...document.querySelectorAll('input[type="password"]')].some(visible))out.push('Employer login or account creation required');const errors=[...document.querySelectorAll('[aria-invalid="true"],[role="alert"],.field-error,.error-message')].filter(visible).map(x=>x.textContent.trim()).filter(Boolean);out.push(...errors.map(x=>x.slice(0,160)));return [...new Set(out)]}
function buttons(){return [...document.querySelectorAll('button,input[type="submit"],a[role="button"]')].filter(visible).filter(b=>b.getAttribute('aria-disabled')!=='true'&&!b.closest('#role-radar-status'))}
function buttonText(b){return E.normalise(b.innerText||b.value||b.getAttribute('aria-label')||'')}
function allowedFormButton(b){const container=b.form||b.closest('form,[role="dialog"],[data-automation-id="applicationPage"],main');if(!container)return false;const marker=[container.id,container.getAttribute?.('name'),container.getAttribute?.('aria-label'),container.querySelector?.('legend,h1,h2,h3')?.textContent].filter(Boolean).join(' ');if(/newsletter|subscribe|job alerts?|search jobs|payment|checkout/i.test(marker))return false;return !/sign in|log in|create account|subscribe|checkout|payment|delete/i.test(buttonText(b))}
function show(text){let badge=document.getElementById('role-radar-status');if(!badge){badge=document.createElement('div');badge.id='role-radar-status';badge.style.cssText='position:fixed;bottom:18px;right:18px;z-index:2147483647;background:#193c31;color:#e4f0dc;font:12px/1.6 system-ui;padding:13px 18px;border-radius:8px;box-shadow:0 4px 25px #0003;max-width:340px;pointer-events:none';document.body.appendChild(badge)}badge.textContent=text}
async function report(status,details,context){const signature=JSON.stringify({status,details,url:location.href});if(signature===previous)return;previous=signature;try{await chrome.runtime.sendMessage({type:'history',event:{url:location.href,title:document.title,job_id:context?.job_id,revision:context?.revision,status,details}})}catch{}}
async function run(){if(busy)return;busy=true;try{
const {configuration,enabled=true}=await chrome.storage.local.get(['configuration','enabled']);
let context={};try{context=await chrome.runtime.sendMessage({type:'context'})||{}}catch{}
if(context.paused||Array.isArray(configuration?.profiles)&&!configuration.profiles.length)return;
const selected=configuration?.profiles?.find(profile=>profile.lane_id===context.lane_id)||context.profile||configuration?.profile;
const p=selected?{...selected,answers:configuration?.profile?.answers||selected.answers||[]}:null;
if(!enabled||!p?.resume)return;
const managed=Boolean(context.job_id),autoSubmit=configuration.automation?.auto_submit===true;
// Resume an existing managed tab, but do not apply on arbitrary pages solely because a URL contains "job".
const supported=/(?:^|\.)(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|myworkdayjobs\.com|ycombinator\.com|workatastartup\.com|naukri\.com)$/.test(location.hostname);
if(!supported&&!managed&&!context.manual)return;
if(managed&&configuration.automation?.enabled===false)return;
if(flow.jobId&&context.job_id&&flow.jobId!==context.job_id)flow={};flow.jobId=context.job_id||flow.jobId;
const all=fields(),editable=all.some(el=>visible(el)&&!el.readOnly&&!['checkbox','radio','submit','button'].includes(el.type));
const successNodes=[...document.querySelectorAll('main,[role="main"],[role="status"],[role="alert"],.application-confirmation')].filter(x=>visible(x)&&!x.closest('#role-radar-status'));
const successText=successNodes.length?successNodes.map(x=>x.innerText||x.textContent).join(' '):document.title;
if(E.confirmed(successText,editable)){
 if(flow.submitAttempted||managed){flow.confirmed=true;save();await report('submitted',{filled:flow.filled||[],remaining:[],confirmation:'Employer page displayed an application confirmation'},context);show('Role Radar · Application submission confirmed. Saved in your history.')}return}
if(flow.submitAttempted){await report('submission_attempted',{filled:flow.filled||[],remaining:['Waiting for employer confirmation. No automatic resubmission will be attempted.']},context);show('Role Radar · Submission attempted; confirmation not yet detected.');return}
if(managed&&!activeApplication(all)&&!flow.submitAttempted){
 const link=[...document.querySelectorAll('a[href]')].find(a=>visible(a)&&/^(apply|apply now|apply for this job|apply for this position|apply on company site|apply on company website|apply on employer site)$/.test(E.normalise(a.textContent)));
 if(link){const target=new URL(link.href,location.href);if(target.protocol==='https:'&&!target.username&&!target.password&&target.href!==location.href){if(target.origin!==location.origin){const allowed=await chrome.runtime.sendMessage({type:'navigate_apply',url:target.href});if(!allowed?.ok){await report('needs_review',{filled:[],remaining:['The employer application link could not be safely verified. No application was opened.']},context);return}}flow.steps=(flow.steps||0)+1;save();if(flow.steps<=30){location.assign(target.href);return}}}
}
const stops=blockers().filter(message=>/login|account creation/i.test(message));if(stops.length){await report('needs_review',{filled:[],remaining:stops},context);show('Role Radar · Paused: '+stops[0]);return}
if(expandSections(all,p)){schedule(1500);return}
const filled=[],groups=new Set(),ambiguous=[];let active=0;
for(const el of all){if(!visible(el)&&el.type!=='file')continue;if(['submit','button','reset','password','hidden'].includes(el.type))continue;active++;
if(el.type==='file'){if(/resume|résumé|\bcv\b/i.test(label(el))&&empty(el)&&upload(el,p))filled.push('Resume file');continue}
if(el.readOnly)continue;const q=question(el),ctx=fieldContext(el,context),answer=E.answerFor(q,p,ctx);if(!answer)continue;
if(!['radio','checkbox'].includes(el.type)&&all.filter(other=>visible(other)&&!['radio','checkbox','hidden','file'].includes(other.type)&&E.normalise(question(other))===E.normalise(q)&&fieldContext(other).section===ctx.section&&fieldContext(other).index===ctx.index).length>1){if(el.required||el.getAttribute('aria-required')==='true')ambiguous.push('Repeated question needs a section-specific answer: '+q);continue}
const section=el.closest('fieldset,section,[role=group]');const heading=section?.querySelector?.('legend,h2,h3,h4')?.textContent||'';if(/reference|referee|emergency contact/i.test(heading))continue;
if(el.type==='radio'){const key=el.name+'|'+q;if(groups.has(key))continue;groups.add(key)}
else if(el.type!=='checkbox'&&!empty(el))continue;
if(await fillControl(el,answer))filled.push(q||'Profile field')}
await delay(filled.includes('Resume file')?1200:350);
const remaining=[...ambiguous];let unknownControls=false;
for(const el of all.filter(el=>(visible(el)||el.type==='file')&&(el.required||el.getAttribute('aria-required')==='true'))){if(el.type==='radio'){if(!all.some(other=>other.type==='radio'&&other.name===el.name&&other.form===el.form&&other.checked))remaining.push(question(el)||'Required selection')}else if(empty(el))remaining.push(question(el)||'Required field')}
for(const el of all.filter(visible))if(el.willValidate&&el.validity&&!el.validity.valid)remaining.push((question(el)||'Field')+' needs a valid answer');
// Unanswered bespoke controls and checked legal conditions cannot be inferred from a CV.
for(const el of document.querySelectorAll('[role="checkbox"][aria-required="true"],[role="radio"][aria-required="true"],[contenteditable="true"][aria-required="true"]'))if(visible(el)&&el.getAttribute('aria-checked')!=='true'&&(el.getAttribute('role')!=='textbox'||!el.textContent.trim())){unknownControls=true;remaining.push(el.getAttribute('aria-label')||'Unsupported required custom control')}
for(const el of all.filter(el=>visible(el)&&el.type==='checkbox'&&(el.required||el.getAttribute('aria-required')==='true'))){if(/agree|consent|certif|attest|terms/i.test(question(el))&&!E.answerFor(question(el),p,fieldContext(el,context))){unknownControls=true;remaining.push(question(el)||'Agreement needs a saved answer')}}
const errors=blockers(),bs=buttons().filter(allowedFormButton),next=bs.find(b=>/^(next|next step|continue|save and continue|review|review application|suivant|etape suivante|continuer|proximo|seguinte|avancar|continuar|下一步|继续|下一页)$/.test(buttonText(b))),submit=bs.find(b=>{const text=buttonText(b);if(!/^(submit|submit application|send application|submit my application|apply now|soumettre|envoyer|envoyer ma candidature|postuler|enviar candidatura|enviar|candidatar me|提交申请|提交|立即申请)$/.test(text))return false;if(text!=='submit')return true;const form=b.form||b.closest('form');if(!form)return false;const marker=[form.id,form.getAttribute?.('name'),form.getAttribute?.('aria-label')].join(' ');return /apply|application|candidate/i.test(marker)||all.some(el=>el.form===form&&/resume|résumé|\bcv\b/i.test(label(el))) });
const state={managed,autoSubmit,captcha:captchaWaiting(),fields:active,remaining:[...new Set(remaining)],blockers:errors,unknownControls,next,submit};
const action=E.actionFor(state);flow.filled=[...new Set([...(flow.filled||[]),...filled])];save();const details={lane_id:context.lane_id,lane_name:context.lane_name,filled:flow.filled,questions:unanswered(all,p,context),remaining:[...new Set([...state.remaining,...errors])]};
if(action==='awaiting_captcha'){await report('awaiting_captcha',{...details,block_reason:'captcha',remaining:[...details.remaining,'Solve the CAPTCHA in this tab. The application agent resumes afterwards.']},context);show('Role Radar · Details filled. Solve this CAPTCHA once; I will continue automatically.');return}
if(action==='needs_review'){silentPasses++;if(silentPasses<3&&!details.remaining.length){schedule(1800);return}if(!details.remaining.length)details.remaining.push(active?'No supported continue or submit control was found.':'No supported application form found.');await report('needs_review',details,context);show('Role Radar · Needs an answer or unsupported step. Saved in history.');return}
silentPasses=0;
if(action==='next'){
 const fingerprint=location.href+'|'+all.filter(visible).map(el=>label(el)).join('|');
 if(flow.lastStep===fingerprint){if(Date.now()-(flow.lastStepAt||0)<12000){schedule(1800);return}await report('needs_review',{...details,remaining:['The form did not advance after Continue. Check validation or custom controls.']},context);return}
 flow.steps=(flow.steps||0)+1;if(flow.steps>30){await report('needs_review',{...details,remaining:['Application exceeded the supported multi-step flow.']},context);return}
 flow.lastStep=fingerprint;flow.lastStepAt=Date.now();save();await report('in_progress',details,context);next.click();schedule(2200);return}
if(action==='submit'){
 // Persist first. A reload, timeout or duplicate observer must not click Submit twice.
 flow.submitAttempted=true;save();const ack=await chrome.runtime.sendMessage({type:'reserve_submit',job_id:context.job_id,revision:context.revision});
 if(!ack?.ok){flow.submitAttempted=false;save();await report('needs_review',{...details,remaining:['Could not reserve this submission in your history; no Submit click was made.']},context);return}
 await report('submission_attempted',{...details,remaining:['Submission requested; waiting for explicit employer confirmation.']},context);submit.click();show('Role Radar · Submitting your application…');schedule(2500);return}
await report('autofilled',details,context);show('Role Radar · Form filled. Autopilot submission is paused or this tab is not in its queue.');
}catch(e){show('Role Radar · Could not complete this form. See application history.');try{await chrome.runtime.sendMessage({type:'history',event:{url:location.href,title:document.title,status:'needs_review',details:{filled:[],remaining:['Browser control failed: '+String(e.message||e).slice(0,120)]}}})}catch{}}
finally{busy=false}}
function schedule(ms=1000){clearTimeout(timer);timer=setTimeout(run,ms)}
let learningTimer;const observedAnswers=new Map();
document.addEventListener?.('change',event=>{if(!event.isTrusted)return;const el=event.target;if(!el||!visible(el)||['password','file','hidden','submit','button'].includes(el.type))return;const heading=el.closest('fieldset,section,[role=group]')?.querySelector?.('legend,h2,h3,h4')?.textContent||'';if(/reference|referee|emergency contact/i.test(heading))return;const name=question(el);if(!name||/password|social security|aadhaar|aadhar|passport number|bank account|credit card|\bssn\b|\botp\b|verification code/i.test(name))return;let value;if(el.type==='checkbox')value=Boolean(el.checked);else if(el.type==='radio'){if(!el.checked)return;value=label(el)}else if(el instanceof HTMLSelectElement)value=el.options[el.selectedIndex]?.text||el.value;else value=el.value;if(value===undefined||value===null||!String(value).trim())return;const ctx=fieldContext(el);observedAnswers.set(JSON.stringify([name,ctx.section,ctx.index]),{question:name,answer:value,section:ctx.section,index:ctx.index,source:'user-entered'});clearTimeout(learningTimer);learningTimer=setTimeout(async()=>{const {configuration}=await chrome.storage.local.get('configuration');if(configuration?.profile?.learn_answers===false)return;let context;try{context=await chrome.runtime.sendMessage({type:'context'})}catch{return}if(!context?.job_id)return;const answers=[...observedAnswers.values()].map(a=>({...a,lane_id:context.lane_id}));observedAnswers.clear();await report('in_progress',{filled:[],remaining:[],answers,lane_id:context.lane_id},context);schedule(300);},1200);});
window.addEventListener('role-radar-fill',()=>schedule(0));schedule();setInterval(()=>schedule(),7000);
new MutationObserver(records=>{if(records.some(r=>!r.target.closest?.('#role-radar-status')))schedule(1100)}).observe(document.documentElement,{subtree:true,childList:true});
})();
