// The tutor's room: the role strip, fraction pictures and the controls a learner uses to answer.
// Nothing here knows an answer. Pictures are drawn from the server's render spec; grading happens on the server.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const frac=s=>{const [a,b]=String(s).split('/').map(Number);return a/b;};
const SHARE=['#d07a52','#8fa883','#efc75b','#7d8fb3','#c9a27e','#a3b8a0'];
const FILL='#d07a52',EMPTY='#fffdf6',INK='#25382e';

export const ROLES={
 scout:{name:'Scout',job:'the pathfinder',does:'Reads the FalkorDB route and picks which foundation to check.',art:'/static/assets/agents/scout.svg'},
 tinker:{name:'Tinker',job:'the experiment guide',does:'Chooses how to teach a foundation that was not yet shown.',art:'/static/assets/agents/tinker.svg'},
 lens:{name:'Lens',job:'the challenger',does:'Chooses a fresh transfer task in a different representation.',art:'/static/assets/agents/lens.svg'},
};

// Role strip. Status comes only from real backend events: a role is "working" while its MCP process runs.
export function renderRoles(el,{due,working,waiting,flash}={}){
 el.innerHTML=`<div class="role-strip" role="list">${Object.entries(ROLES).map(([id,r])=>{
  const state=working===id?'working':waiting===id?'waiting':due===id?'next':'idle';
  const word={working:'working now',waiting:'waiting for your answer',next:'up next',idle:'resting'}[state];
  return `<div class="role ${state}" role="listitem"><img src="${r.art}" alt="" width="48" height="48"><div><b>${r.name}</b><small>${r.job}</small><span class="role-state">${word}</span></div></div>`;}).join('<span class="role-arrow" aria-hidden="true">→</span>')}
  <div class="role-code"><span class="${flash==='assay'?'flash':''}">ASSAY · code grades</span><span class="${flash==='notebook'?'flash':''}">NOTEBOOK · code records</span></div></div>`;
}

