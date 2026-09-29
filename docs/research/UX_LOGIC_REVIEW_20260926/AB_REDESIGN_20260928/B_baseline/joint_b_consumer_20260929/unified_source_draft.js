"use strict";
(function(root){
  const decisions=new Set(["accept","reject"]);
  const issueCategories=new Set(["household","schedule","missing_result","display","other"]);
  function score(value,name){
    if(value===null||value===undefined||value==="")return null;
    const n=Number(value);
    if(!Number.isFinite(n)||n<1||n>5||Math.abs(n*10-Math.round(n*10))>1e-8)
      throw Error(name+"须为 1–5 分，最多一位小数；信息不足请留空。");
    return n;
  }
  function buildAnswer(input){
    if(!decisions.has(input?.choice))throw Error("请选择同意或不同意。");
    const comment=String(input.comment??"").trim();
    if(!comment)throw Error("请简要说明最主要原因或缺少的信息。");
    if(comment.length>1000)throw Error("说明文字不能超过 1000 字。");
    return {decision:input.choice,
      decision_status:'answered',
      score:score(input.score,"整体评分"),comfort_score:score(input.comfort_score,"舒适评分"),
      energy_score:score(input.energy_score,"用电与费用评分"),vpp_score:score(input.vpp_score,"错峰安排评分"),
      comment};
  }
  function buildIssue(input){
    if(!issueCategories.has(input?.category))throw Error("请选择问题类别。");
    const description=String(input.description??"").trim();
    if(!description)throw Error("请简单描述遇到的问题。");
    if(description.length>2000)throw Error("问题描述不能超过 2000 字。");
    return {category:input.category,description};
  }
  root.EBSourceDraft={buildAnswer,buildIssue};
  if(typeof module!=="undefined")module.exports={buildAnswer,buildIssue};
})(typeof window!=="undefined"?window:globalThis);
