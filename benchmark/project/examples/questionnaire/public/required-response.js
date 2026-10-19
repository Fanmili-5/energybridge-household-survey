(function(root){
 'use strict';
 root.EBRequiredResponse=function(answer){
  if(!answer||!['accept','reject'].includes(answer.decision))throw Error('请选择接受或不接受B方案。');
  for(const key of ['score','comfort_score','energy_score','vpp_score']){
   const value=answer[key];
   if(typeof value!=='number'||!Number.isFinite(value)||value<1||value>5)throw Error('请填写全部四项评分（1—5分）。');
  }
  return answer;
 };
})(typeof window==='undefined'?globalThis:window);