function bar(parts,{w=300,h=44,shaded=[],clickable=false}={}){
 let x=0;const cells=parts.map((p,i)=>{const width=frac(p)*w,r=`<rect x="${x.toFixed(2)}" y="1" width="${width.toFixed(2)}" height="${h}" fill="${shaded.includes(i)?FILL:EMPTY}" stroke="${INK}" stroke-width="1.5"${clickable?` class="part" data-part="${i}" tabindex="0" role="button" aria-pressed="${shaded.includes(i)}" aria-label="Part ${i+1} of ${parts.length}"`:''}/>`;x+=width;return r;});
 return `<svg viewBox="-2 -1 ${w+4} ${h+4}" class="shape bar">${cells.join('')}</svg>`;
}
function pie(parts,{r=56,shaded=[],clickable=false}={}){
 let a=-Math.PI/2;const cx=r+2,cy=r+2;
 const slices=parts.map((p,i)=>{const b=a+frac(p)*2*Math.PI,large=frac(p)>.5?1:0;
  const d=parts.length===1?`M${cx} ${cy-r}A${r} ${r} 0 1 1 ${cx-.01} ${cy-r}Z`:`M${cx} ${cy}L${(cx+r*Math.cos(a)).toFixed(2)} ${(cy+r*Math.sin(a)).toFixed(2)}A${r} ${r} 0 ${large} 1 ${(cx+r*Math.cos(b)).toFixed(2)} ${(cy+r*Math.sin(b)).toFixed(2)}Z`;a=b;
  return `<path d="${d}" fill="${shaded.includes(i)?FILL:EMPTY}" stroke="${INK}" stroke-width="1.5"${clickable?` class="part" data-part="${i}" tabindex="0" role="button" aria-pressed="${shaded.includes(i)}" aria-label="Slice ${i+1} of ${parts.length}"`:''}/>`;});
 return `<svg viewBox="0 0 ${2*r+4} ${2*r+4}" class="shape pie">${slices.join('')}</svg>`;
}
function grid(cells){
 const rows=cells.split('/'),s=34,groups=[...new Set(cells.replace(/\//g,''))];
 const rects=rows.flatMap((row,y)=>[...row].map((g,x)=>`<rect x="${x*s+1}" y="${y*s+1}" width="${s}" height="${s}" fill="${SHARE[groups.indexOf(g)%SHARE.length]}" stroke="#fffdf6" stroke-width="2"/>`));
 return `<svg viewBox="0 0 ${rows[0].length*s+2} ${rows.length*s+2}" class="shape grid">${rects.join('')}</svg>`;
}
function counters(n,shaded,clickable){
 const per=n>8?6:4,s=38;
 return `<svg viewBox="0 0 ${per*s} ${Math.ceil(n/per)*s}" class="shape set">${Array.from({length:n},(_,i)=>`<circle cx="${(i%per)*s+s/2}" cy="${Math.floor(i/per)*s+s/2}" r="${s/2-5}" fill="${shaded.includes(i)?FILL:EMPTY}" stroke="${INK}" stroke-width="1.5"${clickable?` class="part" data-part="${i}" tabindex="0" role="button" aria-pressed="${shaded.includes(i)}" aria-label="Counter ${i+1} of ${n}"`:''}/>`).join('')}</svg>`;
}
function line(spec,{selected=null,point=null,clickable=false}={}){
 const span=spec.span||1,t=spec.ticks_per_unit,n=t*span,w=520,pad=26,step=(w-2*pad)/n;
 const ticks=Array.from({length:n+1},(_,j)=>{const x=pad+j*step,whole=j%t===0;
  return `<line x1="${x}" x2="${x}" y1="${whole?22:28}" y2="${whole?58:52}" stroke="${INK}" stroke-width="${whole?2:1.3}"/>${whole?`<text x="${x}" y="78" text-anchor="middle">${j/t}</text>`:''}${clickable?`<rect class="tick" data-tick="${j}" x="${x-step/2}" y="10" width="${step}" height="58" tabindex="0" role="button" aria-label="Mark ${j} of ${n}" aria-pressed="${selected===j}"/>`:''}`;}).join('');
 const marker=v=>v===null?'':`<circle cx="${pad+v*step}" cy="40" r="8" fill="${FILL}" stroke="${INK}" stroke-width="1.5"/>`;
 return `<svg viewBox="0 0 ${w} 86" class="shape line"><line x1="${pad}" x2="${w-pad}" y1="40" y2="40" stroke="${INK}" stroke-width="2"/>${ticks}${marker(selected)}${marker(point)}</svg>`;
}
function picture(o){return o.shape==='grid'?grid(o.cells):o.shape==='circle'?pie(o.parts,{r:44}):bar(o.parts,{w:220,h:36});}

// A worked example. It shows its solution because that item is retired from every check in this notebook.
function exampleHtml(ex){const s=ex.render,sol=ex.solution;let art='';
 if(s.type==='choose_picture')art=`<div class="pictures">${s.options.map((o,i)=>`<div class="picture ${i===sol.choice?'right':''}">${picture(o)}${i===sol.choice?'<small>fair split</small>':''}</div>`).join('')}</div>`;
 else if(s.type==='shade')art=s.shape==='set'?counters(s.parts,sol.shaded,false):s.shape==='circle'?pie(Array(s.parts).fill(`1/${s.parts}`),{shaded:sol.shaded}):bar(Array(s.parts).fill(`1/${s.parts}`),{shaded:sol.shaded});
 else if(s.type==='place')art=line(s,{selected:sol.tick});
 else art=line(s,{point:s.point})+`<p class="small">Answer: ${esc(s.options[sol.choice])}</p>`;
 return `<div class="worked"><span class="eyebrow">WORKED EXAMPLE · RETIRED FROM CHECKS</span><p>${esc(s.prompt)}</p>${art}<ol>${ex.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></div>`;}

const PURPOSE={diagnostic:'SCOUT’S CHECK · NO HINTS',lesson:'TINKER’S LESSON · HINTS ALLOWED',transfer:'LENS’S TRANSFER CHECK · NO HINTS',probe:'TINKER’S DISTINGUISHING CHECK · NOT A SUPPORT CHECK',recheck:'LATER CHECK · NO HINTS'};

export function renderFraction(el,task,{submit,hint}){
 const s=task.render;let chosen=null,shaded=[];
 const showExample=task.example&&task.opening!=='try_first';
 const speak='speechSynthesis' in window;
 el.innerHTML=`<p class="eyebrow">${PURPOSE[task.purpose]||'TASK'} / ${esc(task.activity.title)}</p>
  <p class="source-note">Shown with ${esc(task.representation_label)}. Graded on the server with exact fractions (${esc(task.rubric)}).</p>
  ${task.teaching_strategy?`<section class="strategy-card"><span class="eyebrow">LET’S TRY THIS WAY</span><h3>${esc(task.teaching_strategy.title)}</h3><p>${esc(task.teaching_strategy.instruction)}</p></section>`:''}
  ${task.purpose==='probe'?'<p class="source-note">A short check to help choose an explanation. It does not count towards support.</p>':''}
  ${showExample?exampleHtml(task.example):''}
  <div class="prompt-row"><h3>${esc(s.prompt)}</h3>${speak?'<button class="text-button" id="read-aloud" aria-label="Read the question aloud">Read aloud ♪</button>':''}</div>
  <div id="fraction-work" class="fraction-work"></div>
  <div class="task-actions"><button id="check-answer" class="primary" disabled>Check my answer <span>→</span></button>${task.hints_allowed?`<button id="hint" class="text-button">Show a hint (${task.hints.length} of ${task.hints_available} used) ↗</button>`:''}</div>
  <div id="hint-list">${task.hints.map(h=>`<p class="hint">${esc(h)}</p>`).join('')}</div><div id="feedback" aria-live="polite"></div>`;
 const work=el.querySelector('#fraction-work'),check=el.querySelector('#check-answer');
 const draw=()=>{
  if(s.type==='choose_picture'||s.type==='read_line'){
   work.innerHTML=(s.type==='read_line'?line(s,{point:s.point}):'')+`<div class="${s.type==='read_line'?'answers':'pictures'}">${s.options.map((o,i)=>`<button class="${s.type==='read_line'?'answer':'picture'} ${chosen===i?'chosen':''}" data-choice="${i}" aria-pressed="${chosen===i}">${s.type==='read_line'?esc(o):picture(o)+`<small>Picture ${'ABC'[i]}</small>`}</button>`).join('')}</div>`;
   work.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>{chosen=Number(b.dataset.choice);check.disabled=false;draw();});
  }else if(s.type==='shade'){
   const parts=Array(s.parts).fill(`1/${s.parts}`);
   work.innerHTML=(s.shape==='set'?counters(s.parts,shaded,true):s.shape==='circle'?pie(parts,{shaded,clickable:true}):bar(parts,{shaded,clickable:true}))+`<p class="small">${shaded.length} of ${s.parts} equal parts shaded. Tap a part again to unshade it.</p>`;
   work.querySelectorAll('.part').forEach(p=>{const toggle=()=>{const i=Number(p.dataset.part);shaded=shaded.includes(i)?shaded.filter(x=>x!==i):[...shaded,i];check.disabled=false;draw();work.querySelector(`[data-part="${i}"]`)?.focus();};
    p.addEventListener('click',toggle);p.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle();}});});
  }else{
   work.innerHTML=line(s,{selected:chosen,clickable:true})+`<p class="small">Tap a mark, or use the arrow keys on the line.</p>`;
   const n=s.ticks_per_unit*s.span;
   work.querySelectorAll('.tick').forEach(t=>{const pick=j=>{chosen=Math.max(0,Math.min(n,j));check.disabled=false;draw();work.querySelector(`[data-tick="${chosen}"]`)?.focus();};
    t.addEventListener('click',()=>pick(Number(t.dataset.tick)));
    t.addEventListener('keydown',e=>{const j=Number(t.dataset.tick);if(e.key==='ArrowRight')pick(j+1);else if(e.key==='ArrowLeft')pick(j-1);else if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(j);}});});
  }};
 draw();
 check.onclick=async()=>{check.disabled=true;el.querySelectorAll('#fraction-work button,.part,.tick').forEach(b=>{b.setAttribute('aria-disabled','true');b.style.pointerEvents='none';});
  const response=s.type==='shade'?{shaded:[...shaded].sort((a,b)=>a-b)}:s.type==='place'?{tick:chosen}:{choice:chosen};
  const result=await submit(response);
  if(!result){check.disabled=false;el.querySelectorAll('#fraction-work button,.part,.tick').forEach(b=>{b.removeAttribute('aria-disabled');b.style.pointerEvents='';});return;}
  if(task.example&&task.opening==='try_first')el.querySelector('#feedback').insertAdjacentHTML('beforebegin',exampleHtml(task.example));};
 if(el.querySelector('#hint'))el.querySelector('#hint').onclick=async()=>{const d=await hint();if(!d)return;el.querySelector('#hint-list').insertAdjacentHTML('beforeend',`<p class="hint">${esc(d.hint)}</p>`);
  el.querySelector('#hint').textContent=`Show a hint (${d.shown} of ${d.available} used) ↗`;if(d.shown>=d.available)el.querySelector('#hint').disabled=true;};
 if(el.querySelector('#read-aloud'))el.querySelector('#read-aloud').onclick=()=>{try{speechSynthesis.cancel();speechSynthesis.speak(new SpeechSynthesisUtterance(s.prompt));}catch(e){el.querySelector('#read-aloud').replaceWith(Object.assign(document.createElement('span'),{className:'small',textContent:'Read-aloud is not available here. The question is shown above.'}));}};
}

