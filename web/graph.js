// Original SVG dependency view. Layout is presentation only; planning uses backend graph evidence.
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function render(container,p,onSelect,{compact=false,soft=true}={}){
 const nodes=p.nodes.map(n=>({...n})), edges=[...p.edges];const known=new Set(nodes.map(n=>n.id));
 if(soft){for(const e of p.soft_edges||[]){edges.push(e);if(!known.has(e.to)){known.add(e.to);nodes.push({id:e.to,name:e.name,status:'optional_context',depth:(p.nodes.find(n=>n.id===e.from)?.depth||0)+1});}}}
 const levels=new Map(nodes.map(n=>[n.id,n.depth||0]));
 // Hard DAG layering, with every required branch represented.
 for(let i=0;i<p.nodes.length;i++){let changed=false;for(const e of p.edges){if(levels.get(e.to)<=levels.get(e.from)){levels.set(e.to,levels.get(e.from)+1);changed=true;}}if(!changed)break;}
 const layers=new Map();for(const n of nodes){const l=levels.get(n.id);if(!layers.has(l))layers.set(l,[]);layers.get(l).push(n);}
 const max=Math.max(...[...layers.values()].map(v=>v.length));const width=Math.max(compact?480:650,max*183+40),height=(Math.max(...levels.values())+1)*125+45;
 const positions=new Map();for(const [l,row]of layers){row.sort((a,b)=>a.id.localeCompare(b.id));row.forEach((n,i)=>positions.set(n.id,{x:(width-row.length*183)/2+i*183+8,y:l*125+20}));}
 const witness=p.selected?.witness||[];const highlighted=new Set(witness);
 const path=edges.filter(e=>positions.has(e.from)&&positions.has(e.to)).map(e=>{const a=positions.get(e.from),b=positions.get(e.to),lit=highlighted.has(e.from)&&highlighted.has(e.to)&&e.strength!=='soft';return `<path class="graph-edge ${e.strength==='soft'?'soft':''} ${lit?'lit':''}" d="M${a.x+80} ${a.y+67} C${a.x+80} ${a.y+105},${b.x+80} ${b.y-35},${b.x+80} ${b.y}" ><title>${escape(e.reason||'Prerequisite')}</title></path>`;}).join('');
 const boxes=nodes.map(n=>{const pos=positions.get(n.id),words=n.name.split(' ');let lines=[''];for(const w of words){if((lines.at(-1)+' '+w).length>22&&lines.length<3)lines.push(w);else lines[lines.length-1]+=(lines.at(-1)?' ':'')+w;}const status=n.status==='supported_for_task'||n.status==='supported_for_objective'?'task':n.status==='reported_ready'?'reported':n.status==='conflicting'?'conflict':n.status==='optional_context'?'optional':'unknown';return `<g class="graph-node ${status} ${highlighted.has(n.id)?'highlighted':''}" data-concept="${escape(n.id)}" tabindex="0" role="button" aria-label="${escape(n.name+', '+n.status.replaceAll('_',' '))}" transform="translate(${pos.x},${pos.y})"><rect width="160" height="68" rx="3"/><text x="11" y="17" class="graph-tag">${n.id===p.goal.id?'LEARNING GOAL':n.status==='optional_context'?'SOFT CONTEXT':n.status.replaceAll('_',' ').toUpperCase()}</text><text x="11" y="34">${lines.map((l,i)=>`<tspan x="11" dy="${i?13:0}">${escape(l)}</tspan>`).join('')}</text><title>${escape(n.name)}</title></g>`;}).join('');
 container.innerHTML=`<div class="graph-scroll ${compact?'compact':''}"><svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="group" aria-label="Prerequisite graph for ${escape(p.goal.name)}">${path}${boxes}</svg></div><p class="graph-caption">${p.nodes.length} required-route concepts. Solid lines are hard prerequisites. Dashed lines are optional context. Highlighted path explains the next check.</p>`;
 container.querySelectorAll('[data-concept]').forEach(el=>{const select=()=>onSelect?.(nodes.find(n=>n.id===el.dataset.concept));el.onclick=select;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};});
}

// Routes can hold 120 concepts. By default show what explains the decision: the goal, the highlighted "why" path and the
// direct prerequisites of each step on it. The full route stays one click away. Planning never uses this view.
const FOCUS_LIMIT=30;
export function drawGraph(container,p,onSelect,options={}){
 const witness=p.selected?.witness||[],big=p.nodes.length>FOCUS_LIMIT,full=!!options.full||!big;
 let view=p;
 if(!full){
  const keep=new Set([p.goal.id,...witness]);
  for(const e of p.edges)if(witness.includes(e.from))keep.add(e.to);
  view={...p,nodes:p.nodes.filter(n=>keep.has(n.id)),edges:p.edges.filter(e=>keep.has(e.from)&&keep.has(e.to)),
        soft_edges:(p.soft_edges||[]).filter(e=>keep.has(e.from)&&keep.has(e.to))};
 }
 render(container,view,onSelect,options);
 if(big){
  const note=document.createElement('p');note.className='graph-focus';
  note.innerHTML=full?`Showing all ${p.nodes.length} concepts. <button class="text-button" type="button">Focus on the highlighted path</button>`
   :`Focused view: the highlighted path and its direct prerequisites, ${view.nodes.length} of ${p.nodes.length} concepts. <button class="text-button" type="button">Show all ${p.nodes.length} concepts</button>`;
  note.querySelector('button').onclick=()=>drawGraph(container,p,onSelect,{...options,full:!full});
  container.prepend(note);
 }
 focusGraph(container,p);
}
// Centre the goal's column horizontally and start at the top, so the goal and the lit path are what you see first.
// Called again when the tab becomes visible, because a hidden container has no size.
export function focusGraph(container,p){
 const scroller=container?.querySelector('.graph-scroll'),goal=p&&container.querySelector(`[data-concept="${CSS.escape(p.goal.id)}"]`);
 if(!scroller||!goal||!scroller.clientWidth)return;
 const m=/translate\(([\d.-]+),([\d.-]+)\)/.exec(goal.getAttribute('transform')||'');
 if(m){scroller.scrollLeft=Math.max(0,+m[1]+80-scroller.clientWidth/2);scroller.scrollTop=0;}
}
