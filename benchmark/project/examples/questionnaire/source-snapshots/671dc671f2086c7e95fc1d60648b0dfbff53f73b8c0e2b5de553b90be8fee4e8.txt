'use strict';
(function(root){
  const BASE='/household50-current',UI='eb.questionnaire50.collection.v69';
  const q=id=>document.getElementById(id),copy=x=>JSON.parse(JSON.stringify(x));
  let state,context,epoch=0,restoring=false,timer,tail=Promise.resolve();
  const contexts=new Map();
  function status(message,c=context){if(c===context)q('response-status').textContent=message;}
  function enable(on){for(const n of q('response-form').querySelectorAll('input,textarea,button'))n.disabled=!on;}
  async function api(path,data){
    const r=await fetch(BASE+'/api/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json',...(state?{'X-EB-CSRF':state.csrf}:{})},
      ...(data===undefined?{}:{body:JSON.stringify(data),keepalive:true})});
    const value=await r.json();if(!r.ok){const e=Error(value.error||'暂时无法保存，请稍后重试。');e.status=r.status;throw e;}return value;
  }
  const boot=api('state').then(s=>{state=s;if(!s.participant_id||!s.consented){location.assign(BASE+'/');throw Error('请先确认参与说明。');}return s;});
  function enqueue(fn){const task=tail.then(fn);tail=task.catch(()=>{});return task;}
  const answerFor=c=>state.answers.find(a=>a.case_id===c.case.case_id);
  const draftFor=c=>state.drafts.find(a=>a.case_id===c.case.case_id);
  const viewFor=c=>state.views?.find(a=>a.case_id===c.case.case_id);
  const sameAnswer=(a,b)=>a&&b&&['decision','score','comfort_score','energy_score','vpp_score','reason'].every(k=>a[k]===b[k]);
  const localKey=c=>`eb:formal69:${state.participant_id}:${state.release_sha256}:${c.case.case_id}`;
  const pendingKey=c=>localKey(c)+':pending';
  const viewKey=c=>localKey(c)+':view';
  const bind=c=>({participant_id:state.participant_id,assignment_id:state.assignment_id,release_sha256:state.release_sha256,ui_revision:UI,case_id:c.case.case_id,case_sha256:c.row.sha256});
  function values(){const r={decision:q('response-form').querySelector('input[name=decision]:checked')?.value||null,reason:q('reason').value||null};for(const k of ['score','comfort_score','energy_score','vpp_score'])r[k]=q(k).value===''?null:Number(q(k).value);return r;}
  function setValues(response){q('response-form').reset();if(!response)return;for(const [key,value]of Object.entries(response)){if(key==='decision'){const n=q('response-form').querySelector(`input[name=decision][value="${value}"]`);if(n)n.checked=true;}else if(q(key))q(key).value=value??'';}}
  function presentation(c){return {fields:{family:q('family').textContent,request:q('vpp-request').textContent,changes:q('changes').textContent,impacts:q('impacts').textContent},schedule_seen:c.scheduleSeen,schedule_text:c.scheduleSeen?c.scheduleText:null,presented_at:c.presentedAt};}
  function remember(c){try{localStorage.setItem(localKey(c),JSON.stringify({response:c.response,presentation:c.presentation,base_answer_revision:c.answerRevision,case_sha256:c.row.sha256,ui_revision:UI,sequence:c.sequence}));}catch{status('本机暂时无法保留草稿，请保持页面打开并尽快提交。',c);}}
  function forget(c,sequence){if(c.sequence===sequence)try{localStorage.removeItem(localKey(c));}catch{}}
  function updateDraft(r){const i=state.drafts.findIndex(x=>x.case_id===r.case_id);if(i<0)state.drafts.push(r);else state.drafts[i]=r;}
  function rememberView(c){try{localStorage.setItem(viewKey(c),JSON.stringify({ui_revision:UI,case_sha256:c.row.sha256,schedule_seen:c.scheduleSeen,schedule_text:c.scheduleText}));}catch{status('查看记录暂时无法保存在本机，请保持联网。',c);}}
  function updateView(v,c){
    if(!v)return;state.views??=[];
    const i=state.views.findIndex(x=>x.case_id===v.case_id);if(i<0)state.views.push(v);else state.views[i]=v;
    if(c){c.scheduleSeen=c.scheduleSeen||v.schedule_seen;c.scheduleText=c.scheduleSeen?(v.schedule_text||c.scheduleText):null;c.viewDirty=c.scheduleSeen&&!v.schedule_seen;if(c.presentation){c.presentation.schedule_seen=c.scheduleSeen;c.presentation.schedule_text=c.scheduleText;}rememberView(c);}
  }
  function syncView(c){
    if(!c?.presentation)return Promise.resolve();const shown=copy(c.presentation);c.viewDirty=true;rememberView(c);
    return enqueue(async()=>{const r=await api('view',{...bind(c),presentation:shown});updateView(r.view,c);}).catch(e=>{status(e.message+' 查看记录仍保留在本机，联网后会重试。',c);throw e;});
  }
  function progress(){
    const n=state.answers.length;q('collection-progress').textContent=`第${state.round_number||1}轮 · 系统分配家庭 · 已提交 ${n}/${state.question_count}题${n===state.question_count?' · 本轮已完成':' · 草稿自动保存'}`;
    if(state.fixtures){document.querySelector('.badge').textContent='流程验证 · 不入正式数据';}
    const done=new Set(state.answers.map(x=>x.case_id));
    q('next-question').hidden=!context||!answerFor(context)||context.index.cases.every(x=>done.has(x.case_id));
    q('next-household').hidden=n!==state.question_count||(state.rounds?.length||1)>=context?.index.households_total;
  }
  function flush(c){
    if(!c||!c.dirty||!c.presentation)return Promise.resolve();
    const submitted={response:copy(c.response),presentation:copy(c.presentation),sequence:c.sequence};
    return enqueue(async()=>{
      const remote=draftFor(c);
      const r=await api('draft',{...bind(c),expected_version:remote?.version||0,expected_answer_revision:c.answerRevision,
                              response:submitted.response,presentation:submitted.presentation});
      updateDraft(r);updateView(r.view,c);forget(c,submitted.sequence);
      if(c.sequence===submitted.sequence){c.dirty=false;status('草稿已保存，尚未提交。',c);}
    }).catch(e=>{status(e.message+' 未提交内容仍保留在本机。',c);throw e;});
  }
  async function onCaseShown(c,p,row,index){
    const old=context;if(old?.dirty&&!old.submitting)flush(old).catch(()=>{});clearTimeout(timer);
    const turn=++epoch;restoring=true;enable(false);status('正在恢复进度…');
    try{
      await boot;if(turn!==epoch)return;
      let next=contexts.get(c.case_id);
      if(!next){next={case:c,row,index,presentedAt:new Date().toISOString(),scheduleSeen:false,scheduleText:null,dirty:false,sequence:0};contexts.set(c.case_id,next);}
      context=next;next.index=index;const saved=answerFor(next),draft=draftFor(next);next.answerRevision=saved?.revision||0;
      let response=next.dirty?next.response:draft?.response??saved?.response??null;
      let local,localView;
      try{local=JSON.parse(localStorage.getItem(localKey(next))||'null');}catch{}
      try{localView=JSON.parse(localStorage.getItem(viewKey(next))||'null');}catch{}
      if(localView&&(localView.ui_revision!==UI||localView.case_sha256!==row.sha256))localView=null;
      for(const shown of [viewFor(next),saved?.presentation,localView])if(shown?.schedule_seen){next.scheduleSeen=true;next.scheduleText=shown.schedule_text||next.scheduleText;}
      if(local&&local.ui_revision===UI&&local.case_sha256===row.sha256&&local.base_answer_revision===next.answerRevision){
        response=local.response;next.dirty=true;next.sequence=Math.max(next.sequence,local.sequence||0);
        if(local.presentation?.schedule_seen){next.scheduleSeen=true;next.scheduleText=local.presentation.schedule_text||next.scheduleText;}
      }
      setValues(response);next.response=values();next.presentation=presentation(next);
      enable(true);progress();
      status(local&&next.dirty?'已恢复本机未同步草稿，正在重试保存。':draft?.response?'已恢复草稿，尚未提交。':saved?`已恢复提交的答卷 · 回执 ${saved.receipt_id}。可修改后重交。`:'请评分并选择是否接受B方案。');
      if(next.scheduleSeen)status(q('response-status').textContent+' 本题曾展开完整排程，查看记录已恢复。');
      syncView(next).catch(()=>{});
      if(next.dirty)flush(next).catch(()=>{});
    }catch(e){status(e.message);}
    finally{if(turn===epoch)restoring=false;}
  }
  function changed(){
    if(restoring||!context||!state)return;
    const c=context;c.response=values();c.presentation=presentation(c);c.sequence++;c.dirty=true;remember(c);
    status('正在保存草稿…');clearTimeout(timer);timer=setTimeout(()=>flush(c).catch(()=>{}),500);
  }
  async function submit(){
    if(!context||restoring)return;const c=context;let response;
    try{response=root.EBSimple50.answer(values());}catch(e){status(e.message);return;}
    if(c.submitting)return;
    const saved=answerFor(c);
    if(saved&&sameAnswer(saved.response,response)&&Boolean(saved.presentation?.schedule_seen)===c.scheduleSeen){status('此答卷已保存 · 回执 '+saved.receipt_id);return;}
    c.submitting=true;enable(false);clearTimeout(timer);c.response=response;c.presentation=presentation(c);c.sequence++;c.dirty=true;remember(c);const sequence=c.sequence;
    status('正在提交…');
    try{
      await enqueue(async()=>{
        let pending;
        try{pending=JSON.parse(localStorage.getItem(pendingKey(c))||'null');}catch{}
        if(!pending||!sameAnswer(pending.response,response)||pending.release_sha256!==state.release_sha256){
          pending={...bind(c),expected_answer_revision:c.answerRevision,expected_draft_version:draftFor(c)?.version||0,
                   request_id:crypto.randomUUID(),response,presentation:c.presentation};
          localStorage.setItem(pendingKey(c),JSON.stringify(pending));
        }
        const r=await api('answers',pending);
        updateView(r.view,c);
        const item={...r,date:c.case.date};const i=state.answers.findIndex(x=>x.case_id===r.case_id);if(i<0)state.answers.push(item);else state.answers[i]=item;
        c.answerRevision=r.revision;c.dirty=false;forget(c,sequence);localStorage.removeItem(pendingKey(c));
        // A retry can acknowledge an earlier successful transaction; refresh its draft tombstone.
        if(r.duplicate){const fresh=await api('state');state.answers=fresh.answers;state.drafts=fresh.drafts;state.views=fresh.views;updateView(viewFor(c),c);}
        else if(r.draft_cleared)updateDraft({case_id:r.case_id,version:r.draft_version,base_answer_revision:r.revision,response:null,saved_at:r.saved_at});
        status('答卷已保存 · 回执 '+r.receipt_id+'。可修改后重新提交。',c);progress();
      });
    }catch(e){status(e.message+' 未确认的提交可稍后重试。',c);}
    finally{c.submitting=false;if(context===c)enable(true);}
  }
  async function revert(){
    if(!context||restoring||context.submitting)return;const c=context;clearTimeout(timer);enable(false);
    try{
      await enqueue(async()=>{const r=await api('revert',{...bind(c),expected_version:draftFor(c)?.version||0,expected_answer_revision:c.answerRevision});updateDraft(r);c.dirty=false;c.sequence++;localStorage.removeItem(localKey(c));localStorage.removeItem(pendingKey(c));if(context===c){restoring=true;setValues(answerFor(c)?.response||null);c.response=values();c.presentation=presentation(c);restoring=false;status(answerFor(c)?'已撤销未提交修改，恢复已提交答卷。':'草稿已清空。');}});
    }catch(e){status(e.message,c);}finally{if(context===c)enable(true);}
  }
  function observeSchedule(open){if(!context||!open)return;const c=context;c.scheduleSeen=true;c.scheduleText=q('plans').textContent;c.presentation=presentation(c);rememberView(c);if(c.dirty)remember(c);syncView(c).catch(()=>{});}
  q('response-form').addEventListener('input',changed);q('response-form').addEventListener('change',changed);
  q('next-question').addEventListener('click',()=>{const done=new Set(state.answers.map(x=>x.case_id));const next=context.index.cases.find(x=>!done.has(x.case_id));if(next){q('case-date').value=next.date;q('case-date').dispatchEvent(new Event('change',{bubbles:true}));q('family-heading').scrollIntoView({block:'start'});}});
  q('next-household').addEventListener('click',async()=>{
    const button=q('next-household');if(button.disabled)return;button.disabled=true;
    try{
      clearTimeout(timer);if(context?.viewDirty)await syncView(context);if(context?.dirty)await flush(context);await tail;
      await api('next-round',{participant_id:state.participant_id,assignment_id:state.assignment_id,release_sha256:state.release_sha256,ui_revision:UI});
      location.assign(BASE+'/form');
    }catch(e){status(e.message);button.disabled=false;}
  });
  q('collection-logout').addEventListener('click',async()=>{try{clearTimeout(timer);if(context?.viewDirty)await syncView(context);if(context?.dirty)await flush(context);await tail;await api('logout',{});location.assign(BASE+'/');}catch(e){status(e.message);}});
  let withdrawArmed=false;
  q('collection-withdraw').addEventListener('click',async()=>{
    if(!withdrawArmed){withdrawArmed=true;q('collection-withdraw').textContent='再次点击确认撤回';status('撤回后，此身份全部轮次的答卷将不再用于研究。再次点击确认。');return;}
    try{clearTimeout(timer);await tail;const r=await api('withdraw',{});enable(false);q('collection-progress').textContent='已撤回全部答卷';status('已撤回 · 回执 '+r.receipt_id);}catch(e){status(e.message);}
  });
  window.addEventListener('online',()=>{for(const c of contexts.values()){if(c.viewDirty)syncView(c).catch(()=>{});if(c.dirty)flush(c).catch(()=>{});}});
  root.EBCollection={onCaseShown,observeSchedule,submit,revert};
})(window);