// Stations along the route, in route order, with their real evidence state.
export function renderStations(el,stations,current){
 const word={supported_for_objective:'observed: supported',needs_check:'observed: still checking',unknown:'not checked yet'};
 const state=s=>s.paused_until?['paused','paused, back later']:s.recheck_due?['recheck','due for a later check']:s.suspect?['suspect',`suspected: below ${s.suspect.below_name}`]:s.inferred_from&&s.status==='unknown'?['inferred','inferred only, not observed']:[s.status,word[s.status]||s.status.replaceAll('_',' ')];
 el.innerHTML=`<p class="eyebrow">THE EXPEDITION · LESSONS ON THIS ROUTE · STATES FROM FALKORDB</p><ol class="stations">${stations.map(s=>{const [cls,label]=state(s);return `<li class="station ${s.status} ${cls} ${s.concept===current?'current':''}"><b>${esc(s.title)}</b><small>${esc(label)}</small></li>`;}).join('')}</ol>`;
}

// The Cypher behind the tutor's latest decision, with FalkorDB's own server timings.
export function renderTutorQueries(el,status){
 const q=status.decision_queries||[],v=status.view_queries||[];
 if(!q.length&&!v.length){el.hidden=true;return;}
 const block=x=>`<div class="native-query"><b>${esc(x.name)}</b><small>${Number(x.server_ms).toFixed(3)} ms on the FalkorDB server / ${x.rows} rows</small><pre>${esc(x.cypher)}</pre><button class="text-button explain-button" data-explain>Show FalkorDB’s execution plan</button><pre class="plan" hidden></pre></div>`;
 const total=q.reduce((s,x)=>s+(x.server_ms||0),0);
 el.hidden=false;
 el.innerHTML=`<p class="eyebrow">THE TUTOR'S LATEST DECISION, AS GRAPH QUERIES</p><p>${q.length?`${q.length} decision queries, ${total.toFixed(2)} ms on the server.`:'No tutor decision yet. The state queries below inspect this notebook.'} Evidence is graph structure: each task points to its concept and representation, each answer is an observation about a concept.</p>${status.scout?.reasons?.length?`<p><b>Why Scout chose ${esc(status.scout.title||status.scout.activity_id)}:</b> ${status.scout.reasons.map(esc).join('; ')}.</p>`:''}<details open><summary>Decision queries</summary>${q.map(block).join('')}</details><details><summary>Station state queries (suspected and inferred foundations)</summary>${v.map(block).join('')}</details>`;
}

