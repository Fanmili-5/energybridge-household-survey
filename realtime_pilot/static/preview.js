document.addEventListener('DOMContentLoaded',()=>{
 const v=JSON.parse(document.getElementById('preview-data').textContent);
 // Historic example: make its missing cost explicit, never invent a value.
 if(!v.metrics.some(m=>/成本|费用|电费/.test(m.label)))v.metrics.splice(1,0,{label:'相对用电成本（非人民币）',original:'此示例未记录',proposal:'此示例未记录'});
 for(const p of v.temperature_chart?.periods||[])if(p.label!=='响应期间')v.metrics.push({label:p.label+'室温（'+p.time+'）',original:p.original,proposal:p.proposal});
 EBView.render(document.getElementById('preview-plan'),v);
 EBView.outcomes(document.getElementById('preview-outcomes'),v);
 document.getElementById('preview-notice').textContent='本示例比较到当天24:00，跨夜任务的后续用电未计入。相对用电成本不是人民币金额。';
});
