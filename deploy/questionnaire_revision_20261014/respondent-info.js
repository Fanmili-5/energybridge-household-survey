"use strict";
(function(root){
 const genders=new Set([null,'female','male','other','prefer_not_to_say']);
 function validate(value){
  if(!value||Object.keys(value).sort().join(',')!=='age_years,gender')throw Error('填写者资料字段无效。');
  const age=value.age_years;
  if(age!==null&&(!Number.isInteger(age)||age<1||age>120))throw Error('本人年龄须为1至120的整数；也可以留空。');
  if(!genders.has(value.gender))throw Error('请选择本人性别，或留空。');
  return {age_years:age,gender:value.gender};
 }
 function read(){
  const age=document.getElementById('respondent-age').value.trim();
  if(age!==''&&!/^\d+$/.test(age))throw Error('本人年龄请填写整数。');
  return validate({age_years:age===''?null:Number(age),gender:document.getElementById('respondent-gender').value||null});
 }
 root.EBRespondentInfo={read,validate};
 if(typeof module!=='undefined')module.exports=root.EBRespondentInfo;
})(typeof window!=='undefined'?window:globalThis);
