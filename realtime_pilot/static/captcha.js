"use strict";
// Only the server decides whether a challenge grants task admission.
window.EBCaptcha=(()=>{
 let busy=false;
 async function submit(api,payload,enabled){
  if(!enabled)return api('/api/paired',payload);
  if(busy)throw new Error('请先完成当前验证');
  busy=true;
  const dialog=document.getElementById('captcha-dialog'),form=document.getElementById('captcha-form'),input=document.getElementById('captcha-answer'),picture=document.getElementById('captcha-image'),message=document.getElementById('captcha-message'),refresh=document.getElementById('captcha-refresh'),confirm=document.getElementById('captcha-confirm'),cancel=document.getElementById('captcha-cancel');
  return new Promise((resolve,reject)=>{
   let challenge=null,closed=false,issuing=false,sending=false;
   function state(){refresh.disabled=issuing||sending;confirm.disabled=issuing||sending||!challenge;input.disabled=issuing||sending;cancel.disabled=sending;}
   function finish(error,job){if(closed)return;closed=true;busy=false;dialog.close();form.onsubmit=null;dialog.oncancel=null;refresh.onclick=null;cancel.onclick=null;error?reject(error):resolve(job);}
   async function renew(){
    if(issuing||sending||closed)return;issuing=true;challenge=null;input.value='';picture.removeAttribute('src');picture.hidden=true;message.textContent='正在准备验证码…';state();
    try{const c=await api('/api/captcha',{request_id:payload.request_id});if(closed)return;challenge=c;picture.src=c.image;picture.hidden=false;message.textContent='输入图中 6 位字符，不区分大小写。验证码 3 分钟内有效。';}
    catch(e){if(!closed)message.textContent=e.message;}
    finally{issuing=false;if(!closed){state();input.focus();}}
   }
   form.onsubmit=async e=>{
    e.preventDefault();if(sending||!challenge)return;sending=true;message.textContent='正在验证并提交…';state();
    try{const job=await api('/api/paired',{...payload,captcha:{id:challenge.id,answer:input.value}});finish(null,job);}
    catch(e){
     if(e.code==='captcha_invalid'){message.textContent=e.message;input.value='';}
     else if(e.name==='AbortError'){message.textContent='连接超时，可以再次提交同一次请求，不会重复生成。';}
     else{finish(e);}
    }finally{sending=false;if(!closed){state();input.focus();}}
   };
   cancel.onclick=()=>finish(new Error('已取消生成验证，家庭资料仍已保存。'));
   dialog.oncancel=e=>{e.preventDefault();if(!sending)cancel.click();};refresh.onclick=renew;
   dialog.showModal();renew();
  });
 }
 return {submit};
})();
