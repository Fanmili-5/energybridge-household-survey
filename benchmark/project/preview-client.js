/* Transport for the unchanged v69 response form in a read-only materials preview.
 * No answers, drafts or identities are sent to a collection service.
 */
'use strict';
(function(root){
  const $=id=>document.getElementById(id);
  const keys=['decision','score','comfort_score','energy_score','vpp_score','reason'];
  let current=null,saved=null;
  function raw(){
    return Object.fromEntries(keys.map(key=>[key,key==='decision' ? document.querySelector('input[name="decision"]:checked')?.value||null : $(key).matches('[data-score-options]')?$(key).querySelector('input:checked')?.value??'':$(key).value]));
  }
  function ready(){
    try {root.EBSimple50.answer(raw());$('submit-answer').disabled=false;}
    catch {$('submit-answer').disabled=true;}
  }
  function fill(value){
    $('response-form').reset();
    for(const key of keys){
      if(key==='decision') document.querySelectorAll('input[name="decision"]').forEach(el=>{el.checked=value?.decision===el.value;});
      else if($(key).matches('[data-score-options]'))$(key).querySelectorAll('input').forEach(el=>{el.checked=value?.[key]!=null&&Number(el.value)===value[key];});
      else $(key).value=value?.[key]??'';
    }
    ready();
  }
  root.EBCollection={
    onCaseShown(caseData){
      current=caseData;saved=null;fill(null);
      $('response-status').textContent='资料预览：后果未计算；可检查填写交互，内容不会提交到正式采集库。';
    },
    observeSchedule(){},
    revert(){fill(saved);$('response-status').textContent='已撤销本题未确认修改；没有写入正式答卷。';},
    submit(){
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
