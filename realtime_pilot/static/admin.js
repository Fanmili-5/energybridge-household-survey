"use strict";
async function refreshAdmin(){
 const status=document.getElementById('admin-status'),button=document.getElementById('admin-refresh');button.disabled=true;
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
 try{
  const response=await fetch('/admin/api/admin/status',{credentials:'same-origin',signal:controller.signal});
  if(!response.ok)throw new Error(response.status===403||response.status===401?'请使用管理员账号登录。':'暂时无法读取状态，请稍后刷新。');
  const data=await response.json(),limits=data.limits;
  status.textContent=data.planning_enabled?'方案生成已开启':'方案生成已暂停';
  document.getElementById('admin-limits').textContent=`最多同时执行 ${limits.workers} 个任务，待处理任务上限 ${limits.pending_limit} 个；排队开始期限 ${limits.queue_wait_seconds} 秒，单个任务计算超时 ${limits.timeout_seconds} 秒。`;
  document.getElementById('admin-queue').textContent=`当前排队 ${data.tasks.queued} 个、计算中 ${data.tasks.running} 个；已创建管理员测试任务 ${data.tasks.admin_tests} 个。`;
  document.getElementById('admin-captcha').textContent=data.captcha_enabled?'参与者人机验证已启用。':'参与者人机验证尚未启用，需要配置验证码服务。';
 }catch(error){status.textContent=error.name==='AbortError'?'读取超时，请稍后刷新。':error.message;}
 finally{clearTimeout(timer);button.disabled=false;}
}
document.getElementById('admin-refresh').onclick=refreshAdmin;
refreshAdmin();

const reviewNames={open:'待查看',confirmed:'已确认问题',not_bug:'非故障',fixed:'已修复'};
const categoryNames={generation_failed:'生成失败',waiting:'等待太久',schedule:'安排不合理',display:'显示异常',other:'其他问题'};
let reportCursor=null,reportLoading=false;
async function adminRequest(path,body){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
 try{
  const response=await fetch('/admin/api/admin/'+path,{credentials:'same-origin',signal:controller.signal,...(body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
  if(!response.ok)throw Error('操作未完成（'+response.status+'），请检查登录状态后重试。');
  return await response.json();
 }finally{clearTimeout(timer);}
}
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
async function downloadDiagnostic(kind,id){
 const data=await adminRequest('diagnostics/'+kind+'/'+id);
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='diagnostic-'+id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function loadReports(more=false){
 if(reportLoading)return;reportLoading=true;
 const status=document.getElementById('reports-status'),list=document.getElementById('reports-list');
 document.getElementById('reports-more').disabled=true;document.getElementById('reports-refresh').disabled=true;document.getElementById('report-filter').disabled=true;
 status.textContent='正在读取…';
 try{
  const query=new URLSearchParams();if(document.getElementById('report-filter').value)query.set('status',document.getElementById('report-filter').value);if(more&&reportCursor)query.set('before',reportCursor);
  const data=await adminRequest('reports?'+query);if(!more)list.replaceChildren();
  for(const report of data.reports){
   const card=node('article','');card.className='report-card';
   card.append(node('h3',categoryNames[report.category]||report.category),node('p',(report.participant_name||'未填写昵称')+' · '+new Date(report.created_at*1000).toLocaleString()),node('p',(report.target_type==='case'?'案例编号：':'家庭资料编号：')+report.target_id),node('p','报告编号：'+report.id),node('p','报告时状态：'+report.reported_status),node('p',report.description));
   const select=node('select','');select.setAttribute('aria-label','核查状态');for(const [value,label] of Object.entries(reviewNames)){const option=node('option',label);option.value=value;select.append(option);}select.value=report.review_status;
   const note=node('textarea','');note.maxLength=2000;note.rows=2;note.placeholder='核查备注（选填）';note.setAttribute('aria-label','核查备注');
   const save=node('button','保存核查结果'),download=node('button','下载诊断记录'),feedback=node('p','');save.type=download.type='button';download.className='secondary';feedback.setAttribute('role','status');
   save.onclick=async()=>{save.disabled=true;try{await adminRequest('reports/'+report.id,{status:select.value,note:note.value});feedback.textContent='核查结果已保存。';note.value='';}catch(e){feedback.textContent=e.message;}finally{save.disabled=false;}};
   download.onclick=async()=>{download.disabled=true;try{await downloadDiagnostic(report.target_type,report.target_id);feedback.textContent='诊断记录已下载。';}catch(e){feedback.textContent=e.message;}finally{download.disabled=false;}};
   for(const item of report.review_history||[])card.append(node('p',`${new Date(item.at*1000).toLocaleString()} · ${reviewNames[item.status]} · ${item.note||'无备注'}`));
   card.append(select,note,save,download,feedback);list.append(card);
  }
  reportCursor=data.next_cursor;document.getElementById('reports-more').hidden=!reportCursor;status.textContent=list.children.length?'已显示 '+list.children.length+' 条报告。':'没有符合条件的问题报告。';
 }catch(e){status.textContent=e.message;}
 finally{reportLoading=false;document.getElementById('reports-more').disabled=false;document.getElementById('reports-refresh').disabled=false;document.getElementById('report-filter').disabled=false;}
}
document.getElementById('reports-refresh').onclick=()=>loadReports();
document.getElementById('report-filter').onchange=()=>loadReports();
document.getElementById('reports-more').onclick=()=>loadReports(true);
document.getElementById('diagnostic-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button'),status=document.getElementById('diagnostic-status');button.disabled=true;status.textContent='正在整理记录…';try{await downloadDiagnostic(document.getElementById('diagnostic-kind').value,document.getElementById('diagnostic-id').value.trim());status.textContent='诊断记录已下载。';}catch(ex){status.textContent=ex.message;}finally{button.disabled=false;}};
loadReports();
