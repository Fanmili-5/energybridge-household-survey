"""Disposable admin namespace/browser-storage isolation; no generation calls."""
import os,subprocess,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'realtime_pilot'))
from server import make_server
with tempfile.TemporaryDirectory() as root:
    server=make_server(0,root,disable_planning=True,admin_user='admin',local_captcha=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    code=r'''
    const {chromium}=require('playwright'),assert=require('assert');
    (async()=>{const origin=process.env.EB_ADMIN_TEST_ORIGIN,browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
    try{const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin!==origin)return route.abort();if(route.request().method==='POST')throw Error('No writes allowed in this admin UI test');return route.continue({headers:{...route.request().headers(),...(url.pathname.startsWith('/admin/')?{'X-EB-Authenticated-User':'admin'}:{})}});});
    await page.goto(origin+'/admin/');await page.waitForFunction(()=>document.getElementById('admin-status').textContent==='方案生成已暂停');
    await page.getByRole('link',{name:'进入问卷测试 →'}).click();await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.is_admin===true);
    assert.strictEqual(new URL(page.url()).pathname,'/admin/survey');assert.strictEqual(await page.evaluate(()=>schema.captcha_enabled),false);
    await page.evaluate(()=>{localStorage.setItem('eb:probe','public');writeBrowser(draftStorage,'eb:probe',{admin:true});});
    assert.strictEqual(await page.evaluate(()=>localStorage.getItem('eb:probe')),'public');
    assert.deepStrictEqual(await page.evaluate(()=>JSON.parse(localStorage.getItem('eb:admin:eb:probe'))),{admin:true});
    await page.goto(origin);await page.waitForFunction(()=>typeof schema!=='undefined'&&schema?.is_admin===false);
    assert.strictEqual(await page.evaluate(()=>schema.captcha_enabled),true);assert.strictEqual(await page.evaluate(()=>draftStorage.getItem('eb:probe')),'public');
    assert.deepStrictEqual(errors,[]);console.log('Admin page/API routing, public role, captcha exemption and draft isolation passed.');
    }finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
    '''
    try:subprocess.run(['node','-e',code],env={**os.environ,'EB_ADMIN_TEST_ORIGIN':f'http://127.0.0.1:{server.server_address[1]}'},check=True,timeout=60)
    finally:server.shutdown();server.server_close();server.store.pool.shutdown();server.store.db.close()
