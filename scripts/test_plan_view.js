// Pure rendering-model checks: no browser, EnergyPlus or API requests.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../realtime_pilot/static/plan-view.js'),'utf8'),context);
const t=context.window.EBView.timeline,plain=x=>JSON.parse(JSON.stringify(x));
const c={start_h:0,end_h:32};
assert.equal(t.clock(24,true),'次日 00:00');
assert.equal(t.clock(25+50/60,true),'次日 01:50');
assert.equal(t.clock(48,true),'第3天 00:00');
assert.deepEqual(plain(t.days(c)),[{day:0,start:0,end:24},{day:1,start:24,end:32}]);
assert(t.ticks(c).includes(24));
assert.deepEqual(plain(t.ticks(c)),[0,8,16,24,32]);
// Distinct dawn runs must never be shifted or merged across the daytime gap.
const spans=[{start_h:25.666667,end_h:25.833333,label:'0.243 kW'},{start_h:22,end_h:25.666667,label:'7.400 kW'},{start_h:0.166667,end_h:3.833333,label:'7.400 kW'},{start_h:3.833333,end_h:4,label:'0.243 kW'}];
const saved=JSON.stringify(spans),runs=plain(t.periods(spans,'home_ev',c));
assert.deepEqual(runs.map(s=>[s.start_h,s.end_h,s.label]),[[.166667,4,'充电'],[22,25.833333,'充电']]);
assert.equal(JSON.stringify(spans),saved,'Frozen source spans must remain unchanged');
assert.deepEqual(plain(t.visibleSpans(spans,c)).map(s=>s.start_h),[.166667,3.833333,22,25.666667]);
// Retain temperature changes, merge only identical adjacent settings.
const ac=[{start_h:22,end_h:24,label:'26℃'},{start_h:24,end_h:26,label:'25.5℃'},{start_h:26,end_h:32,label:'25.5℃'}];
assert.deepEqual(plain(t.periods(ac,'ac',c)).map(s=>[s.start_h,s.end_h,s.label]),[[22,24,'26℃'],[24,32,'25.5℃']]);
assert.deepEqual(plain(t.visibleSpans([{start_h:-1,end_h:2},{start_h:31,end_h:34},{start_h:34,end_h:36}],c)).map(s=>[s.start_h,s.end_h]),[[0,2],[31,32]]);
assert.deepEqual(plain(t.periods([],'washer',c)),[]);
// Legacy one-day results are not extended to invent a second day.
assert.deepEqual(plain(t.days({start_h:0,end_h:24})),[{day:0,start:0,end:24}]);
console.log('Timeline: absolute date order, midnight, clipping, immutable source, continuous tasks, temperature changes and legacy horizon passed.');



const placed=plain(t.labelLayout([{x:0,width:38},{x:145,width:38},{x:151,width:38},{x:250,width:68}],250));
assert.notEqual(placed[1].lane,placed[2].lane,'Adjacent boundary labels need separate tiers');
for(const p of placed){assert(p.left>=0);assert(p.left+p.width<=250);}
assert.equal(placed[0].x,0);assert.equal(placed.at(-1).x,250);
for(let i=0;i<placed.length;i++)for(let j=i+1;j<placed.length;j++)if(placed[i].lane===placed[j].lane)assert(placed[i].left+placed[i].width+6<=placed[j].left);
console.log('Endpoint labels: adjacent boundaries, midnight edges, no coordinate shifts passed.');

// Only the beginning/end of each continuous run are labelled; setting changes remain in periods().
assert.deepEqual(plain(t.runEndpoints(ac,c)),[22,32]);
assert.deepEqual(plain(t.runEndpoints(spans,c)),[.166667,4,22,25.833333]);
assert.deepEqual(plain(t.runEndpoints([{start_h:0,end_h:8},{start_h:18,end_h:19},{start_h:19,end_h:32}],c)),[0,8,18,32]);
assert.deepEqual(plain(t.runEndpoints([],c)),[]);
console.log('Continuous-run endpoints: thermal changes omitted, idle gaps and EV dawn runs preserved.');
