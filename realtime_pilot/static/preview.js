document.addEventListener('DOMContentLoaded',()=>{
 const v=JSON.parse(document.getElementById('preview-data').textContent);
 // This saved example has no cost or EV/tank observations; show its available outcomes only.
 v.service_rows=(v.service_rows||[]).filter(r=>!['original','proposal'].some(side=>/不据此判断|按原 EB 模型/.test(r[side])));
 for(const p of v.temperature_chart?.periods||[])if(p.label!=='响应期间')v.metrics.push({label:p.label+'室温（'+p.time+'）',original:p.original,proposal:p.proposal});
 EBView.render(document.getElementById('preview-plan'),v);
 EBView.outcomes(document.getElementById('preview-outcomes'),v);
 document.getElementById('preview-notice').textContent='本示例比较到当天24:00，跨夜任务的后续用电未计入。相对用电成本不是人民币金额。';
});
