"use strict";
(async function(){
 const landing=window.EBFormalLanding,config=landing||window.EBFormalConfig;if(!config)return;
 const q=id=>document.getElementById(id);
 async function api(path,data){const response=await fetch(config.api_base+'/api/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-EB-CSRF':config.csrf},...(data===undefined?{}:{body:JSON.stringify(data)})});const value=await response.json();if(!response.ok)throw Error(value.error||'暂时无法完成，请稍后再试。');return value;}
 if(landing){
  q('claim-form').addEventListener('submit',async event=>{event.preventDefault();try{const result=await api('claim',{credential:q('credential').value.trim()});q('credential').value='';q('claim-status').textContent='已进入您的参与身份。';q('recovery-panel').hidden=false;q('recovery-code').value=result.recovery_code||'继续使用您已保存的恢复码';q('assigned-link').href=result.route;}catch(error){q('claim-status').textContent=error.message;}});
  return;
 }
 let state=null,restoring=false;
 function restore(){
  if(!state)return;
  const completed=state.answers.length;q('formal-progress').textContent=`参与编号：${state.participant_id} · 已提交 ${completed}/10 个日期。修改后重新提交会保留修订记录。`+(state.prior_release_answer_count?' 您有旧版问卷的记录，已保留；当前新版任务需要重新阅读并作答。':'');
  q('formal-consent-text').textContent=state.notice;q('formal-consent-controls').hidden=state.consented;
  q('joint-export').disabled=!state.consented;
  q('formal-consent-status').textContent=state.consented?'已确认自愿参与。':'确认参与说明后即可提交答卷。';
  const index=Number(q('joint-select').value),saved=state.answers.find(x=>x.case_index===index);
  if(saved){
   restoring=true;
   const radio=document.querySelector(`[name="source_decision"][value="${saved.feedback.decision}"]`);if(radio)radio.checked=true;
   for(const[name,id]of [['score','joint-score'],['comfort_score','joint-comfort-score'],['energy_score','joint-energy-score'],['vpp_score','joint-vpp-score']]){q(id).value=saved.feedback[name]??'';q(id).dispatchEvent(new Event('input',{bubbles:true}));}
   q('joint-comment').value=saved.feedback.comment;q('joint-status').textContent='此日期已有答卷，回执：'+saved.receipt_id+'。您可以修改后重新提交。';restoring=false;
  }
 }
 async function refresh(){state=await api('session');restore();}
 q('formal-consent-submit').addEventListener('click',async()=>{try{if(!q('formal-consent-accept').checked)throw Error('请先阅读并勾选参与说明。');await api('consent',{accept:true,understood_assigned_role:true,notice_version:state.notice_version});await refresh();}catch(error){q('formal-consent-status').textContent=error.message;}});
 let withdrawArmed=false;
 q('formal-withdraw').addEventListener('click',async()=>{if(!withdrawArmed){withdrawArmed=true;q('formal-withdraw').textContent='确认撤回全部答卷（再次点击）';q('formal-consent-status').textContent='撤回将排除本参与身份下的全部答卷。再次点击确认撤回，或退出此页取消。';return;}try{const result=await api('withdraw',{});q('formal-progress').textContent='已撤回全部答卷。回执：'+result.receipt_id;q('joint-export').disabled=true;q('formal-withdraw').disabled=true;}catch(error){q('formal-consent-status').textContent=error.message;}});
 q('formal-logout').addEventListener('click',async()=>{try{await api('logout',{});location.href=config.api_base;}catch(error){q('formal-consent-status').textContent=error.message;}});
 new MutationObserver(()=>restore()).observe(q('joint-date'),{childList:true,characterData:true,subtree:true});
 new MutationObserver(()=>{if(restoring)return;if(q('joint-status').textContent.startsWith('答卷已提交'))refresh().catch(error=>{q('formal-consent-status').textContent=error.message;});}).observe(q('joint-status'),{childList:true,characterData:true,subtree:true});
 try{await refresh();const last=state.answers[state.answers.length-1];if(last){q('respondent-age').value=last.respondent.age_years??'';q('respondent-gender').value=last.respondent.gender??'';}}catch(error){q('formal-consent-status').textContent=error.message;q('joint-export').disabled=true;}
})();
