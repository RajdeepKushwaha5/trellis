import {createAtlas} from './atlas.js';
import {drawGraph,focusGraph} from './graph.js';
import {initWater} from './water.js';
import {startNightSky} from './footer.js';
import {ROLES,renderRoles,renderFraction,renderStations,renderTutorQueries,renderReport,tutorTrail} from './tutor.js';
startNightSky(document.getElementById('night-sky'),document.querySelector('footer.night'));
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let plan,action,busy=false,agentMode=false,automatic=0,prepared=null,comparison=null;
const curriculum={subject:'',q:'',offset:0};
let atlas=null,atlasPromise=null,activeJob=null;
let tutor=null,roleView={};
const EXPEDITION='mt_NoB20kVa4w';
const lessonRoute=()=>Boolean(plan&&plan.lesson_count>0);
// On a lesson route the map highlights the foundation Scout actually chose, with FalkorDB's witness path to the goal.
const mapPlan=()=>lessonRoute()&&tutor?.concept&&plan.graph_reasoning?.witnesses?.[tutor.concept]?{...plan,selected:{...(plan.selected||{}),concept:tutor.concept,witness:plan.graph_reasoning.witnesses[tutor.concept]}}:plan;
async function ensureAtlas(){if(!atlasPromise)atlasPromise=api('constellation').then(data=>{atlas=createAtlas($('atlas'),data,n=>{$('atlas-selection').innerHTML=`<b>${esc(n.name)}</b> / ${esc(n.subject)} <button id="atlas-choose" class="text-button">Choose this goal →</button>`;$('atlas-choose').onclick=()=>changeGoal(n.id);});atlas.setRoute(plan);});await atlasPromise;atlas.setSubject(curriculum.subject);}
// What the lit route is, in numbers the graph returned: size, subjects crossed and FalkorDB time for the deciding queries.
function routeSummary(){if(!plan||!$('atlas-route'))return;const subjects=[...new Set(plan.nodes.map(n=>n.subject))],other=plan.nodes.filter(n=>n.subject!==plan.goal.subject).length,q=plan.graph_reasoning?.queries||[],ms=q.reduce((s,x)=>s+(x.server_ms||0),0);
 $('atlas-route').innerHTML=`<b>${esc(plan.goal.name)}</b> needs ${plan.nodes.length-1} foundation${plan.nodes.length===2?'':'s'}${other?`, ${other} of them from ${subjects.filter(s=>s!==plan.goal.subject).map(esc).join(' and ')}`:''}. FalkorDB computed the route, coverage and paths in ${ms.toFixed(1)} ms over ${q.length} queries.`;}
async function loadFeatured(){try{const d=await api('featured');$('featured').innerHTML='<span class="eyebrow">ROUTES WORTH A LOOK, PICKED BY FALKORDB</span>'+d.goals.map(g=>`<button class="featured-goal" data-feature="${esc(g.id)}"><b>${esc(g.name)}</b><small>${esc(g.subject)} · ${g.route_size} foundations${g.other_subject_count?` · ${g.other_subject_count} from ${g.other_subjects.map(esc).join(', ')}`:''}</small></button>`).join('')+`<p class="small">One query over all 1,590 routes, ${d.server_ms.toFixed(1)} ms on the server.</p>`;document.querySelectorAll('[data-feature]').forEach(b=>b.onclick=()=>changeGoal(b.dataset.feature));}catch(e){$('featured').textContent='';}}
loadFeatured();
// The opening panel: figures the graph returned, and the route this notebook is following now.
async function loadOverview(){try{const d=await api('overview'),n=v=>Number(v).toLocaleString();
 $('hero-figures').innerHTML=[[n(d.concepts),'ideas a child can learn'],[n(d.connections),'links saying what comes first'],
  [n(d.cross_subject_goals),'goals that lean on another subject'],[n(d.largest_route),'foundations behind the biggest goal']]
  .map(([v,l])=>`<div><b>${v}</b><span>${l}</span></div>`).join('');
 $('hero-source').textContent=`Counted live in FalkorDB: one query walks all 1,590 routes in ${d.server_ms.toFixed(1)} ms on the server.`;}catch(e){$('hero-source').textContent='';}}
function heroRoute(){if(!plan||!$('hero-route'))return;const n=plan.nodes.length-1;
 $('hero-route').innerHTML=`<span class="eyebrow">YOUR ROUTE NOW</span><button class="text-button" data-tab="map">${esc(plan.goal.name)} · ${n} foundation${n===1?'':'s'} ↗</button>`;
 $('hero-route').querySelector('[data-tab]').onclick=()=>tab('map');}