// The parent's summary, computed from the evidence edges.
export function renderReport(el,r){
 if(!r.activity.length&&!r.return_later.length){el.hidden=true;return;}
 const when=t=>new Date(t*1000).toLocaleString([], {weekday:'short',hour:'2-digit',minute:'2-digit'});
 el.hidden=false;
 el.innerHTML=`<p class="eyebrow">FOR A GROWN-UP · TODAY WITH THE TUTOR</p><table class="report"><thead><tr><th>Foundation</th><th>Answers</th><th>Correct</th><th>Lesson practice</th><th>With hints</th><th>What was tricky</th></tr></thead><tbody>${r.activity.map(a=>`<tr><td>${esc(a.title)}<small>${esc(a.name)}</small></td><td>${a.answers}</td><td>${a.correct}</td><td>${a.lesson_answers}</td><td>${a.hinted}</td><td>${a.difficulties.map(esc).join('; ')||'nothing recorded'}</td></tr>`).join('')}</tbody></table>
 ${r.return_later.length?`<p><b>Coming back later:</b> ${r.return_later.map(x=>`${esc(x.title)} (${when(x.when)}, ${esc(x.why)})`).join('; ')}.</p>`:''}
 <p class="small">${esc(r.scope)} Computed by ${r.queries.length} FalkorDB quer${r.queries.length===1?'y':'ies'} over the observations.</p>`;
}

