// A deterministic original constellation layout. Positions are display geometry, not learning scores.
export function createAtlas(canvas,data,onSelect){
 const ctx=canvas.getContext('2d'),subjects=[...new Set(data.nodes.map(n=>n.subject))],palette=['#476b68','#ae6347','#9a8555','#6d7189','#638655','#997584','#588c91','#987149'];
 const points=new Map(),golden=Math.PI*(3-Math.sqrt(5));
 subjects.forEach((subject,index)=>{const group=data.nodes.filter(n=>n.subject===subject),angle=index/subjects.length*Math.PI*2-.8,cx=500+Math.cos(angle)*320,cy=235+Math.sin(angle)*145;
  group.forEach((n,i)=>{const r=Math.sqrt((i+.5)/group.length)*Math.min(115,40+Math.sqrt(group.length)*3);points.set(n.id,{...n,x:cx+Math.cos(i*golden)*r,y:cy+Math.sin(i*golden)*r*.76,color:palette[index]});});});
 let route=new Set(),subject='',zoom=1,pan={x:0,y:0},drag=null,hover=null,w=1,h=1;
 function project(p){const s=Math.min(w/1000,h/470)*zoom;return{x:w/2+(p.x-500)*s+pan.x,y:h/2+(p.y-235)*s+pan.y};}
 function draw(){w=canvas.clientWidth;h=canvas.clientHeight;if(!w||!h)return;const dpr=devicePixelRatio||1;canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  for(const edge of data.edges){const a=points.get(edge.from),b=points.get(edge.to),lit=route.has(a.id)&&route.has(b.id),A=project(a),B=project(b);ctx.beginPath();ctx.moveTo(A.x,A.y);ctx.lineTo(B.x,B.y);ctx.strokeStyle=lit?'#b94c2e':'#6e8170';ctx.globalAlpha=lit?.65:.035;ctx.lineWidth=lit?1.2:.6;ctx.stroke();}
  ctx.globalAlpha=1;
  for(const n of points.values()){const p=project(n),lit=route.has(n.id);ctx.globalAlpha=subject&&n.subject!==subject&&!lit?.12:lit?1:.72;ctx.beginPath();ctx.arc(p.x,p.y,lit?3.1:1.55,0,Math.PI*2);ctx.fillStyle=lit?'#b94c2e':n.color;ctx.fill();}
  ctx.globalAlpha=1;ctx.font='9px sans-serif';ctx.fillStyle='#526153';subjects.forEach((s,i)=>{const p=project({x:500+Math.cos(i/subjects.length*Math.PI*2-.8)*320,y:235+Math.sin(i/subjects.length*Math.PI*2-.8)*145+Math.min(115,40+Math.sqrt(data.nodes.filter(n=>n.subject===s).length)*3)*.85+12});ctx.textAlign='center';const tw=ctx.measureText(s).width;ctx.fillStyle='rgba(238,240,229,.92)';ctx.fillRect(p.x-tw/2-4,p.y-9,tw+8,12);ctx.fillStyle='#526153';ctx.fillText(s,p.x,p.y);});
  if(hover){const p=project(hover);ctx.beginPath();ctx.arc(p.x,p.y,6,0,Math.PI*2);ctx.strokeStyle='#25382e';ctx.stroke();}
 }
 function hit(x,y){let best=null,distance=12;for(const n of points.values()){const p=project(n),d=Math.hypot(x-p.x,y-p.y);if(d<distance){best=n;distance=d;}}return best;}
 canvas.onpointerdown=e=>{drag={x:e.offsetX,y:e.offsetY,pan:{...pan},moved:false};canvas.setPointerCapture(e.pointerId);};
 canvas.onpointermove=e=>{if(drag){const dx=e.offsetX-drag.x,dy=e.offsetY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;pan={x:drag.pan.x+dx,y:drag.pan.y+dy};}else{hover=hit(e.offsetX,e.offsetY);canvas.title=hover?.name||'Drag to explore. Select a concept, or use the accessible curriculum cards below.';}draw();};
 canvas.onpointerup=e=>{if(drag&&!drag.moved){const n=hit(e.offsetX,e.offsetY);if(n)onSelect(n);}drag=null;};
 canvas.onpointerleave=()=>{hover=null;draw();};new ResizeObserver(draw).observe(canvas);
 return{setRoute(p){route=new Set((p?.nodes||[]).map(n=>n.id));draw();},setSubject(s){subject=s;draw();},zoom(delta){zoom=Math.max(.6,Math.min(4,zoom+delta));draw();},reset(){zoom=1;pan={x:0,y:0};draw();}};
}
