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
