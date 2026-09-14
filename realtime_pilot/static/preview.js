document.addEventListener('DOMContentLoaded',()=>{
 const v=JSON.parse(document.getElementById('preview-data').textContent);
 EBView.render(document.getElementById('preview-plan'),v);
 EBView.outcomes(document.getElementById('preview-outcomes'),v);
 document.getElementById('preview-notice').textContent=v.notice;
});
