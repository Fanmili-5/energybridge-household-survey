(function(root){
 'use strict';
 root.EBRequiredResponse=function(answer){
  if(!answer||!['accept','reject'].includes(answer.decision))throw Error('请选择接受或不接受B方案。');
  for(const key of ['score','comfort_score','energy_score','vpp_score']){
   const value=answer[key];
   if(!Number.isInteger(value)||value<0||value>5)throw Error('请完成四项评分，每项选择0—5分。');
  }
  return answer;
 };
})(typeof window==='undefined'?globalThis:window);
