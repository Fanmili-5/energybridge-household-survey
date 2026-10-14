'use strict';
// Read-only binding check through the shipped frontend's actual verifier.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
if(!global.crypto)Object.defineProperty(global,'crypto',{value:require('node:crypto').webcrypto});
async function main(){
 const root=path.resolve(process.argv[2]),manifest=JSON.parse(fs.readFileSync(path.join(root,'FORMAL_RELEASE.json'),'utf8'));let checked=0;
 for(const row of manifest.households){
  const site=path.join(root,'households',row.household_id),api=require(path.join(site,'joint-view.js'));
  const page=fs.readFileSync(path.join(site,'index.html'),'utf8');
  const cases=JSON.parse(page.match(/id="joint-cases-data"[^>]*>(.*?)<\/script>/s)[1]);
  const hashes=JSON.parse(page.match(/id="source-hashes-data"[^>]*>(.*?)<\/script>/s)[1]);
  assert.equal(cases.length,10);assert.equal(hashes.length,10);
  assert.deepEqual(hashes,row.case_hashes);
  for(let i=0;i<10;i++){await api.verify(cases[i],hashes[i]);checked++;}
  delete require.cache[require.resolve(path.join(site,'joint-view.js'))];
 }
 assert.equal(checked,manifest.households.length*10);
 console.log(JSON.stringify({passed:true,case_bindings_verified:checked,canonicalization:'shipped frontend sorted JSON.stringify',actual_browser_interaction:false,human_answers_generated:0}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
