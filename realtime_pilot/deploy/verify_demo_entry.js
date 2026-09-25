// Bundled assets and synthetic responses only: never creates a paid task.
process.chdir(require('path').resolve(__dirname,'..'));
const {chromium}=require('playwright'),fs=require('fs'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 try{
  const schema=JSON.parse(fs.readFileSync('ui_audit_20260911/members/schema.json'));
 schema.questionnaire_context={context_hash:'offline-browser-fixture',date:'2007-09-12',label:'9月12日 · 秋季',instruction:'兼容旧记录的显示测试。'};
  for(const width of [390,1365]){
   const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];
   let status=200,writes=0;page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(request.method()!=='GET'){writes++;return route.abort();}
    if(path==='/api/session')return status===200?route.fulfill({json:{...schema,collection_mode:'engineering',jobs:[],households:[]}}):route.fulfill({status,contentType:'text/html',body:'<html>Proxy error</html>'});
    const name=path==='/'?'index.html':path.slice(1);
    if(!['index.html','app.js','style.css','time-input.js','plan-view.js','plan-preview.html','preview.js'].includes(name))return route.abort();
    return route.fulfill({contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('static/'+name)});
   });
   await page.goto('http://127.0.0.1:8766/');
   await page.waitForFunction(()=>document.getElementById('collection-badge').textContent==='体验版');
   assert.strictEqual(await page.locator('a[href="/legacy"]').count(),0);
   await page.locator('.preview-link').click();await page.locator('#preview-plan .schedule-board').waitFor({state:'attached'});
   assert((await page.locator('.preview-note').innerText()).includes('用电安排示例'));
   assert.strictEqual(await page.locator('#preview-data').evaluate(node=>JSON.parse(node.textContent).has_changes),true);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.locator('header a').last().click();await page.locator('#wizard-nav').waitFor();
   for(const [code,message] of [[401,'页面会话已失效'],[429,'当前请求较多'],[502,'计算服务暂时不可用']]){
    status=code;await page.reload();await page.waitForFunction(text=>document.getElementById('error').textContent.includes(text),message);
   }
   assert.deepStrictEqual(errors,[]);assert.strictEqual(writes,0);await context.close();
  }
  console.log('Demo navigation, responsive preview and HTML proxy error checks passed; no API calls.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
