document.addEventListener('click',event=>{const button=event.target.closest('[data-confirm]');if(button&&!window.confirm(button.dataset.confirm)){event.preventDefault();}});
document.addEventListener('submit',event=>{const submitter=event.submitter;if(submitter){setTimeout(()=>{submitter.disabled=true;submitter.dataset.originalText=submitter.textContent;submitter.textContent='处理中…';},0);}});
(()=>{
 const form=document.querySelector('[data-wizard]');
 if(form){
   const panels=[...form.querySelectorAll('[data-wizard-step]')],labels=[...document.querySelectorAll('[data-step-label]')];let current=0;
   const setStep=n=>{current=n;panels.forEach((p,i)=>p.hidden=i!==n);labels.forEach((l,i)=>l.classList.toggle('current',i===n));
     if(n===2){document.querySelector('#setup-summary-name').textContent=form.elements.name.value.trim();const selected=[...form.querySelectorAll('[name=presets]:checked')].map(x=>x.dataset.sourceName);document.querySelector('#setup-summary-sources').textContent=selected.length?selected.join('、'):'稍后导入自己的文件';}
   };
   const validStep=()=>{
     if(current===0){for(const field of panels[0].querySelectorAll('input,select')){if(!field.checkValidity()){field.reportValidity();return false;}}}
     if(current===1&&!form.querySelector('[name=presets]:checked')&&!form.elements.use_upload.checked){document.querySelector('#setup-source-error').textContent='请至少勾选一个来源，或选择稍后导入自己的文件。';return false;}
     return true;
   };
   form.addEventListener('click',e=>{if(e.target.closest('[data-next]')&&validStep())setStep(Math.min(2,current+1));if(e.target.closest('[data-prev]'))setStep(Math.max(0,current-1));});
   form.addEventListener('submit',e=>{if(current!==2){e.preventDefault();if(validStep())setStep(Math.min(2,current+1));}});
   form.addEventListener('change',e=>{if(e.target.name==='presets'||e.target.name==='use_upload'){if(form.querySelector('[name=presets]:checked')||form.elements.use_upload.checked)document.querySelector('#setup-source-error').textContent='';}});
   const industry=form.elements.industry,coverage=document.querySelector('#setup-coverage');
   industry.addEventListener('change',()=>{coverage.textContent=industry.value==='consumer'?'当前来源以综合新闻和科技资讯为主，消费品牌覆盖可能有限，不含社交平台投诉或评论。可先查看公开报道，也可导入自有反馈。':'这些是公开资讯订阅，不是全网搜索。没有报道你的关注对象时，就不会出现相关提及；不包含抖音、小红书或微博定向评论。';});
   setStep(0);
 }
 const panel=document.querySelector('[data-first-results]');
 if(panel){
   let attempts=0;const status=document.querySelector('#first-poll-status');
   async function poll(){
     if(++attempts>120){status.textContent='本页自动更新已暂停，后台仍会继续。可稍后刷新或返回工作台查看。';return;}
     try{
       const response=await fetch(panel.dataset.firstResults,{credentials:'same-origin',headers:{'Accept':'application/json'}});
       if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('not available');
       const data=await response.json();
       for(const [id,value]of [['first-title',data.title],['first-detail',data.detail],['first-total',data.total],['first-matches',data.matches],['first-failures',data.failures]])document.getElementById(id).textContent=String(value);
       const sources=document.querySelector('#first-sources');sources.replaceChildren();
       for(const source of data.sources){const row=document.createElement('div');row.className='list-row';const name=document.createElement('strong');name.textContent=source.name;const badge=document.createElement('span');badge.className='badge';badge.textContent=source.status;const time=document.createElement('small');time.textContent='最近成功：'+source.last_success;row.append(name,badge,time);sources.append(row);}
       if(data.report_id){const link=document.createElement('a');link.className='button';link.href='/reports/'+data.report_id+'/';link.textContent='查看首次报告 →';document.querySelector('#first-report').replaceChildren(link);}
       status.classList.remove('poll-warning');status.textContent=data.finished?'检查结果已更新；只有实际命中的内容才计为相关提及。':'后台正在处理，页面会自动更新。';
       if(data.finished&&(data.report_id||['import_required','failed','paused'].includes(data.stage)))return;
     }catch{status.textContent='暂时无法刷新状态，原有结果保留。系统会再次尝试，你也可以稍后手动刷新。';status.classList.add('poll-warning');}
     window.setTimeout(poll,3000);
   }
   window.setTimeout(poll,1500);
 }
})();

(()=>{
 const search=document.querySelector('[data-source-search]');if(!search)return;
 const cards=[...document.querySelectorAll('[data-source-card]')],count=document.querySelector('[data-source-count]');
 const update=()=>{const term=search.value.trim().toLowerCase();cards.forEach(c=>c.hidden=!c.textContent.toLowerCase().includes(term));count.textContent=cards.filter(c=>!c.hidden).length+' 个来源 / 共 '+cards.length+' 个';};
 search.addEventListener('input',update);
 document.querySelector('[data-source-select]').addEventListener('click',()=>cards.filter(c=>!c.hidden).forEach(c=>{const input=c.querySelector('[name=presets]');if(input&&!input.disabled)input.checked=true;}));
 document.querySelector('[data-source-clear]').addEventListener('click',()=>cards.forEach(c=>{const input=c.querySelector('[name=presets]');if(input)input.checked=false;}));update();
})();

(()=>{
 const panel=document.querySelector('[data-monitor-progress]');if(!panel)return;
 let attempts=0;
 async function update(){
  if(++attempts>120){panel.textContent='后台仍在继续处理，可稍后刷新工作台或查看来源采集记录。';return;}
  try{
   const response=await fetch('/monitor/status/',{credentials:'same-origin',cache:'no-store'});
   if(!response.ok)throw Error('status unavailable');
   const data=await response.json();
   if(!data.active){window.location.reload();return;}
   panel.textContent=`监测正在处理：排队 ${data.queued} 项，进行中 ${data.running} 项。完成后自动更新结果。`;
  }catch{panel.textContent='暂时无法更新进度，后台任务仍会继续。可刷新页面或查看来源采集记录。';}
  window.setTimeout(update,3000);
 }
 window.setTimeout(update,1500);
})();

(()=>{
 const button=document.querySelector('[data-monitor-button]');if(!button)return;
 const deadline=Date.now()+Number(button.dataset.cooldownSeconds||0)*1000;
 function tick(){
  const seconds=Math.max(0,Math.ceil((deadline-Date.now())/1000));
  button.disabled=seconds>0;
  button.textContent=seconds>0?`立即检索（${seconds}秒）`:'立即检索';
  if(seconds>0)window.setTimeout(tick,250);
 }
 tick();
})();
