'use strict';
(async function(){
  const base='/household50-current',q=id=>document.getElementById(id);let state,busy=false,pending=null;
  async function api(path,data){const r=await fetch(base+'/api/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:{'Content-Type':'application/json',...(state?{'X-EB-CSRF':state.csrf}:{})},...(data===undefined?{}:{body:JSON.stringify(data)})});const v=await r.json();if(!r.ok)throw Error(v.error||'暂时无法进入，请重试。');return v;}
  function mode(){if(state.fixtures){q('collection-mode').textContent='流程验证';q('entry-status').textContent='独立测试环境，测试答卷不进入正式研究数据。';}}
  async function refresh(){state=await api('state');q('notice-text').textContent=state.notice;q('start').disabled=false;mode();try{pending=JSON.parse(sessionStorage.getItem('eb69:pending-recovery')||'null');}catch{}if(pending?.participant_id!==state.participant_id)pending=null;if(state.participant_id&&state.consented){q('start').textContent='继续填写';if(pending?.recovery_code)recovery(pending);}}
  function recovery(result){if(!result.recovery_code){location.assign(base+'/form');return;}q('recovery-code').value=result.recovery_code;q('recovery-panel').hidden=false;q('continue-link').href=base+'/form';q('entry-status').textContent='已分配家庭。保存恢复码后，进入问卷。';q('start').hidden=true;q('consent-label').hidden=true;}
  q('start').addEventListener('click',async()=>{if(busy)return;busy=true;q('start').disabled=true;try{
    if(state.participant_id&&state.consented){location.assign(base+'/form');return;}
    if(!q('entry-consent').checked)throw Error('请先阅读说明并勾选自愿参与。');
    const result=await api('start',{});if(result.recovery_code){pending=result;sessionStorage.setItem('eb69:pending-recovery',JSON.stringify(result));}
    await api('consent',{accept:true,understood_assigned_role:true,notice_version:state.notice_version});
    recovery(pending||result);
  }catch(e){q('entry-status').textContent=e.message;}finally{busy=false;q('start').disabled=false;}});
  q('recover-form').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;try{
    const result=await api('recover',{credential:q('credential').value.trim()});q('credential').value='';if(result.recovery_code){pending=result;sessionStorage.setItem('eb69:pending-recovery',JSON.stringify(result));}
    state=await api('state');if(state.consented)recovery(result);else{q('entry-status').textContent='身份已恢复，请确认参与说明后继续。';q('start').textContent='确认并继续';}
  }catch(e){q('entry-status').textContent=e.message;}finally{busy=false;}});
  q('copy-recovery').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(q('recovery-code').value);q('entry-status').textContent='恢复码已复制，请妥善保存。';}catch{q('recovery-code').select();q('entry-status').textContent='请复制已选中的恢复码。';}});
  try{await refresh();}catch(e){q('entry-status').textContent=e.message;}
})();