loadOverview();
$('atlas-in').onclick=()=>atlas?.zoom(.3);$('atlas-out').onclick=()=>atlas?.zoom(-.3);$('atlas-reset').onclick=()=>atlas?.reset();
const notice=text=>{$('notice').hidden=!text;$('notice').textContent=text;};
async function api(path,body){const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'The request could not be completed');return d;}
function tab(name){if(!['lab','map','notes','curriculum','compare'].includes(name))name='lab';if(location.hash.slice(1)!==name)notice('');document.querySelectorAll('.tab').forEach(x=>x.hidden=x.id!==name);document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));if(name==='notes')loadNotes().catch(e=>notice(e.message));if(name==='curriculum')loadCurriculum().catch(e=>notice(e.message));document.body.classList.toggle('working-view',name!=='curriculum');if(name==='compare'&&!comparison&&!busy)openComparison();if(name==='map')requestAnimationFrame(()=>focusGraph($('map-view'),mapPlan()));location.hash=name;}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
function emptyTask(){action=null;prepared=null;$('task').innerHTML='<p class="eyebrow">A PLACE TO BEGIN</p><h3>What feels familiar? What needs a closer look?</h3><p>Ask the guide to investigate, or try the graph-ranked next check. Parent reports and graded task responses are kept separate.</p>';}
function render(){
 const selected=plan.selected,water=plan.goal.subject==='Science'&&plan.activity_count>0;
 $('goal-title').textContent=plan.goal.name;$('goal-description').textContent=plan.goal.description;$('goal-subject').textContent=plan.goal.subject.toUpperCase();
 $('goal-subject').textContent=plan.goal.subject.toUpperCase()+(plan.goal.ages.every(v=>v!==null)?` · SOURCE AGES ${plan.goal.ages.join(' TO ')}`:'');
 $('water-demo').hidden=!water;$('general-context').hidden=water;
 $('general-context').innerHTML=`<span class="eyebrow">THE INVESTIGATION DESK</span><h2>${esc(plan.goal.subject)}</h2><p>${plan.nodes.length} connected concepts behind this goal.</p><p>${plan.activity_count?'Prototype tasks are available on this route.':'No interactive lab on this route yet. Investigate using source criteria and parent observations.'}</p><span class="source-label">PARENT CHECKS ARE REPORTED EVIDENCE, NOT GRADED TESTS</span>`;
 document.querySelector('.pill').textContent=water?'THE WATER STUDIO':'THE LEARNING NOTEBOOK';
 $('next').innerHTML=`<span class="label">${selected?'YOUR NEXT STEPPING STONE':'PAUSE & REVIEW THE ROUTE'}</span><h3>${esc(selected?.title||'No unchecked source criteria remain')}</h3>`;
 const names=new Map(plan.nodes.map(n=>[n.id,n.name]));
 $('reason').innerHTML=selected?`<p><b>${esc(selected.title)}</b> investigates a foundation connected to ${selected.coverage} concept${selected.coverage===1?'':'s'} in this route.</p><p>${selected.missing.length?'Other foundations are uncertain. This is a diagnostic probe, not a readiness claim.':'No unresolved direct hard prerequisites were found for this check.'}</p><p class="witness">${selected.witness.map(id=>esc(names.get(id))).join(' → ')}</p><span class="source-label">${selected.kind==='parent_check'?'SOURCE CRITERION / PARENT REPORT':'PROTOTYPE TASK / DETERMINISTIC GRADING'}</span>`:'<p>No unchecked criteria or prototype tasks remain. Inspect unresolved evidence and coverage gaps. Finishing available checks does not prove mastery.</p>';
 $('candidates').innerHTML=plan.candidates.slice(0,12).map((c,i)=>`<div class="candidate">${i+1} / ${esc(c.title)}<small>${c.coverage} connected concept${c.coverage===1?'':'s'} · ${c.missing.length} uncertain prerequisite${c.missing.length===1?'':'s'} · ${c.kind==='parent_check'?'parent check':'prototype task'}</small></div>`).join('')+(plan.candidates.length>12?`<p class="small">First 12 of ${plan.candidates.length} eligible checks.</p>`:'');
 if(lessonRoute()&&tutor?.scout?.ranked){
  // On a lesson route, explain the tutor's actual decision rather than the generic next check.
  const sc=tutor.scout;
  $('reason').innerHTML=`<p><b>${esc(sc.title)}</b> was chosen by ${sc.chosen_by==='scout'?'Scout':'a manual click'} from ${sc.ranked.length} lessons FalkorDB ranked for this route.</p><p>${sc.reasons.map(esc).join('. ')}.</p><p class="witness">${sc.witness_concepts.map(esc).join(' → ')}</p><span class="source-label">LESSON CHECK / EXACT GRADING ON THE SERVER</span>`;
  $('candidates').innerHTML=sc.ranked.map(o=>`<div class="candidate">${o.graph_rank??'later'} / ${esc(o.title)} <small>${esc(o.concept_name)} · ${o.reasons.map(esc).join(' · ')}</small></div>`).join('');}
 drawGraph($('map-view'),mapPlan(),inspectConcept,{soft:$('show-soft').checked});
 const focus=plan.nodes.find(n=>n.id===selected?.concept);if(focus)inspectConcept(focus);
 const queries=plan.graph_reasoning?.queries||[];
 $('query-info').innerHTML=`${plan.nodes.length} concepts in the complete hard closure. Reachability, coverage, shortest witnesses and ranking run in FalkorDB.<details class="native-queries"><summary>See the deciding queries and actual timings</summary>${queries.map(q=>`<div class="native-query"><b>${esc(q.name)}</b><small>${Number(q.server_ms).toFixed(3)} ms server / ${q.wall_ms} ms client wall / ${q.rows} rows</small><pre>${esc(q.cypher)}</pre></div>`).join('')}</details>`;
 $('evidence').textContent=JSON.stringify({graph:plan.graph,revision:plan.revision,fingerprint:plan.fingerprint,edges:plan.edges,soft_edges:plan.soft_edges,candidates:plan.candidates},null,2);
 $('manual').disabled=busy||!selected;$('agent').disabled=busy||!selected;atlas?.setRoute(plan);routeSummary();heroRoute();
 if(lessonRoute())renderLessonRoom();else{$('tutor-studio').hidden=true;$('tutor-queries').hidden=true;$('agent').innerHTML='Let the guide choose <span>↗</span>';$('manual').textContent='Try the graph\'s first diagnostic →';$('guide-note').textContent='Local AI guide through MCP. Manual mode uses the same graph evidence.';document.querySelectorAll('.autoguide,.autoguide+.small').forEach(x=>x.hidden=false);}
}
async function refresh(){plan=await api('plan');render();}
function inspectConcept(n){
 const related=[...plan.edges,...plan.soft_edges].filter(e=>e.from===n.id||e.to===n.id);
 $('concept-inspector').innerHTML=`<p class="eyebrow">CONCEPT FIELD NOTES</p><h3>${esc(n.name)}</h3><p>${esc(n.description||'Optional source context.')}</p><p class="small">${esc(n.id)} / ${esc(n.status.replaceAll('_',' '))} / ${esc(n.evidence_kind||'optional context')}</p>${n.criteria?.length?`<h4>Source-authored criteria</h4><ol>${n.criteria.map((c,i)=>`<li>${esc(c)} <small>${esc(n.reports?.find(r=>r.criterion===i)?.response||'not reported')}</small><button class="text-button" data-recheck="${i}">Update this parent observation →</button></li>`).join('')}</ol>`:'<p>No criteria in this displayed context.</p>'}<details><summary>Why these concepts connect</summary>${related.map(e=>`<p class="small">${esc(e.reason)} (${e.strength})</p>`).join('')}</details>${n.criteria?.length?'<button id="preview" class="text-button">What if this foundation had reported support? ↗</button>':''}`;
 $('concept-inspector').querySelectorAll('[data-recheck]').forEach(b=>b.onclick=async()=>{if(busy)return;try{const value=await api('recheck',{concept_id:n.id,criterion:Number(b.dataset.recheck),revision:plan.revision});agentMode=false;showTask(value);notice('Explicit parent recheck. Earlier observations remain in the field notes.');}catch(e){notice(e.message);}});
 if($('preview'))$('preview').onclick=async()=>{try{$('preview').disabled=true;const d=await api('preview',{concept_id:n.id});$('preview-result').innerHTML=`<div class="feedback"><b>Hypothetical graph-copy preview</b><p>Current: ${esc(d.before?.title||'No next check')}<br>With reported support: ${esc(d.after?.title||'Review the route')}</p><p>${esc(d.note)}</p></div>`;}catch(e){notice(e.message);}finally{if($('preview'))$('preview').disabled=false;}};
}
function showTask(value){if(value.kind==='fraction'){refreshTutor().then(()=>{render();showFraction(value);tab('lab');});return;}action=value;prepared=null;$('phase').textContent=value.kind==='parent_check'?'02 / PARENT OBSERVATION':'02 / PREDICT & EXPLAIN';$('task').innerHTML=`<p class="eyebrow">${value.kind==='parent_check'?'PARENT-REPORTED CHECK':'STRUCTURED TASK'} / ${esc(value.activity.title)}</p>${value.kind==='parent_check'?'<p class="source-note">Report what you have seen the learner do. This source-authored criterion is not a graded answer.</p>':''}<h3>${esc(value.item.question)}</h3><div class="answers">${value.item.options.map((s,i)=>`<button class="answer" data-choice="${i}">${String.fromCharCode(65+i)}. ${esc(s)}</button>`).join('')}</div><div id="feedback" aria-live="polite"></div>`;document.querySelectorAll('[data-choice]').forEach(b=>b.onclick=()=>answer(Number(b.dataset.choice)));tab('lab');}
function renderTrail(events){
 // Real choices stand out; required reads and controller steps are muted. Model prose stays labelled unverified.
 $('live-trail').innerHTML=events.map(e=>{
  if(e.type==='model_decision'){
   const opts=e.ranked_options||[],pick=e.decision.activity_id,rank=opts.findIndex(o=>o.id===pick),title=opts[rank]?.title||pick;
   const launch=e.decision.tool==='launch_diagnostic',inspect=e.decision.tool==='inspect_concept';
   const free=e.offered_tools.length>1||((launch||inspect)&&opts.length>1);
   const tag=launch||inspect?`MODEL CHOICE · 1 of ${opts.length} ranked check${opts.length===1?'':'s'}${rank>=0?` · FalkorDB ranked it #${rank+1}`:''}`:free?`MODEL CHOICE · 1 of ${e.offered_tools.length} tools`:'ONE TOOL OFFERED';
   return `<div class="trail-step ${free?'choice':'guided'}"><span class="trail-tag">STEP ${e.step} · ${esc(tag)}</span><b>${esc(launch?'Launch: '+title:inspect?'Inspect: '+title:'Rank the checks')}</b><details><summary>Model's own words (unverified)</summary>${esc(e.decision.reason)}</details></div>`;}
  if(e.type==='tool_finished'&&e.source!=='model-selected')return `<div class="trail-step guided"><span class="trail-tag">${esc(e.source==='harness prerequisite'?'REQUIRED READ':'CONTROLLER')}</span><b>${esc(e.tool)}</b><small>result ${esc(e.result_hash?.slice(0,10))}</small></div>`;
  return '';}).join('');
 const last=[...events].reverse().find(e=>e.type==='model_decision'&&e.decision.tool==='launch_diagnostic');
 if(last){const opts=last.ranked_options||[],rank=opts.findIndex(o=>o.id===last.decision.activity_id);
  $('agent-status').textContent=`The guide chose “${opts[rank]?.title||last.decision.activity_id}” from ${opts.length} graph-ranked checks${rank>=0?` (FalkorDB ranked it #${rank+1})`:''}. The explanation shown is built from graph evidence, not the model's prose.`;}
}

async function runLiveAgent(){
 const start=await api('agent/start',{});activeJob=start.id;
 $('agent-status').innerHTML='Investigation running <button id="stop-investigation" class="text-button">Pause</button>';
 $('stop-investigation').onclick=()=>api('agent/jobs/'+activeJob+'/cancel',{}).catch(e=>notice(e.message));
 try{while(true){const job=await api('agent/jobs/'+start.id);renderTrail(job.events);if(job.status==='completed')return job.result;if(job.status!=='running')throw Error(job.error||'Investigation stopped');await new Promise(resolve=>setTimeout(resolve,450));}}
 finally{activeJob=null;if(!$('agent-status').textContent.startsWith('The guide chose'))$('agent-status').textContent='Investigation paused. Only completed evidence changes the notebook.';}
}
async function requestNext(useAgent){if(useAgent){const d=await runLiveAgent();return {action:d.action,reason:d.reason,complete:d.complete};}return {action:await api('launch',{activity_id:plan.selected.id,revision:plan.revision}),reason:'Graph-ranked check selected manually. No model decision was made.'};}

async function next(useAgent){if(busy||!plan.selected)return;
 // The same check is already open and unanswered: say so beside the button instead of relaunching it.
 if(!useAgent&&action&&!action.answered&&action.activity?.id===plan.selected.id){$('agent-status').textContent='This check is already open in the panel. Answer it and FalkorDB will rank the next one.';$('task').scrollIntoView({behavior:'smooth',block:'center'});$('task').classList.add('pulse');setTimeout(()=>$('task').classList.remove('pulse'),1200);return;}
busy=true;agentMode=useAgent;automatic=0;notice(useAgent?'The guide is investigating through MCP. Cold model startup can take a minute.':'');render();try{const d=await requestNext(useAgent);if(d.action){showTask(d.action);$('task').scrollIntoView({behavior:'smooth',block:'center'});}notice(d.reason);if(!useAgent)$('agent-status').textContent=d.reason;}catch(e){notice(e.message);$('agent-status').textContent=e.message;}finally{busy=false;render();}}
async function answer(choice){
 if(busy||!action)return;busy=true;document.querySelectorAll('[data-choice]').forEach(b=>b.disabled=true);
 try{const d=await api('answer',{action:action.action,choice});action.answered=true;const reported=d.kind==='parent_check';$('feedback').innerHTML=`<div class="feedback"><b>${reported?'Your observation is recorded.':d.correct?'A useful observation.':'Let’s look a little closer.'}</b><br>${esc(d.explanation)}${reported?'':`<br><small>${d.distinct_checks} distinct correct checks recorded. ${d.status==='supported_for_task'?'Supported for these tasks only.':'We will keep checking this idea.'}</small>`}</div><button id="continue" class="text-button">Find the next stepping stone →</button>`;await refresh();
 $('continue').onclick=()=>{if(prepared){const ready=prepared;if(ready.action)showTask(ready.action);else tab('notes');notice(ready.reason);}else next(agentMode);};
 if(agentMode&&$('auto-guide').checked&&automatic<3&&plan.selected){automatic++;$('continue').disabled=true;$('continue').textContent='The guide is preparing your next step...';notice('Your response changed the evidence. The agent is replanning automatically.');try{prepared=await requestNext(true);$('continue').textContent=prepared.action?'Your next check is ready →':'Review the learning route';}catch(e){notice(e.message);$('continue').textContent='Retry the next step →';}finally{if($('continue'))$('continue').disabled=false;}}
 else notice(agentMode&&automatic>=3?'Automatic investigation paused at its three-step budget. Review or explicitly continue.':reported?'Parent evidence recorded separately. The route has been recomputed.':'Task evidence recorded. The route has been recomputed.');
 }catch(e){notice(e.message);}finally{busy=false;render();}
}
async function loadNotes(){const d=await api('notebook'),r=d.plan.route;
 if(d.plan.lesson_count>0)api('tutor/report').then(x=>renderReport($('tutor-report'),x)).catch(()=>{});else $('tutor-report').hidden=true;
 $('learning-route').innerHTML=`<p class="eyebrow">YOUR EVIDENCE-BACKED LEARNING ROUTE</p><h3>${esc(r.goal)}</h3><div class="route-columns">${[['Observed task support',r.observed_support],['Parent-reported support',r.reported_support],['Still uncertain',r.uncertain]].map(([label,items])=>`<div><b>${label}${items.length>12?` (${items.length})`:''}</b><p>${items.slice(0,12).map(esc).join(', ')||'None recorded'}${items.length>12?`</p><details><summary>and ${items.length-12} more</summary><p>${items.slice(12).map(esc).join(', ')}</p></details><p>`:''}</p></div>`).join('')}</div><p>Next: ${lessonRoute()&&tutor?esc(tutor.task?`answer the open ${tutor.task.activity.title} task`:tutor.due_role?`${ROLES[tutor.due_role].name}: ${ROLES[tutor.due_role].does.toLowerCase()}`:'review the route'):esc(r.next?.title||'Review uncertainty and coverage.')}</p>${r.gaps.map(g=>`<p>${esc(g.name)}: ${esc(g.reason)}</p>`).join('')}<p class="small">${esc(r.scope)}</p>`;
 $('observations').innerHTML=d.observations.map((o,i)=>`<div class="observation"><span>${i+1}</span><span>${esc(o.label||o.item)}<br><small>${o.purpose?`${esc({diagnostic:'Scout check',lesson:'Tinker lesson practice',transfer:'Lens transfer check',recheck:'later check'}[o.purpose]||o.purpose)} / ${esc(o.representation)}${o.hinted?' / with hints, not counted as a check':''} / rubric ${esc(o.rubric)}`:'Structured response / rubric v1'}</small></span><span>${o.correct?'Correct for this task':'Needs another look'}</span></div>`).join('')||'<p class="small">No structured task responses.</p>';
 $('parent-observations').innerHTML=(d.parent_observations||[]).map(o=>`<div class="observation"><span>↗</span><span>${esc(d.plan.nodes.find(n=>n.id===o.concept)?.name||o.concept)} / criterion ${o.criterion+1}</span><span>${esc(o.response)} / parent-reported</span></div>`).join('')||'<p class="small">No parent observations.</p>';
 $('trace').innerHTML=d.decisions.map(x=>`<div class="tool"><b>${esc(x.model)}</b> <small>${x.plan_fingerprint===d.plan.fingerprint?'current evidence revision':'historical decision / evidence revision changed'}</small><br>${esc(x.reason)}<pre>${esc(JSON.stringify(x.trace,null,2))}</pre>Runtime tokens: ${x.usage.input??'unknown'} input, ${x.usage.output??'unknown'} output. Digest ${esc(x.provenance?.model_digest?.slice(0,12)||'unknown')}.<details><summary>Unverified model rationale</summary>${esc(x.model_reason_unverified)}</details></div>`).join('')||'No investigation-agent decision recorded. Manual checks do not count as agent decisions.';
 if((d.role_decisions||[]).length&&!d.decisions.length)$('trace').innerHTML='';
 $('trace').insertAdjacentHTML('beforeend',(d.role_decisions||[]).map(x=>`<div class="tool"><b>${esc(ROLES[x.role]?.name||x.role)}</b> <small>${x.decisions.map(c=>`${c.chooser==='model'?'model '+esc(c.model):'policy fallback, no model'} chose option ${c.rank_in_options} of ${c.options.length}: ${esc(c.label)}`).join(' / ')}</small><br>Tools exposed to this role: ${x.tools.map(esc).join(', ')}<details><summary>Tool trace and unverified model words</summary><pre>${esc(JSON.stringify(x.trace,null,2))}</pre>${x.decisions.map(c=>`<p>${esc(c.model_reason_unverified)}</p>`).join('')}</details></div>`).join(''));return d;
}
async function loadCurriculum(){await ensureAtlas();const d=await api(`curriculum?subject=${encodeURIComponent(curriculum.subject)}&q=${encodeURIComponent(curriculum.q)}&offset=${curriculum.offset}`);
 $('subjects').innerHTML=[{name:'',count:1590},...d.subjects].map(s=>`<button class="subject ${s.name===curriculum.subject?'selected':''}" data-subject="${esc(s.name)}">${esc(s.name||'All subjects')} <small>${s.count}</small></button>`).join('');$('subjects').querySelectorAll('button').forEach(b=>b.onclick=()=>{curriculum.subject=b.dataset.subject;curriculum.offset=0;loadCurriculum().catch(e=>notice(e.message));});
 $('curriculum-count').textContent=`${Number(d.total).toLocaleString()} matching concept${d.total===1?'':'s'}. Each card says whether its goal has a lesson, a prototype task or parent checks.`;
 $('curriculum-grid').innerHTML=d.concepts.map(c=>`<button class="curriculum-card" data-goal="${esc(c.id)}"><span class="eyebrow">${esc(c.subject)}</span><h3>${esc(c.name)}</h3><p>${c.age_start!==null?`Source ages ${c.age_start} to ${c.age_end}`:'No source age range'}</p><span class="source-label">${c.lesson_available?'INTERACTIVE LESSON + TRANSFER CHECKS':c.activity_available?'PROTOTYPE TASK + PARENT CHECKS':c.criterion_count===0?'MAP AVAILABLE / SOURCE CRITERIA MISSING':'SOURCE-BACKED GUIDED INVESTIGATION'}</span><span class="card-arrow">Choose this goal ↗</span></button>`).join('')||'<p>No concepts match. Try a broader search.</p>';
 $('curriculum-grid').querySelectorAll('[data-goal]').forEach(b=>b.onclick=()=>changeGoal(b.dataset.goal));$('previous').disabled=curriculum.offset===0;$('more').disabled=curriculum.offset+24>=d.total;$('page-label').textContent=d.total?`${curriculum.offset+1} to ${Math.min(curriculum.offset+24,d.total)} of ${d.total}`:'No matches';
}
async function changeGoal(id){if(busy)return;try{plan=await api('goal',{concept_id:id});agentMode=false;automatic=0;emptyTask();tutor=null;await refreshTutor();render();tab('lab');notice('Goal selected. The route uses actual source prerequisites. Parent checks are not graded tests.');}catch(e){notice(e.message);}}
let timer;$('curriculum-search').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{curriculum.q=$('curriculum-search').value;curriculum.offset=0;loadCurriculum().catch(e=>notice(e.message));},250);};
 $('previous').onclick=()=>{curriculum.offset=Math.max(0,curriculum.offset-24);loadCurriculum().catch(e=>notice(e.message));};$('more').onclick=()=>{curriculum.offset+=24;loadCurriculum().catch(e=>notice(e.message));};
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(async()=>{try{const d=await api('search?q='+encodeURIComponent($('search').value));$('search-results').innerHTML=d.concepts.map(c=>`<button class="search-result" data-goal="${esc(c.id)}"><span>${esc(c.name)}</span><small>${esc(c.subject)} / choose this goal ↗</small></button>`).join('');$('search-results').querySelectorAll('[data-goal]').forEach(b=>b.onclick=()=>changeGoal(b.dataset.goal));}catch(e){notice(e.message);}},250);};
function renderComparison(){
 $('comparison').innerHTML=comparison.profiles.map((profile,side)=>`<article class="comparison-card"><p class="eyebrow">SYNTHETIC NOTEBOOK ${side===0?'A':'B'}</p><h3>${esc(profile.label)}</h3><p>Seeded software fixture, not a real child's performance.</p><p id="compare-next-${side}"><b>Next:</b> ${esc(profile.plan.selected?.title||'Review the route')}</p><div id="compare-graph-${side}"></div><div id="compare-task-${side}"><button class="text-button" data-compare="${side}">Try a live response in this notebook →</button></div></article>`).join('');
 comparison.profiles.forEach((p,i)=>drawGraph($('compare-graph-'+i),p.plan,null,{compact:true,soft:false}));document.querySelectorAll('[data-compare]').forEach(b=>b.onclick=()=>compareStep(Number(b.dataset.compare)));
}
async function compareStep(side,choice){const profile=comparison.profiles[side],old=$('compare-task-'+side);old.querySelectorAll('button').forEach(b=>b.disabled=true);try{const body={comparison_id:comparison.id,side};if(choice!==undefined){body.choice=choice;body.action=profile.action.action;}const d=await api('comparison/step',body);profile.plan=d.plan;profile.action=d.action;drawGraph($('compare-graph-'+side),d.plan,null,{compact:true,soft:false});$('compare-next-'+side).textContent='Next: '+(d.plan.selected?.title||'Review uncertainty');old.innerHTML=(d.result?`<div class="feedback">${esc(d.result.explanation)}</div>`:'')+(d.action?`<p class="source-label">${d.action.kind==='parent_check'?'PARENT REPORT':'GRADED PROTOTYPE TASK'}</p><h4>${esc(d.action.item.question)}</h4><div class="answers">${d.action.item.options.map((o,i)=>`<button class="answer" data-cchoice="${i}">${esc(o)}</button>`).join('')}</div>`:'<p>No further check. Review unresolved evidence.</p>');old.querySelectorAll('[data-cchoice]').forEach(b=>b.onclick=()=>compareStep(side,Number(b.dataset.cchoice)));notice('Comparison updated using a real response in its own synthetic learner graph.');}catch(e){notice(e.message);old.querySelectorAll('button').forEach(b=>b.disabled=false);}}
async function openComparison(){if(busy)return;busy=true;$('compare-start').disabled=true;try{comparison=await api('comparison',{});renderComparison();notice('Two controlled profiles opened. Initial task support is seeded and labelled synthetic.');}catch(e){notice(e.message);}finally{busy=false;$('compare-start').disabled=false;}}
 $('compare-start').onclick=openComparison;
 $('show-soft').onchange=()=>drawGraph($('map-view'),mapPlan(),inspectConcept,{soft:$('show-soft').checked});
 $('manual').onclick=()=>lessonRoute()?tutorStep(false):next(false);$('agent').onclick=()=>lessonRoute()?tutorStep(true):next(true);
 document.querySelectorAll('[data-expedition]').forEach(b=>b.onclick=()=>changeGoal(EXPEDITION));
 $('reset').onclick=async()=>{if(busy)return;try{await api('session',{});agentMode=false;automatic=0;emptyTask();await refresh();await loadNotes();notice('A fresh synthetic notebook is ready. The previous notebook was not deleted.');}catch(e){notice(e.message);}};
 $('export').onclick=async()=>{try{const d=await loadNotes();const u=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='trellis-learning-route.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){notice(e.message);}};
initWater($);
// ---------- the tutor loop: Scout checks, Tinker teaches, Lens tries a fresh transfer task ----------
const WAITS={diagnostic:'scout',recheck:'scout',lesson:'tinker',transfer:'lens'};
async function refreshTutor(){if(!lessonRoute()){tutor=null;return;}tutor=await api('tutor/state');roleView={due:tutor.task?null:tutor.due_role,waiting:tutor.task?WAITS[tutor.task.purpose]:null};}
function renderLessonRoom(){
 $('water-demo').hidden=true;$('general-context').hidden=true;$('tutor-studio').hidden=false;
 document.querySelector('.pill').textContent='THE FRACTION STUDIO';
 document.querySelectorAll('.autoguide,.autoguide+.small').forEach(x=>x.hidden=true);
 $('agent').innerHTML='Start the expedition <span>↗</span>';$('manual').textContent='Run the same roles without a model →';
 $('guide-note').textContent='Start uses the local model for each role. The second button runs the same role servers with a fixed rule and no model.';
 if(!$('live-trail').querySelector('.trail-step'))$('live-trail').innerHTML='<p class="small">Each role\u2019s tool calls appear here: the tools its MCP server exposed, the options it was offered and the one it chose.</p>';
 if(!tutor)return;
 renderRoles($('role-strip'),roleView);renderStations($('stations'),tutor.stations,tutor.concept);renderTutorQueries($('tutor-queries'),tutor);
 const due=tutor.due_role&&ROLES[tutor.due_role];
 $('next').innerHTML=`<span class="label">${tutor.task?'WAITING FOR YOUR ANSWER':'WHO IS UP NEXT'}</span><h3>${tutor.task?esc(tutor.task.activity.title):due?`${due.name}, ${due.job}`:'Review the route'}</h3><p class="small">${due&&!tutor.task?esc(due.does):''}</p>`;
 $('tutor-note').innerHTML=tutor.history.length?`<b>Latest step.</b> ${esc(tutor.history.at(-1).note)}`:'Scout reads the FalkorDB route first. Nothing is recorded until you answer.';
 $('agent').disabled=$('manual').disabled=busy||Boolean(tutor.task)||!due;
 if(!tutor.task&&!busy&&!$('task').querySelector('#feedback .feedback'))$('task').innerHTML=`<p class="eyebrow">${due?esc(due.name.toUpperCase())+' IS UP NEXT':'A PLACE TO PAUSE'}</p><h3>${due?esc(due.does):'No permitted step remains on this route right now.'}</h3><p>Each role runs in its own MCP server with only its own tools. Grading and recording are code, not agents. A correct answer here is evidence for one task, not proof of mastery.</p>`;
}
function showFraction(task){action=null;prepared=null;
 $('phase').textContent={diagnostic:'02 / SCOUT’S CHECK',recheck:'02 / A LATER CHECK',lesson:'03 / TINKER’S LESSON',transfer:'04 / LENS’S TRANSFER'}[task.purpose]||'02 / TASK';
 renderFraction($('task'),task,{submit:r=>fractionAnswer(task,r),hint:()=>api('tutor/hint',{task:task.task}).catch(e=>{notice(e.message);return null;})});}
async function tutorStep(useModel){
 if(busy)return;busy=true;
 try{await refreshTutor();}catch(e){notice(e.message);busy=false;return;}
 if(!tutor?.due_role){busy=false;render();return;}agentMode=useModel;render();
 notice(useModel?'The local model is choosing for this role. A cold start can take a minute.':'Policy mode: the same role servers and permissions, the first permitted option, and no model.');
 let result=null;
 try{const start=await api('tutor/step',{use_model:useModel});activeJob=start.id;
  $('agent-status').innerHTML='A role is working <button id="stop-investigation" class="text-button">Pause</button>';
  $('stop-investigation').onclick=()=>api('agent/jobs/'+activeJob+'/cancel',{}).catch(e=>notice(e.message));
  while(true){const job=await api('agent/jobs/'+start.id);
   const started=[...job.events].reverse().find(e=>e.type==='role_started'),done=job.events.some(e=>e.type==='role_finished');
   roleView={working:done?null:started?.role};renderRoles($('role-strip'),roleView);$('live-trail').innerHTML=tutorTrail(job.events);
   if(job.status==='completed'){result=job.result;break;}if(job.status!=='running')throw Error(job.error||'Stopped');
   await new Promise(r=>setTimeout(r,450));}
  const last=result.decisions?.at(-1);
  $('agent-status').textContent=last?`${ROLES[result.role].name} chose option ${last.rank_in_options} of ${last.options.length}${last.chooser==='policy'?' by policy, no model':' with the local model'}: ${last.label}.`:result.note||'';
  notice('');
 }catch(e){notice(e.message);$('agent-status').textContent='Stopped. Only answered tasks change the notebook.';}
 finally{activeJob=null;busy=false;await refreshTutor().catch(()=>{});render();if(result?.task)showFraction(result.task);}
}
async function fractionAnswer(task,response){
 try{const d=await api('tutor/answer',{task:task.task,response});
  roleView={flash:'assay'};renderRoles($('role-strip'),roleView);
  const next=d.next_role&&ROLES[d.next_role];
  const counted=d.counts_as_check?'Counted as a check.':d.purpose==='lesson'?(d.hinted?'Lesson practice with hints. Not counted as a check.':'Lesson practice. Not counted as a check.'):'A hinted answer is not counted as a check.';
  $('feedback').innerHTML=`<div class="feedback"><b>${d.correct?'That works.':'Let’s look a little closer.'}</b><br>${esc(d.explanation)}<br><small>${counted} Status: ${esc(d.status.replaceAll('_',' '))}.</small><p class="small">${esc(d.note)}</p>${d.rule?`<p class="small">${esc(d.rule)}</p>`:''}</div>${next?`<button id="continue" class="text-button">${esc(next.name)} is next: ${esc(next.does.toLowerCase())} →</button>`:''}`;
  if($('continue'))$('continue').onclick=()=>tutorStep(agentMode);
  await refresh();await refreshTutor();roleView.flash='notebook';render();
  return d;
 }catch(e){notice(e.message);return null;}
}
async function init(){try{try{const s=await api('session/state');if(!s.exists)await api('session',{});await refresh();}catch(e){if(!e.message.includes('Start a learning')&&!e.message.includes('Session not found'))throw e;await api('session',{});await refresh();}await refreshTutor();render();if(tutor?.task)showFraction(tutor.task);tab(location.hash.slice(1)||'curriculum');}catch(e){notice(e.message);$('next').innerHTML='<h3>The learning graph needs attention.</h3>';$('agent').disabled=true;$('manual').disabled=true;}}
init();
