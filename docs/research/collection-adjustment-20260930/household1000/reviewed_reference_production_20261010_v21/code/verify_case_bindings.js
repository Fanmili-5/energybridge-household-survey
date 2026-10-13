'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
if(!global.crypto)Object.defineProperty(global,'crypto',{value:require('node:crypto').webcrypto});
async function main(){
const root=process.argv[2],index=JSON.parse(fs.readFileSync(path.join(root,'INDEX50.json'),'utf8'));let checked=0;
for(const h of index.households){
 const site=path.join(root,'households',h.household_id),api=require(path.join(site,'joint-view.js'));
 const page=fs.readFileSync(path.join(site,'index.html'),'utf8'),cases=JSON.parse(page.match(/id="joint-cases-data"[^>]*>(.*?)<\/script>/s)[1]);
 const hashes=JSON.parse(page.match(/id="source-hashes-data"[^>]*>(.*?)<\/script>/s)[1]);
 for(let i=0;i<cases.length;i++){await api.verify(cases[i],hashes[i]);checked++;}
}
assert.equal(checked,500);const result={status:'pass',case_bindings_verified:checked,human_answers:0,browser_answer_isolation_is_separate:true};
fs.writeFileSync(process.argv[3],JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
