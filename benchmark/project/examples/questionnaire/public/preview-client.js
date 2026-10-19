/* Transport for the unchanged v69 response form in a read-only materials preview.
 * No answers, drafts or identities are sent to a collection service.
 */
'use strict';
(function(root){
  const $=id=>document.getElementById(id);
  const keys=['decision','score','comfort_score','energy_score','vpp_score','reason'];
  let current=null,saved=null;
  const pending=()=>!current||current.outcome_status==='not_computed';
  const pendingMessage='资料预览：实际后果未计算，评价暂不可填写或提交；请不要猜测评分。没有保存正式答卷。';
  function raw(){
    return Object.fromEntries(keys.map(key=>[key,key==='decision' ? document.querySelector('input[name="decision"]:checked')?.value||null : $(key).value]));
  }
  function ready(){
    if(pending()){$('submit-answer').disabled=true;return;}
    try {root.EBSimple50.answer(raw());$('submit-answer').disabled=false;}
    catch {$('submit-answer').disabled=true;}
  }
  function fill(value){
    $('response-form').reset();
    for(const key of keys){
      if(key==='decision') document.querySelectorAll('input[name="decision"]').forEach(el=>{el.checked=value?.decision===el.value;});
      else $(key).value=value?.[key]??'';
    }
    ready();
  }
  root.EBCollection={
    onCaseShown(caseData){
      current=caseData;saved=null;fill(null);
      $('response-form').querySelectorAll('input,textarea,select,button').forEach(el=>{el.disabled=pending();});
      ready();
      $('response-status').textContent=pending()?pendingMessage:'资料预览：填写只在当前页面检查，不会提交到正式采集库。';
    },
    observeSchedule(){},
    revert(){fill(saved);$('response-status').textContent=pending()?pendingMessage:'已撤销本题未确认修改；没有写入正式答卷。';},
    submit(){
      if(pending())throw Error('OUTCOMES_NOT_COMPUTED: evaluation is unavailable in this preview');
      const response=root.EBSimple50.answer(raw());
      // In-memory only, scoped to this exact displayed case. Never a human label.
      saved={...response};
      $('response-status').textContent='本题填写检查通过；仅在当前页面暂存，未保存为正式答卷。';
      return {case_id:current.case_id,preview_only:true,formal_response_saved:false};
    }
  };
  document.addEventListener('DOMContentLoaded',()=>{
    $('response-form').addEventListener('input',ready);
    $('response-form').addEventListener('change',ready);
  });
})(window);
