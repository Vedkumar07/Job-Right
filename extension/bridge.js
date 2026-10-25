(()=>{'use strict';if(!['http://127.0.0.1:8877','http://localhost:8877'].includes(location.origin))return;
async function sync(){try{const r=await fetch('/api/export-profile',{credentials:'include',cache:'no-store'});if(!r.ok)return;const configuration=await r.json();if(!configuration.historyToken)return;const {configuration:old}=await chrome.storage.local.get('configuration');if(JSON.stringify(old?.automation)===JSON.stringify(configuration.automation)&&old?.historyToken===configuration.historyToken)return;await chrome.storage.local.set({configuration});chrome.runtime.sendMessage({type:'sync'});chrome.runtime.sendMessage({type:'poll'})}catch{}}
window.addEventListener('message',event=>{if(event.source!==window||event.origin!==location.origin||event.data?.type!=='role-radar-run')return;sync().then(()=>chrome.runtime.sendMessage({type:'run'}))});
sync();setInterval(sync,15000);
})();
