'use strict';
// Use the actual frontend canonical JSON representation for browser bindings.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const release=process.argv[2];const index=JSON.parse(fs.readFileSync(path.join(release,'INDEX50.json'),'utf8'));
const sort=x=>Array.isArray(x)?x.map(sort):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,sort(x[k])])):x;
const hash=x=>crypto.createHash('sha256').update(JSON.stringify(sort(x))).digest('hex');
for(const row of index.households){const file=path.join(release,'households',row.household_id,'index.html');let page=fs.readFileSync(file,'utf8');const cases=JSON.parse(page.match(/id="joint-cases-data"[^>]*>(.*?)<\/script>/s)[1]);for(const c of cases){for(const [key,value] of [['profile_sha256',c.profile],['commands_sha256',c.commands],['A_plan_sha256',c.plans.A],['B_plan_sha256',c.plans.B],['vpp_sha256',c.vpp],['physical_sha256',c.physical]])c.bindings[key]=hash(value);}
 row.case_hashes=cases.map(hash);for(const [id,v] of [['joint-cases-data',cases],['source-hashes-data',row.case_hashes]]){const pattern=new RegExp('(<script[^>]+id="'+id+'"[^>]*>).*?(</script>)','s');page=page.replace(pattern,(_,a,b)=>a+JSON.stringify(v).replace(/</g,'\\u003c')+b);}fs.writeFileSync(file,page);}
index.browser_binding_canonicalization='actual live joint-b sorted JSON.stringify; IEEE754 numbers serialized by Node20.19';fs.writeFileSync(path.join(release,'INDEX50.json'),JSON.stringify(index));console.log(JSON.stringify({case_bindings:500,canonicalization:'actual browser representation'}));
