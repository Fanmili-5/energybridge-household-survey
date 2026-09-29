"use strict";
const PROFILES = JSON.parse(document.getElementById("profile-data").textContent);
const SOURCE_SELECTION = JSON.parse(document.getElementById("source-selection-data").textContent);
let SOURCE_CASES = JSON.parse(document.getElementById("source-cases-data").textContent);
const COLLECTION_MODE = document.body.dataset.r72Collection === "true";
const $ = id => document.getElementById(id);
const make = (tag,text,cls) => { const x=document.createElement(tag); if(text!=null)x.textContent=String(text); if(cls)x.className=cls; return x; };
const deviceNames={ac:"空调",washer:"洗衣机",dryer:"烘干机",dishwasher:"洗碗机",electric_water_heater:"电热水器",home_ev:"电动车充电"};
const deviceName=id=>deviceNames[id]||id||"设备";
const zoneLabel=(zone,labels={})=>{const label=labels[zone]||zone;const name=({kitchen:"厨房",bathroom:"卫浴",corridor:"过道",living_hall:"起居厅",outdoor:"室外"}[label])||String(label||"").replace(/^natural_(\d+)$/,"自然间 $1");return name==="位置未提供"?"":name;};
const svgNS="http://www.w3.org/2000/svg";
function svg(tag,attributes={},textValue){const x=document.createElementNS(svgNS,tag);for(const [key,value] of Object.entries(attributes))x.setAttribute(key,String(value));if(textValue!=null)x.textContent=String(textValue);return x;}
let roles=Object.keys(SOURCE_CASES);
let role=roles[0],index=0,currentCase=null;
const drafts=new Map(),swaps=new Map();
const key=f=>`${f.artifact.role_id}|${f.artifact.date}|${f.artifact.source_action_sha256}`;
function clock(minute){if(!Number.isFinite(minute))return "时间未知";const day=Math.floor(minute/1440),value=((minute%1440)+1440)%1440;return `${day<0?"前日 ":day===1?"次日 ":day>1?`第 ${day+1} 日 `:""}${String(Math.floor(value/60)).padStart(2,"0")}:${String(value%60).padStart(2,"0")}`;}
function local(f,value){return value-f.artifact.day_index*1440;}
function addFact(box,label,value){const item=make("div",null,"home-fact");item.append(make("small",label),make("strong",value));box.append(item);}
function roomPicture(profile,geometry){
  const figure=document.querySelector(".home-figure");
  if(!geometry?.floors?.length){$("home-visual").replaceChildren();$("home-caption").textContent="";if(figure)figure.hidden=true;return;}
  if(figure)figure.hidden=false;
  const points=geometry.floors.flatMap(f=>f.points),minX=Math.min(...points.map(p=>p[0])),maxX=Math.max(...points.map(p=>p[0])),minY=Math.min(...points.map(p=>p[1])),maxY=Math.max(...points.map(p=>p[1]));
  const scale=Math.min(52,900/(maxX-minX),295/(maxY-minY));
  const xy=p=>[Math.round(55+(p[0]-minX)*scale),Math.round(49+(maxY-p[1])*scale)];
  const picture=svg("svg",{viewBox:"0 0 1010 410",role:"img","aria-label":"住宅布局示意"});
  const defs=svg("defs"),shadow=svg("filter",{id:"house-shadow",x:"-10%",y:"-10%",width:"120%",height:"140%"});shadow.append(svg("feDropShadow",{dx:0,dy:10,stdDeviation:8,"flood-color":"#2b4e3b","flood-opacity":.17}));defs.append(shadow);picture.append(defs);
  const fills={natural_1:"#edf4eb",natural_2:"#f2f0e9",corridor:"#faf8f0",kitchen:"#e9f1ee",bathroom:"#e5eef1"};
  const floorLayer=svg("g",{filter:"url(#house-shadow)"});
  for(const floor of geometry.floors){const polygon=floor.points.map(p=>xy(p).join(",")).join(" ");floorLayer.append(svg("polygon",{points:polygon,fill:geometry.owned_zones&&!geometry.owned_zones.includes(floor.zone)?"#e8e9e6":fills[floor.zone]||"#f6f8f3",stroke:"#d9e3da","stroke-width":1}));}
  picture.append(floorLayer);
  // Furniture is decorative; equipment is listed by source zone rather than invented coordinates.
  const zonePoints={};for(const floor of geometry.floors)(zonePoints[floor.zone]??=[]).push(...floor.points);
  const centroid={};for(const [zone,coordinates] of Object.entries(zonePoints)){const unique=[...new Map(coordinates.map(p=>[p.join(","),p])).values()];centroid[zone]=xy([unique.reduce((sum,p)=>sum+p[0],0)/unique.length,unique.reduce((sum,p)=>sum+p[1],0)/unique.length]);}
  function furniture(zone,kind){const point=centroid[zone];if(!point)return;const [x,y]=point;
    if(kind==="bed")picture.append(svg("rect",{x:x-41,y:y-30,width:82,height:53,rx:6,fill:"#f8faf7",stroke:"#b9cfc0","stroke-width":2}),svg("rect",{x:x-35,y:y-24,width:25,height:16,rx:4,fill:"#dbe8db"}));
    if(kind==="table")picture.append(svg("rect",{x:x-22,y:y-16,width:44,height:31,rx:5,fill:"#d9e7d8",stroke:"#adc8b6","stroke-width":2}));
    if(kind==="washer")picture.append(svg("rect",{x:x-19,y:y-20,width:38,height:39,rx:4,fill:"#fbfdfb",stroke:"#8fb4ae","stroke-width":2}),svg("circle",{cx:x,cy:y+3,r:12,fill:"#d4e8e8",stroke:"#8fb4ae","stroke-width":2}));
  }
  for(const item of profile.devices||[])if(item.device_class==="washer"&&item.installed===true&&item.owned!==false)furniture(item.zone,"washer");
  for(const item of geometry.decorative_furniture||[])furniture(item.zone,item.kind);
  const seen=new Set();for(const wall of geometry.walls){const ends=wall.points.map(p=>xy(p)),canonical=ends.map(p=>p.join(",")).sort().join("|");if(seen.has(canonical))continue;seen.add(canonical);picture.append(svg("line",{x1:ends[0][0],y1:ends[0][1],x2:ends[1][0],y2:ends[1][1],stroke:"#5c7369","stroke-width":8,"stroke-linecap":"square"}));}
  for(const opening of geometry.openings){const [a,b]=opening.points.map(p=>xy(p));picture.append(svg("line",{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:fills.corridor,"stroke-width":11}));
    if(opening.type==="window")picture.append(svg("line",{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:"#79b6c2","stroke-width":6,"stroke-linecap":"round"}));
    else{const length=Math.hypot(b[0]-a[0],b[1]-a[1]);const end=Math.abs(b[0]-a[0])>Math.abs(b[1]-a[1])?[a[0],a[1]-length]:[a[0]+length,a[1]];picture.append(svg("line",{x1:a[0],y1:a[1],x2:end[0],y2:end[1],stroke:"#bc9671","stroke-width":2}));picture.append(svg("path",{d:`M ${b[0]} ${b[1]} Q ${b[0]} ${end[1]} ${end[0]} ${end[1]}`,fill:"none",stroke:"#c9ad89","stroke-width":1.5,"stroke-dasharray":"4 4"}));}
  }
  const names=geometry.zone_labels||{};
  for(const [zone,point] of Object.entries(centroid)){const shift=zone==="bathroom"||zone==="kitchen"?37:44;picture.append(svg("text",{x:point[0],y:point[1]+shift,"text-anchor":"middle",fill:"#355a48","font-size":zone==="bathroom"?14:17,"font-weight":650},`${zoneLabel(zone,names)}${geometry.owned_zones&&!geometry.owned_zones.includes(zone)?" · 共用/其他范围":""}`));}
  $("home-visual").replaceChildren(picture);
  $("home-caption").textContent="住宅布局示意";
}
function renderInventory(profile,labels={}){
  const equipment=$("home-device-inventory");equipment.replaceChildren();
  const backgroundNames={冷藏设备:"cold_storage",网络待机:"network_standby",厨房设备:"cooking_main",照明:"lighting",活动插座:"activity_plugs"};
  const classes=Object.fromEntries(Object.entries(deviceNames).map(([id,name])=>[name,id]));classes["家用电动车充电"]="home_ev";
  const groups={adjustable:new Map(),other:new Map(),background:new Map()};
  const condition=item=>item.owned===false?"未持有":item.installed===false||item.installed===0?"未安装":item.accessible===false||item.usable===0?"暂不可用":item.modeled===false||item.controllable===false?"暂不可调":item.controllable===true||item.candidate===1?"":"调整条件未提供";
  for(const item of profile.devices||[]){
    if(item.owned===false||item.installed===false||item.installed===0)continue;
    const id=item.device_class||classes[item.device]||backgroundNames[item.device]||item.device,background=item.background===true||Object.values(backgroundNames).includes(id),state=condition(item);
    const section=background?groups.background:state?groups.other:groups.adjustable;
    if(!section.has(id))section.set(id,[]);section.get(id).push({item,state});
  }
  for(const [key,title] of [["adjustable","可调整电器"],["other","其他电器"]]){
    if(!groups[key].size)continue;
    equipment.append(make("h4",title,"equipment-section-title"));const grid=make("div",null,"equipment-grid");
    for(const [id,entries] of groups[key]){
      const card=make("article",null,"equipment-card");card.dataset.deviceClass=id;
      const heading=make("div",null,"equipment-card-heading");heading.append(window.EBView.icon(id),make("strong",entries[0].item.device||deviceName(id)));card.append(heading);
      for(const {item,state} of entries){const text=[zoneLabel(item.zone,labels),state].filter(Boolean).join(" · ");if(!text)continue;const position=make("span",text,"equipment-position");if(item.asset_id)position.dataset.assetId=item.asset_id;card.append(position);}
      grid.append(card);
    }
    equipment.append(grid);
  }
  if(groups.background.size){
    const details=make("section",null,"equipment-background");details.append(make("h4","其他日常用电","equipment-section-title"));
    const list=make("dl",null,"equipment-background-list");
    for(const [id,entries] of groups.background){const row=make("div",null,"equipment-background-row");row.dataset.deviceClass=id;
      row.append(make("dt",entries[0].item.device||deviceName(id)),make("dd",[...new Set(entries.map(({item,state})=>[zoneLabel(item.zone,labels),state!=="暂不可调"?state:""].filter(Boolean).join(" · ")).filter(Boolean))].join("、")));list.append(row);}
    if([...groups.background.values()].flat().every(({state})=>state==="暂不可调"))details.append(make("p","以下日常用电暂不可调。"));
    details.append(list);equipment.append(details);
  }
}
function renderHome(roleId){
  const bound=PROFILES[roleId],profile=bound?.profile,home=profile?.household;
  if(!home){$("home-intro").textContent="本户背景资料未交付。";return;}
  $("home-intro").textContent=[home.city,home.family_size==null?null:`${home.family_size} 位成员`,home.building_type].filter(Boolean).join(" · ");
  roomPicture(profile,bound.geometry);
  const facts=$("home-summary");facts.replaceChildren();
  if(home.building_type)addFact(facts,"住宅类型",home.building_type);
  if(home.natural_rooms_H7)addFact(facts,"房间",home.natural_rooms_H7);
  if(home.household_net_share_m2!=null)addFact(facts,"本户面积",`${home.household_net_share_m2} ㎡`);
  if(home.floor_position)addFact(facts,"所在楼层",home.floor_position);
  renderInventory(profile,bound.geometry?.zone_labels);

  $("home-targets").textContent="";
  const members=$("home-members");members.replaceChildren();
  for(const member of profile.members||[]){
    const card=make("article",null,"person-card"),copy=make("div",null,"person-copy");
    copy.append(make("strong",`${member.relationship} · ${member.age_years} 岁`));
    if(member.life_roles||member.routine)copy.append(make("span",[member.life_roles,member.routine].filter(Boolean).join(" · ")));
    if(member.weekday_home)copy.append(make("small",`工作日通常在家：${member.weekday_home}`));
    card.append(copy);members.append(card);
  }
  const attitude=$("home-attitudes");attitude.replaceChildren();
  const phrase=(n,high,mid,low)=>n==null?null:n>=4?high:n>=3?mid:low;
  const priority=[phrase(home.saving_importance_1_5,"很在意电费变化","会留意电费变化","电费不是主要顾虑"),phrase(home.comfort_importance_1_5,"很在意舒适度","希望兼顾舒适","舒适度可灵活调整"),phrase(home.conditional_grid_shift_importance_1_5,"愿意在条件合适时错峰","可以考虑错峰","不倾向为错峰改变安排")].filter(Boolean);
  const addAttitude=(title,text)=>{if(!text)return;const row=make("div",null,"attitude-item");row.append(make("strong",title),make("p",text));attitude.append(row);};
  addAttitude("用电取舍",[priority.join("；"),home.budget_explanation].filter(Boolean).join("。"));
  addAttitude("调整条件",[home.control_condition,home.notice_preference_hours==null?null:`希望提前 ${home.notice_preference_hours} 小时通知`].filter(Boolean).join("；"));
}
