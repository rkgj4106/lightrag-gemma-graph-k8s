/* Local SVG graph viewer. No CDN, no external graph service. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const svg = el('network'), NS = 'http://www.w3.org/2000/svg';
  const palette = ['#2563eb','#059669','#d97706','#9333ea','#db2777','#0e7490','#475569'];
  let nodes = [], edges = [], nodeEls = new Map(), edgeEls = [];
  let layer, colors = new Map(), zoom = 1, offset = {x:0,y:0}, drag = null, focused = null;
  const create = (tag, attrs={}, text) => {
    const item = document.createElementNS(NS, tag);
    for (const [key,value] of Object.entries(attrs)) item.setAttribute(key,String(value));
    if (text !== undefined) item.textContent = text;
    return item;
  };
  const point = event => {
    const p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY;
    return p.matrixTransform(svg.getScreenCTM().inverse());
  };
  const world = p => ({x:(p.x-offset.x)/zoom,y:(p.y-offset.y)/zoom});
  const transform = () => { if(layer) layer.setAttribute('transform',`translate(${offset.x} ${offset.y}) scale(${zoom})`); };
  function place() {
    nodes.forEach((n,i) => {
      const angle = 2*Math.PI*i/Math.max(1,nodes.length);
      n.x = 500+260*Math.cos(angle); n.y = 310+240*Math.sin(angle);
    });
    // Bounded force layout; the small lab graph is drawn once, then draggable.
    for(let step=0;step<180;step++) {
      const delta = nodes.map(()=>({x:0,y:0}));
      for(let i=0;i<nodes.length;i++) for(let j=i+1;j<nodes.length;j++) {
        let dx=nodes[i].x-nodes[j].x, dy=nodes[i].y-nodes[j].y;
        const d2=Math.max(50,dx*dx+dy*dy), distance=Math.sqrt(d2), force=3800/d2;
        delta[i].x+=dx/distance*force; delta[i].y+=dy/distance*force;
        delta[j].x-=dx/distance*force; delta[j].y-=dy/distance*force;
      }
      for(const e of edges) {
        const dx=e.b.x-e.a.x, dy=e.b.y-e.a.y, distance=Math.max(1,Math.hypot(dx,dy));
        const force=(distance-150)*0.018;
        delta[e.a.index].x+=dx/distance*force; delta[e.a.index].y+=dy/distance*force;
        delta[e.b.index].x-=dx/distance*force; delta[e.b.index].y-=dy/distance*force;
      }
      nodes.forEach((n,i)=>{
        n.x+=Math.max(-8,Math.min(8,delta[i].x+(500-n.x)*0.003));
        n.y+=Math.max(-8,Math.min(8,delta[i].y+(310-n.y)*0.003));
      });
    }
  }
  function drawPositions() {
    for(const n of nodes) nodeEls.get(n.id).setAttribute('transform',`translate(${n.x} ${n.y})`);
    edges.forEach((e,i)=>{
      const {line,hit,label}=edgeEls[i];
      for(const item of [line,hit]) for(const [key,value] of Object.entries({x1:e.a.x,y1:e.a.y,x2:e.b.x,y2:e.b.y})) item.setAttribute(key,value);
      label.setAttribute('x',(e.a.x+e.b.x)/2);label.setAttribute('y',(e.a.y+e.b.y)/2-6);
    });
  }
  function fit() {
    if(!nodes.length)return;
    const minX=Math.min(...nodes.map(n=>n.x))-110,maxX=Math.max(...nodes.map(n=>n.x))+110;
    const minY=Math.min(...nodes.map(n=>n.y))-55,maxY=Math.max(...nodes.map(n=>n.y))+75;
    zoom=Math.min(2,880/Math.max(1,maxX-minX),540/Math.max(1,maxY-minY));
    offset={x:500-(minX+maxX)/2*zoom,y:310-(minY+maxY)/2*zoom};transform();
  }
  function highlight(selected) {
    const query=el('graphSearch').value.trim().toLocaleLowerCase();
    const near=new Set(selected?[selected]:[]);
    if(selected) for(const e of edges) if(e.a.id===selected||e.b.id===selected){near.add(e.a.id);near.add(e.b.id);}
    for(const n of nodes) {
      const g=nodeEls.get(n.id),match=!query||n.id.toLocaleLowerCase().includes(query);
      g.style.opacity=selected?(near.has(n.id)?'1':'0.18'):(match?'1':'0.16');
      g.querySelector('circle').setAttribute('stroke',n.id===selected?'#111827':'white');
      g.querySelector('circle').setAttribute('stroke-width',n.id===selected?5:2);
    }
    edges.forEach((e,i)=>{edgeEls[i].group.style.opacity=!selected||e.a.id===selected||e.b.id===selected?'1':'0.12';});
  }
  const details = (title,data) => {
    el('graphDetails').textContent=title+'\n\n설명: '+(data.description||'설명 없음')+
      '\n\n출처 문서: '+(data.file_path||'문서 경로 정보 없음')+
      (data.keywords?'\n\n관계 키워드: '+data.keywords:'');
  };
  function select(n) {focused=n.id;highlight(n.id);details(n.id+' · '+(n.entity_type||'Other'),n);}
  function render(data) {
    svg.replaceChildren();nodeEls=new Map();edgeEls=[];colors=new Map();focused=null;
    // The limit is explicit: all data remains available in the text list.
    nodes=data.nodes.slice(0,200).map((n,index)=>({...n,index}));
    const byId=new Map(nodes.map(n=>[n.id,n]));
    edges=data.edges.filter(e=>byId.has(e.source)&&byId.has(e.target)).map(e=>({...e,a:byId.get(e.source),b:byId.get(e.target)}));
    for(const n of nodes){const type=n.entity_type||'Other';if(!colors.has(type))colors.set(type,palette[colors.size%palette.length]);}
    layer=create('g');svg.append(layer);
    for(const e of edges) {
      const group=create('g'),line=create('line',{stroke:'#aab8cc','stroke-width':2});
      const hit=create('line',{stroke:'transparent','stroke-width':16,tabindex:0,role:'button','aria-label':`${e.source}와 ${e.target} 관계`});
      const short=String(e.keywords||'관계').split(',')[0];
      const label=create('text',{'font-size':11,fill:'#475569','text-anchor':'middle','pointer-events':'none','paint-order':'stroke',stroke:'white','stroke-width':4},short.length>14?short.slice(0,14)+'…':short);
      group.append(line,label,hit);group.style.cursor='pointer';
      const choose=()=>{focused=null;highlight(null);details(e.source+' — '+e.target,e);};
      hit.onclick=choose;hit.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();choose();}};
      group.append(create('title',{},e.description||short));layer.append(group);edgeEls.push({group,line,hit,label});
    }
    for(const n of nodes) {
      const g=create('g',{'data-node':n.id,tabindex:0,role:'button','aria-label':n.id});g.style.cursor='grab';
      g.append(create('circle',{r:19,fill:colors.get(n.entity_type||'Other'),stroke:'white','stroke-width':2}));
      g.append(create('text',{y:36,'text-anchor':'middle','font-size':13,fill:'#162137','paint-order':'stroke',stroke:'white','stroke-width':4},n.id));
      g.append(create('title',{},n.description||n.id));
      g.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(n);}};
      layer.append(g);nodeEls.set(n.id,g);
    }
    place();drawPositions();fit();highlight(null);
    el('legend').replaceChildren();
    for(const [type,color] of colors){const span=document.createElement('span');span.textContent='● '+type;span.style.color=color;el('legend').append(span);}
    el('graphStatus').textContent=`전체 개체 ${data.nodes.length}개 · 관계 ${data.edges.length}개`+
      (data.nodes.length>200?' / 그림에는 앞의 200개 개체와 그 사이 관계만 표시합니다.':'')+
      (nodes.length?' / 기본 LightRAG 그래프의 관계선에는 방향을 표시하지 않습니다.':' / 아직 그래프가 없습니다. 색인 로그를 확인하세요.');
    el('graphout').textContent=data.nodes.map(n=>`${n.id}: ${n.description||''}`).join('\n')+'\n\n'+data.edges.map(e=>`${e.source} — ${e.target}\n  ${e.description||''}`).join('\n');
  }
  svg.addEventListener('pointerdown',event=>{
    const target=event.target.closest('[data-node]');
    if(!target&&event.target!==svg)return; // relationship clicks retain their details
    const p=point(event), node=target?nodes.find(n=>n.id===target.getAttribute('data-node')):null;
    drag={node,start:p,last:p,moved:false};svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener('pointermove',event=>{
    if(!drag)return;const p=point(event);
    if(Math.hypot(p.x-drag.start.x,p.y-drag.start.y)>3)drag.moved=true;
    if(drag.node){const w=world(p);drag.node.x=w.x;drag.node.y=w.y;drawPositions();}
    else {offset.x+=p.x-drag.last.x;offset.y+=p.y-drag.last.y;transform();}
    drag.last=p;
  });
  svg.addEventListener('pointerup',()=>{
    if(!drag)return;
    if(!drag.moved){if(drag.node)select(drag.node);else {focused=null;highlight(null);}}
    drag=null;
  });
  svg.addEventListener('pointercancel',()=>{drag=null;});
  function zoomAt(factor,p={x:500,y:310}) {
    const before=world(p);zoom=Math.max(0.12,Math.min(6,zoom*factor));
    offset={x:p.x-before.x*zoom,y:p.y-before.y*zoom};transform();
  }
  svg.addEventListener('wheel',event=>{event.preventDefault();zoomAt(event.deltaY<0?1.12:1/1.12,point(event));},{passive:false});
  el('fit').onclick=fit;el('zoomIn').onclick=()=>zoomAt(1.25);el('zoomOut').onclick=()=>zoomAt(0.8);
  el('graphSearch').oninput=()=>{focused=null;highlight(null);};
  el('graph').onclick=async()=>{
    el('graph').disabled=true;el('graphStatus').textContent='그래프를 불러오는 중…';
    try{const response=await fetch('/api/graph');if(!response.ok)throw Error('그래프 조회 실패: '+response.status);render(await response.json());}
    catch(error){el('graphStatus').textContent=error.message;}
    finally{el('graph').disabled=false;}
  };
})();
