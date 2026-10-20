  // Display camera only. Room floors come directly from frozen usable_rect_m.
  function housingGeometry(p){
    const rooms=p.display_housing.rooms.filter(r=>Array.isArray(r.usable_rect_m));if(!rooms.length)return null;
    const xs=rooms.flatMap(r=>[r.usable_rect_m[0],r.usable_rect_m[2]]),ys=rooms.flatMap(r=>[r.usable_rect_m[1],r.usable_rect_m[3]]);
    const bounds=[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];
    const base=(x,y)=>[(x-bounds[0])-.40*(y-bounds[1]),.16*(x-bounds[0])+.88*(y-bounds[1])];
    const corners=[[bounds[0],bounds[1]],[bounds[2],bounds[1]],[bounds[2],bounds[3]],[bounds[0],bounds[3]]].map(([x,y])=>base(x,y));
    const xlo=Math.min(...corners.map(q=>q[0])),xhi=Math.max(...corners.map(q=>q[0])),yhi=Math.max(...corners.map(q=>q[1]));
    const scale=Math.min(440/(xhi-xlo),310/yhi),wall=22,margin=18;
    const project=(x,y,z=0)=>{const q=base(x,y);return [margin+(q[0]-xlo)*scale,margin+wall+q[1]*scale-z];};
    return {rooms,bounds,scale,wall,width:(xhi-xlo)*scale+margin*2,height:yhi*scale+margin*2+wall+9,project,
      floor:r=>{const[a,b,c,d]=r.usable_rect_m;return [[a,b],[c,b],[c,d],[a,d]].map(([x,y])=>project(x,y));}};
  }
  function roomUse(p,r){return !(r.using_household_ids||[]).includes(p.household_id)?'other':r.using_household_ids.length>1?'shared':'own';}
  const housingLabelCache=new Map();
  function annotationRect(x,y,w,h){return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]];}
  function annotationIntersects(a,b,gap=0){
    for(const poly of [a,b])for(let i=0;i<poly.length;i++){
      const u=poly[i],v=poly[(i+1)%poly.length],dx=v[0]-u[0],dy=v[1]-u[1],len=Math.hypot(dx,dy),axis=[-dy/len,dx/len];
      const aa=a.map(q=>q[0]*axis[0]+q[1]*axis[1]),bb=b.map(q=>q[0]*axis[0]+q[1]*axis[1]);
      if(Math.max(...aa)+gap<=Math.min(...bb)||Math.max(...bb)+gap<=Math.min(...aa))return false;
    }
    return true;
  }
  function annotationInside(box,poly,gap=0){
    return box.every(q=>poly.every((a,i)=>{const b=poly[(i+1)%poly.length],dx=b[0]-a[0],dy=b[1]-a[1];return (dx*(q[1]-a[1])-dy*(q[0]-a[0]))/Math.hypot(dx,dy)>=gap;}));
  }
  function annotationSegment(a,b){const dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1,nx=-dy/len*.6,ny=dx/len*.6;return [[a[0]-nx,a[1]-ny],[b[0]-nx,b[1]-ny],[b[0]+nx,b[1]+ny],[a[0]+nx,a[1]+ny]];}
  function annotationOptions(name,devices,area){
    const wraps=[[name]];
    if(name.startsWith('共用储物间'))wraps.push(['共用','储物间'+name.slice(5)]);
    else if(name.length>4)wraps.push([name.slice(0,2),name.slice(2)]);
    const options=[];
    for(const font of [15.5,14,12.5])for(const lines of wraps)for(const size of [22,20,18])for(const columns of devices.length>1?[devices.length,1]:[1]){
      const tile=size+4,cell=tile+(devices.some(d=>d.count>1)?17:0),lineHeight=font*1.4;
      const titleWidth=Math.max(...lines.map(s=>[...s].reduce((n,ch)=>n+(/[\u3000-\uffff]/.test(ch)?1:.65),0)))*font+4;
      const iconWidth=devices.length?Math.min(columns,devices.length)*cell+(Math.min(columns,devices.length)-1)*4:0;
      const iconHeight=devices.length?Math.ceil(devices.length/columns)*tile+(Math.ceil(devices.length/columns)-1)*4:0;
      const core={font,lines,size,tile,cell,columns,lineHeight,titleHeight:lines.length*lineHeight,
        w:Math.max(titleWidth,iconWidth)+4,h:lines.length*lineHeight+(devices.length?5+iconHeight:0)+4};
      if(!devices.length)options.push({...core,area,showArea:true,w:Math.max(core.w,[...area].length*7+8),h:core.h+15});
      options.push(core);
      if(!devices.length)break;
    }
    return options;
  }
  function annotationParts(option,x,y,shear=0){
    const {w,h,font,lines,lineHeight,titleHeight,devices,tile,cell,columns}=option,parts=[];
    const shift=cy=>shear*(cy-y-h/2);
    for(const[i,text]of lines.entries()){
      const cy=y+2+(i+.5)*lineHeight,tw=[...text].reduce((n,ch)=>n+(/[\u3000-\uffff]/.test(ch)?1:.65),0)*font+4;
      parts.push(annotationRect(x+w/2+shift(cy)-tw/2,cy-font*.7,tw,font*1.4));
    }
    for(const[i,device]of devices.entries()){
      const count=Math.min(columns,devices.length-i+i%columns),rowWidth=count*cell+(count-1)*4;
      const yy=y+2+titleHeight+5+Math.floor(i/columns)*(tile+4),xx=x+(w-rowWidth)/2+(i%columns)*(cell+4)+shift(yy+tile/2);
      parts.push(annotationRect(xx,yy,tile,tile));
      if(device.count>1)parts.push(annotationRect(xx+tile+1,yy-1,16,13));
    }
    if(option.showArea){const cy=y+h-8,tw=[...option.area].length*7+2;parts.push(annotationRect(x+w/2+shift(cy)-tw/2,cy-7.5,tw,15));}
    return parts;
  }
  function housingAnnotationPlan(p,g,wallPolygons){
    const key=JSON.stringify([p.household_id,p.display_housing.rooms,p.devices]);if(housingLabelCache.has(key))return housingLabelCache.get(key);
    const floors=g.rooms.map(r=>({id:r.room_id,points:g.floor(r)})),labels=[],pending=[];
    for(const r of g.rooms.filter(r=>roomUse(p,r)!=='other')){
      const poly=g.floor(r),center=[0,1].map(axis=>poly.reduce((s,q)=>s+q[axis],0)/4),groups=new Map();
      for(const d of displayDevices(p).filter(v=>v.room_id===r.room_id)){const title=deviceName(d),item=groups.get(title)||{title,count:0};item.count++;groups.set(title,item);}
      const devices=[...groups.values()],name=room(r.room_id),area=`${num(r.usable_area_m2,1)}㎡${roomUse(p,r)==='shared'?' · 共用':''}`;
      const item={id:r.room_id,name,area,devices,center,poly},options=annotationOptions(name,devices,area);
      const xs=poly.map(q=>q[0]),ys=poly.map(q=>q[1]),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
      let placed;
      for(const option of options){
        const candidates=[];
        for(const shear of [0,-.4/.88])for(let yy=minY+2;yy+option.h<=maxY-2;yy+=4)for(let xx=minX-option.w/2;xx<maxX;xx+=4){
          const parts=annotationParts({...option,devices},xx,yy,shear);
          if(parts.some(box=>!annotationInside(box,poly,2.5)||wallPolygons.some(w=>annotationIntersects(box,w,2.5))))continue;
          candidates.push({x:xx,y:yy,shear,score:Math.hypot(xx+option.w/2-center[0],yy+option.h/2-center[1])+Math.abs(shear)*2});
        }
        if(candidates.length){const best=candidates.sort((a,b)=>a.score-b.score)[0];placed={...item,...option,...best,placement:'inside'};break;}
      }
      if(placed)labels.push(placed);else pending.push(item);
    }
    // Labels that cannot fit without touching walls use empty space in the same SVG.
    // The source floor polygons, camera, wall geometry and viewBox are unchanged.
    for(const item of pending.sort((a,b)=>b.devices.length-a.devices.length)){
      const anchors=[],xs=item.poly.map(q=>q[0]),ys=item.poly.map(q=>q[1]);
      for(let yy=Math.min(...ys)+4;yy<Math.max(...ys)-4;yy+=6)for(let xx=Math.min(...xs)+4;xx<Math.max(...xs)-4;xx+=6){
        const dot=annotationRect(xx-2.2,yy-2.2,4.4,4.4);
        if(annotationInside(dot,item.poly,2)&&!wallPolygons.some(w=>annotationIntersects(dot,w,1.5)))anchors.push([xx,yy]);
      }
      // Very shallow corridors can be covered by the unchanged raised wall faces.
      // Keep their marker on their own floor centerline, never on an adjacent edge.
      if(!anchors.length)for(const t of [.15,.35,.5,.65,.85]){
        const a=item.poly[0],b=item.poly[1],c=item.poly[2],d=item.poly[3];
        anchors.push([(a[0]+d[0])*.5*(1-t)+(b[0]+c[0])*.5*t,(a[1]+d[1])*.5*(1-t)+(b[1]+c[1])*.5*t]);
      }
      const options=annotationOptions(item.name,item.devices,item.area).filter(o=>!o.showArea&&o.font>=14&&o.size===20),candidates=[];
      for(const option of options)for(let yy=4;yy+option.h<=g.height-4;yy+=4)for(let xx=4;xx+option.w<=g.width-4;xx+=4){
        const box=annotationRect(xx,yy,option.w,option.h);
        if(floors.some(f=>annotationIntersects(box,f.points,4))||wallPolygons.some(w=>annotationIntersects(box,w,4))||labels.some(n=>n.placement==='callout'&&(annotationIntersects(box,annotationRect(n.x,n.y,n.w,n.h),6)||annotationIntersects(box,annotationSegment(n.tail,n.anchor),2))))continue;
        const center=[xx+option.w/2,yy+option.h/2];let anchor,distance=Infinity;
        for(const q of anchors){const d=Math.hypot(q[0]-center[0],q[1]-center[1]);if(d<distance){distance=d;anchor=q;}}
        const tail=[Math.max(xx,Math.min(xx+option.w,anchor[0])),Math.max(yy,Math.min(yy+option.h,anchor[1]))];
        const leader=annotationSegment(tail,anchor);
        if(labels.some(n=>annotationParts(n,n.x,n.y,n.shear||0).some(part=>annotationIntersects(leader,part,2))))continue;
        let crossings=0;
        for(const f of floors.filter(f=>f.id!==item.id))for(let k=1;k<10;k++){const q=[tail[0]+(anchor[0]-tail[0])*k/10,tail[1]+(anchor[1]-tail[1])*k/10];if(annotationInside([q],f.points)){crossings++;break;}}
        candidates.push({...item,...option,x:xx,y:yy,placement:'callout',anchor,tail,score:distance+crossings*1000+(15.5-option.font)*12});
      }
      if(!candidates.length)throw new Error('No clear housing label position: '+p.household_id+'/'+item.id);
      labels.push(candidates.sort((a,b)=>a.score-b.score)[0]);
    }
    housingLabelCache.set(key,labels);return labels;
  }
  function housingDrawing(p,variant='detail'){
    const g=housingGeometry(p);if(!g)return m('p','未提供可绘制的房间位置。','effect-detail');
    const {rooms,project,wall,width,height}=g,id='cutaway-'+variant+'-'+p.household_id.replace(/[^a-zA-Z0-9-]/g,'');
    const pts=values=>values.map(q=>q.map(v=>Number(v.toFixed(3))).join(',')).join(' ');
    const poly=(p,attrs={},cls='')=>m('polygon',null,cls,[],{points:pts(p),...attrs});
    const line=(a,b,attrs)=>m('line',null,'',[],{x1:a[0],y1:a[1],x2:b[0],y2:b[1],...attrs});
    const palettes={own:['#f0f6e9','#deebd2'],shared:['#fffef9','#f0f4e8'],other:['#f1f4ee','#e7ece2']};
    const defs=m('defs',null,'',[
      m('filter',null,'',[m('feGaussianBlur',null,'',[],{stdDeviation:2.5})],{id:id+'-shadow',x:'-15%',y:'-25%',width:'140%',height:'170%'}),
      ...Object.entries(palettes).map(([key,colors])=>m('linearGradient',null,'',[
        m('stop',null,'',[],{offset:'0%','stop-color':colors[0]}),m('stop',null,'',[],{offset:'100%','stop-color':colors[1]})
      ],{id:id+'-'+key,x1:'0%',y1:'0%',x2:'15%',y2:'100%'}))
    ]);
    const[a,b,c,d]=g.bounds,base=[[a,b],[c,b],[c,d],[a,d]].map(([x,y])=>project(x,y));
    const shadow=poly(base.map(([x,y])=>[x+3,y+9]),{fill:'#607456',opacity:.15,filter:`url(#${id}-shadow)`});
    const slab=[poly([base[1],base[2],[base[2][0],base[2][1]+6],[base[1][0],base[1][1]+6]],{fill:'#a9bba0'}),
      poly([base[2],base[3],[base[3][0],base[3][1]+6],[base[2][0],base[2][1]+6]],{fill:'#c1ceb7'}),poly(base,{fill:'#e0e8d8',stroke:'#b3c2a8','stroke-width':.8})];
    const floors=rooms.map(r=>poly(g.floor(r),{fill:`url(#${id}-${roomUse(p,r)})`,stroke:roomUse(p,r)==='other'?'#cbd6c1':'#9daf91','stroke-width':.9,
      'data-room-id':r.room_id,'data-source-rect':r.usable_rect_m.join(','),'data-room-use':roomUse(p,r)},'model-room-floor'));
    const walls=[];
    const ordered=[...rooms].sort((r,s)=>{const center=t=>project((t.usable_rect_m[0]+t.usable_rect_m[2])/2,(t.usable_rect_m[1]+t.usable_rect_m[3])/2)[1];return center(r)-center(s);});
    for(const r of ordered){
      const[x1,y1,x2,y2]=r.usable_rect_m,other=roomUse(p,r)==='other';
      for(const[u,v,h]of [[ [x1,y1],[x2,y1],wall],[[x1,y1],[x1,y2],wall],[[x2,y1],[x2,y2],5],[[x1,y2],[x2,y2],5]]){
        const A=project(...u),B=project(...v),C=project(...v,h),D=project(...u,h),vertical=u[0]===v[0];
        walls.push(poly([A,B,C,D],{fill:other?'#e7ede1':vertical?'#dce5d3':'#f9fbf4',stroke:other?'#c3d0b8':'#9bad8e','stroke-width':.75}));
        walls.push(line(D,C,{stroke:other?'#c6d2bc':'#aabd9a','stroke-width':2.1,'stroke-linecap':'round'}));
        if(!other&&h===wall)walls.push(line(A,D,{stroke:'#a1b191','stroke-width':.7}));
      }
    }
    const wallPolygons=walls.filter(n=>n.tag==='polygon').map(n=>n.attrs.points.split(' ').map(s=>s.split(',').map(Number))),plan=housingAnnotationPlan(p,g,wallPolygons),labels=[];
    for(const item of plan){
      const {x,y,w,h,font,lines,lineHeight,titleHeight,devices,tile,size,cell,columns,name,area}=item;
      const shift=cy=>(item.shear||0)*(cy-y-h/2);
      const children=[m('title',`${name} · ${area}${devices.length?'；'+devices.map(t=>t.title+(t.count>1?'×'+t.count:'')).join('、'):''}`)];
      if(item.placement==='callout'){
        children.push(line(item.tail,item.anchor,{stroke:'#769064','stroke-width':1.05,'stroke-linecap':'round','data-room-connector':item.id}));
        children.push(m('circle',null,'',[],{cx:item.anchor[0],cy:item.anchor[1],r:2,fill:'#668657'}));
        children.push(m('rect',null,'cutaway-callout',[],{x,y,width:w,height:h,rx:5,fill:'#fbfcf8',stroke:'#d5dfcc','stroke-width':.7}));
      }
      for(const[i,text]of lines.entries()){const cy=y+2+(i+.5)*lineHeight;children.push(m('text',text,'cutaway-room-title',[],{x:x+w/2+shift(cy),y:cy,'font-size':font,'dominant-baseline':'central','text-anchor':'middle',fill:'#34523b','font-weight':550,'paint-order':'stroke',stroke:'#fbfcf7','stroke-width':2.6,'stroke-linejoin':'round'}));}
      if(item.showArea)children.push(m('text',item.area,'cutaway-room-area',[],{x:x+w/2+shift(y+h-8),y:y+h-8,'text-anchor':'middle','dominant-baseline':'central','font-size':11,fill:'#617658'}));
      for(const[i,device]of devices.entries()){
        const count=Math.min(columns,devices.length-i+i%columns),rowWidth=count*cell+(count-1)*4;
        const yy=y+2+titleHeight+5+Math.floor(i/columns)*(tile+4),xx=x+(w-rowWidth)/2+(i%columns)*(cell+4)+shift(yy+tile/2);
        children.push(m('rect',null,'cutaway-icon-tile',[],{x:xx,y:yy,width:tile,height:tile,rx:5,fill:'#fffefb',stroke:'#b8c9ab','stroke-width':.8}));
        const icon=iconNode(device.title);icon.cls='model-appliance-icon';icon.attrs={...icon.attrs,x:xx+2,y:yy+2,width:size,height:size,stroke:'#4f7044','stroke-width':1.6};children.push(icon);
        if(device.count>1)children.push(m('text','×'+device.count,'cutaway-device-count',[],{x:xx+tile+2,y:yy+7,'font-size':10,fill:'#3f6036','paint-order':'stroke',stroke:'#fffefb','stroke-width':2}));
      }
      labels.push(m('g',null,'cutaway-room-label',children,{'data-room-id':item.id,'data-label-placement':item.placement,'data-label-box':[x,y,w,h].join(',')}));
    }
    const others=rooms.filter(r=>roomUse(p,r)==='other');
    if(others.length){
      const centers=others.map(r=>project((r.usable_rect_m[0]+r.usable_rect_m[2])/2,(r.usable_rect_m[1]+r.usable_rect_m[3])/2));
      labels.push(m('text','其他住户','cutaway-other-label',[],{x:centers.reduce((s,q)=>s+q[0],0)/centers.length,y:centers.reduce((s,q)=>s+q[1],0)/centers.length+4,
        'text-anchor':'middle','font-size':12,fill:'#7b8c70','paint-order':'stroke',stroke:'#edf2e7','stroke-width':3,'stroke-linejoin':'round'}));
    }
    return m('svg',null,'house-cutaway',[
      m('title','房屋立体剖面示意；房间源坐标与相对面积不变，墙高及设备具体位置仅作示意'),defs,shadow,...slab,...floors,...walls,...labels
    ],{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':'房屋立体剖面示意，标注本户与共用房间名称和已配设备','data-layout-source':'frozen_usable_rect_m','data-projection':'axonometric-cutaway'});
  }
  function housePicture(p){
    const original=legacyHousePicture(p);if(original.tag!=='figure')return original;
    return {...original,children:original.children.map(n=>n.cls==='house-cutaway'?housingDrawing(p,'detail'):n.tag==='figcaption'?{...n,text:'布局取自模型；墙高和设备具体位置仅作示意。'}:n.cls==='house-figure-title'?{...n,children:n.children.map(t=>t.tag==='h3'?{...t,text:'房屋与设备剖面示意'}:t)}:n)};
  }