// The parent/judge drawer: real tool steps, the offered options and who chose.
export function tutorTrail(events){
 return events.map(e=>{
  if(e.type==='role_started')return `<div class="trail-step guided"><span class="trail-tag">${esc(ROLES[e.role].name.toUpperCase())} · OWN MCP SERVER · ${e.chooser==='model'?'LOCAL MODEL':'RULE-BASED, NO MODEL'}</span></div>`;
  if(e.type==='tools_listed')return `<div class="trail-step guided"><span class="trail-tag">PERMITTED TOOLS</span><small>${e.tools.map(esc).join(', ')}</small></div>`;
  if(e.type==='model_decision'){const model=e.chooser==='model',same=e.agrees_with_rule;
   return `<div class="trail-step choice"><span class="trail-tag">${model?`MODEL CHOICE · ${same?'SAME AS THE RULE':'DIFFERS FROM THE RULE'}`:'RULE CHOICE · NO MODEL'} · ${e.options.length} permitted options${model?' · shown shuffled':''}</span><b>${esc(e.label)}</b>${model&&!same?`<small>The rule would have chosen: ${esc(e.rule_label)}</small>`:''}<details><summary>All options and the ${model?'model’s own words (unverified)':'rule'}</summary><ol>${e.options.map(o=>`<li>${esc(o.label)}</li>`).join('')}</ol><p>${esc(model?e.model_reason_unverified:e.rule_why)}</p></details></div>`;}
  if(e.type==='tool_finished')return `<div class="trail-step guided"><span class="trail-tag">TOOL · ${esc(e.tool)}</span><small>result ${esc(e.result_hash?.slice(0,10))}</small></div>`;
  return '';}).join('');
}

const STEP={diagnostic:'Scout’s check',probe:'Distinguishing check',lesson:'Lesson practice',transfer:'Lens’s transfer check',recheck:'Later check'};

// The current foundation's episode, as FalkorDB records it: each answer, what it suggested, what was tried.
export function episodeHtml(episode){
 if(!episode?.steps?.length)return '';
 const st=episode.status;
 const banner=st?[st.required?`<p class="episode-flag required"><b>Investigation required by the controller.</b> ${esc(st.note)}</p>`:'',
  !st.required&&st.note?`<p class="episode-flag">${esc(st.note)}</p>`:'',
  st.probe_outcome?`<p class="episode-flag ${st.probe_outcome.kind}"><b>${st.probe_outcome.kind==='pointed'?'The check narrowed it down.':'The check was inconclusive.'}</b> ${esc(st.probe_outcome.text)}</p>`:'',
  st.tried_strategies.length?`<p class="episode-flag excluded"><b>Not repeated:</b> ${st.tried_strategies.map(x=>`${esc(x.title)} (${esc(x.why)})`).join('; ')}.</p>`:''].join(''):'';
 return `${banner}<ol class="episode">${episode.steps.map(s=>`<li class="${s.correct?'ok':'miss'}"><b>${esc(STEP[s.purpose]||s.purpose)}</b>${s.strategy?` · strategy: ${esc(s.strategy)}`:''} · ${esc(s.representation)}<br><span>${s.correct?'Correct for this task':'Not yet right'}${s.hinted?', with hints':''}.</span>${!s.correct&&s.explanation?` <span class="maybe">Possible explanation: ${esc(s.explanation)}${s.ambiguous?' (ambiguous on its own)':''}</span>`:''}</li>`).join('')}</ol>`;
}

export function renderInvestigation(el, investigation, episode){
 const body=episodeHtml(episode);
 if(!body&&!investigation?.observation){el.innerHTML='';return;}
 const st=episode?.status,open=st&&(st.required||st.tried_strategies.length||st.probe_outcome);
 const tried=new Set((st?.tried_strategies||[]).map(x=>x.id));
 const eligible=(investigation?.strategies||[]).filter(s=>!tried.has(s.id));
 el.innerHTML=`<details class="investigation-card"${open?' open':''}><summary>For a grown-up: why this next?</summary>
 ${body}
 ${eligible.length&&!st?.required?`<p><b>Strategies still eligible for the latest mistake:</b> ${eligible.map(s=>esc(s.title)).join('; ')}</p>`:''}
 <p class="small">These are possible explanations to check, not diagnoses. Every line above is read from this notebook's graph. <a href="#notes">See the full field notes</a>.</p></details>`;
 el.querySelector('a').onclick=e=>{e.preventDefault();document.querySelector('nav [data-tab="notes"]').click();};
}
