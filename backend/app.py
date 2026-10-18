import asyncio
import json
import time
from uuid import uuid4
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from .core import ROOT, import_data, create_session, graph_for, plan, launch, submit, registry, all_activities, LOCK
from .agent import choose
from .investigation import learning_plan, set_goal, launch_check, submit_check, launch_parent_criterion, preview, comparison, comparison_child

@asynccontextmanager
async def lifespan(app):
    import_data()
    yield

app = FastAPI(title='Trellis',lifespan=lifespan)
agent_jobs={}

def token(request):
    value=request.cookies.get('trellis_session')
    if not value: raise HTTPException(401,'Start a learning notebook first.')
    return value

@app.exception_handler(ValueError)
async def invalid(request,e):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':str(e)},status_code=409)

@app.exception_handler(RedisError)
async def unavailable(request,e):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':'The learning graph is unavailable. No adaptive decision was made.'},status_code=503)

@app.get('/')
def home(): return FileResponse(ROOT/'web/index.html')

@app.post('/api/session')
def session(response:Response):
    value=create_session()
    response.set_cookie('trellis_session',value['token'],httponly=True,samesite='strict',max_age=604800)
    return {'created':True,'synthetic':True}

@app.get('/api/session/state')
def session_state(request:Request):
    """Whether this browser already has a notebook, without raising an error for a first visit."""
    value=request.cookies.get('trellis_session')
    if not value:return {'exists':False}
    try:graph_for(value);return {'exists':True}
    except ValueError:return {'exists':False}

@app.get('/api/plan')
def current(request:Request): return learning_plan(token(request))

class Launch(BaseModel):
    activity_id:str=Field(max_length=60)
    revision:int=Field(ge=0)

@app.post('/api/launch')
def activity(body:Launch,request:Request): return launch_check(token(request),body.activity_id,body.revision)

class Answer(BaseModel):
    action:str=Field(pattern='^[a-f0-9]{32}$')
    choice:int=Field(ge=0,le=20)

@app.post('/api/answer')
def answer(body:Answer,request:Request): return submit_check(token(request),body.action,body.choice)

@app.post('/api/agent')
async def agent(request:Request):
    try: result=await choose(token(request))
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(503,'The local agent could not finish. Graph-guided manual diagnostics remain available. '+str(e)[:140]) from e
    if 'action' in result:
        g=graph_for(token(request))
        g.query('CREATE (:Decision {id:$id,payload:$payload,revision:$revision})',
                {'id':result['action'].get('action') or result['action'].get('task'),'payload':json.dumps(result),'revision':result['action']['revision']})
    return result

@app.post('/api/agent/start')
async def start_agent(request:Request):
    owner=token(request)
    graph_for(owner)
    if any(j['owner']==owner and j['status']=='running' for j in agent_jobs.values()):
        raise HTTPException(409,'An investigation is already running in this notebook')
    for key in list(agent_jobs):
        if len(agent_jobs)<64:break
        if agent_jobs[key]['status']!='running':del agent_jobs[key]
    jid=uuid4().hex
    job={'owner':owner,'status':'running','events':[],'result':None}
    agent_jobs[jid]=job
    def emit(event):job['events'].append({'time':time.time(),**event})
    async def run():
        try:
            result=await choose(owner,emit)
            if 'action' in result:
                graph_for(owner).query('CREATE (:Decision {id:$id,payload:$payload,revision:$revision})',
                    {'id':result['action'].get('action') or result['action'].get('task'),'payload':json.dumps(result|{'events':job['events']}),'revision':result['action']['revision']})
            job.update(status='completed',result=result)
        except asyncio.CancelledError:
            job.update(status='cancelled',error='Investigation paused. Any completed evidence remains in the notebook.')
        except Exception as e:
            job.update(status='failed',error=str(e)[:240])
    job['task']=asyncio.create_task(run())
    return {'id':jid}

def owned_job(request,jid):
    job=agent_jobs.get(jid)
    if not job or job['owner']!=token(request):raise HTTPException(404,'Investigation not found in this notebook')
    return job

@app.get('/api/agent/jobs/{jid}')
def agent_progress(jid:str,request:Request):
    return {k:v for k,v in owned_job(request,jid).items() if k not in ('owner','task')}

@app.post('/api/agent/jobs/{jid}/cancel')
async def cancel_agent(jid:str,request:Request):
    job=owned_job(request,jid)
    if job['status']=='running':job['task'].cancel()
    return {'requested':True}

@app.get('/api/notebook')
def notebook(request:Request):
    g=graph_for(token(request)); rows=g.ro_query('MATCH (o:Observation) RETURN o.id,o.item,o.choice,o.correct,o.time,o.purpose,o.rep,o.hinted,o.label,o.rubric ORDER BY o.time').result_set
    decisions=g.ro_query('MATCH (d:Decision) RETURN d.payload').result_set
    return {'observations':[dict(zip(['id','item','choice','correct','time','purpose','representation','hinted','label','rubric'],r)) for r in rows],
            'decisions':[json.loads(r[0]) for r in decisions],'plan':learning_plan(token(request)),
            'role_decisions':[json.loads(r[0]) for r in g.ro_query('MATCH (d:RoleDecision) RETURN d.payload ORDER BY d.time').result_set],
            'parent_observations':[dict(zip(['id','concept','criterion','response','source','time'],r)) for r in g.ro_query('MATCH (o:ReportedObservation) RETURN o.id,o.concept,o.criterion,o.response,o.source,o.time ORDER BY o.time').result_set],
            'attribution':'Marble Skill Taxonomy v1, Generative Spark, Inc. ODbL 1.0 database and CC BY-SA 4.0 content.',
            'scope':'Synthetic local notebook. Prototype tasks, not independently validated educational assessments.'}

@app.get('/api/search')
def search(q:str=''):
    from .core import db,BASE
    q=q.strip()[:80]
    if len(q)<2:return {'concepts':[]}
    rows=db().select_graph(BASE).ro_query('MATCH (c:Concept) WHERE toLower(c.name) CONTAINS $q '
                'RETURN c.id,c.name,c.subject LIMIT 20',{'q':q.lower()}).result_set
    supported={a['concept'] for a in all_activities()}
    return {'concepts':[{'id':r[0],'name':r[1],'subject':r[2],'activity_available':r[0] in supported} for r in rows]}

class Goal(BaseModel):
    concept_id:str=Field(max_length=80)

@app.post('/api/goal')
def goal(body:Goal,request:Request):return set_goal(token(request),body.concept_id)

class Recheck(Goal):
    criterion:int=Field(ge=0)
    revision:int=Field(ge=0)

@app.post('/api/recheck')
def recheck(body:Recheck,request:Request):
    return launch_parent_criterion(token(request),body.concept_id,body.criterion,body.revision)

@app.get('/api/curriculum')
def curriculum(subject:str='',offset:int=0,q:str=''):
    from .core import db,BASE
    g=db().select_graph(BASE)
    subjects=g.ro_query('MATCH (c:Concept) RETURN c.subject,count(c) ORDER BY c.subject').result_set
    where=' WHERE ($subject="" OR c.subject=$subject) AND ($q="" OR toLower(c.name) CONTAINS $q) '
    params={'subject':subject[:80],'q':q.lower().strip()[:80]}
    total=g.ro_query('MATCH (c:Concept)'+where+'RETURN count(c)',params).result_set[0][0]
    rows=g.ro_query('MATCH (c:Concept)'+where+'RETURN c.id,c.name,c.subject,c.age_start,c.age_end,size(c.criteria) '
                    'ORDER BY c.subject,c.name,c.id SKIP $offset LIMIT 24',params|{'offset':max(0,min(offset,1590))}).result_set
    ids={a['concept'] for a in all_activities()}
    lessons={a['concept'] for a in all_activities() if a['kind']=='lesson'}
    return {'total':total,'subjects':[{'name':r[0],'count':r[1]} for r in subjects],
            'concepts':[dict(zip(['id','name','subject','age_start','age_end','criterion_count'],r))|{'activity_available':r[0] in ids,'lesson_available':r[0] in lessons} for r in rows]}

FEATURED = '''MATCH (g:Concept)-[:REQUIRES*1..]->(c:Concept)
WITH g, collect(DISTINCT c) AS route
WITH g, size(route) AS size, [x IN route WHERE x.subject <> g.subject] AS other
RETURN g.id, g.name, g.subject, size, size(other), [x IN other | x.subject]
ORDER BY size(other) DESC, size DESC'''


OVERVIEW = '''MATCH (g:Concept)-[:REQUIRES*0..]->(c:Concept)
WITH g, collect(DISTINCT c) AS route
RETURN count(g), max(size(route)) - 1, sum(CASE WHEN size([x IN route WHERE x.subject <> g.subject]) > 0 THEN 1 ELSE 0 END)'''


@app.get('/api/overview')
def overview():
    """Curriculum-wide figures for the opening panel: concepts, connections, the largest route and how many goals have
    foundations in another subject. Computed live in FalkorDB; structure only, not learner evidence."""
    from .core import db,BASE
    g=db().select_graph(BASE)
    result=g.ro_query(OVERVIEW,timeout=5000)
    goals,largest,crossing=result.result_set[0]
    edges=g.ro_query('MATCH ()-[r:REQUIRES|BENEFITS_FROM]->() RETURN count(r)').result_set[0][0]
    return {'concepts':goals,'connections':edges,'largest_route':largest,'cross_subject_goals':crossing,
            'server_ms':result.run_time_ms,'query':OVERVIEW}


@app.get('/api/featured')
def featured():
    """Goals worth a first look, decided by one FalkorDB query over every route: the routes that cross the most
    subjects, and the deepest route. Display only; it does not change any learner's plan."""
    import time as _time
    from .core import db,BASE
    start=_time.perf_counter()
    result=db().select_graph(BASE).ro_query(FEATURED,timeout=5000)
    rows=result.result_set
    crossing=[r for r in rows if r[4]][:3]
    deepest=max(rows,key=lambda r:r[3])
    picks=[]
    for r in crossing+[deepest]:
        if r[0] in [p['id'] for p in picks]:continue
        picks.append({'id':r[0],'name':r[1],'subject':r[2],'route_size':r[3],'other_subject_count':r[4],
                      'other_subjects':sorted(set(r[5]))})
    return {'goals':picks,'query':FEATURED,'server_ms':result.run_time_ms,'wall_ms':round((_time.perf_counter()-start)*1000,2),
            'scope':'Curriculum structure only. Crossing subjects says where prerequisites come from, not difficulty.'}


@app.get('/api/constellation')
def constellation():
    from .core import db,BASE
    g=db().select_graph(BASE)
    nodes=g.ro_query('MATCH (c:Concept) RETURN c.id,c.name,c.subject ORDER BY c.subject,c.id').result_set
    edges=g.ro_query('MATCH (a:Concept)-[r:REQUIRES|BENEFITS_FROM]->(b:Concept) RETURN a.id,b.id,type(r) ORDER BY a.id,b.id').result_set
    return {'nodes':[dict(zip(['id','name','subject'],n)) for n in nodes],
            'edges':[dict(zip(['from','to','type'],e)) for e in edges],
            'scope':'Public curriculum connections, not learner evidence.'}

@app.post('/api/preview')
def hypothetical(body:Goal,request:Request):return preview(token(request),body.concept_id)

@app.post('/api/comparison')
def compare(request:Request):return comparison(token(request))

class CompareAction(BaseModel):
    comparison_id:str=Field(pattern='^[a-f0-9]{32}$')
    side:int=Field(ge=0,le=1)
    action:str|None=None
    choice:int|None=Field(default=None,ge=0,le=20)

@app.post('/api/comparison/step')
def compare_step(body:CompareAction,request:Request):
    child=comparison_child(token(request),body.comparison_id,body.side)
    result=None
    if body.action:
        if body.choice is None:raise ValueError('A response is required')
        result=submit_check(child,body.action,body.choice)
    p=learning_plan(child)
    action=launch_check(child,p['selected']['id'],p['revision']) if p['selected'] else None
    return {'result':result,'plan':p,'action':action}

# ---------- two learners, same fractions goal, different mistakes ----------
from .tutor import compare as fraction_compare

@app.post('/api/comparison/fractions')
def compare_fractions(request:Request):return fraction_compare.open_comparison(token(request))

class CompareAnswer(BaseModel):
    comparison_id:str=Field(pattern='^[a-f0-9]{32}$')
    side:int=Field(ge=0,le=1)
    task:str=Field(pattern='^[a-f0-9]{32}$')
    response:dict|None=None

@app.post('/api/comparison/fractions/answer')
def compare_fractions_answer(body:CompareAnswer,request:Request):
    if body.response is None:raise ValueError('A response is required')
    return fraction_compare.answer(token(request),body.comparison_id,body.side,body.task,body.response)

@app.post('/api/comparison/fractions/hint')
def compare_fractions_hint(body:CompareAnswer,request:Request):
    return fraction_compare.hint(token(request),body.comparison_id,body.side,body.task)

# ---------- adaptive tutor: Scout, Tinker and Lens around one fraction foundation at a time ----------
from .tutor import session as tutor
from .tutor.runner import step as tutor_step

@app.get('/api/tutor/state')
def tutor_state(request:Request):return tutor.status(token(request))

class TutorStep(BaseModel):
    use_model:bool=True

@app.post('/api/tutor/step')
async def tutor_start(body:TutorStep,request:Request):
    owner=token(request);graph_for(owner)
    if any(j['owner']==owner and j['status']=='running' for j in agent_jobs.values()):
        raise HTTPException(409,'A role is already working in this notebook')
    for key in list(agent_jobs):
        if len(agent_jobs)<64:break
        if agent_jobs[key]['status']!='running':del agent_jobs[key]
    jid=uuid4().hex
    job={'owner':owner,'status':'running','events':[],'result':None,'kind':'tutor'}
    agent_jobs[jid]=job
    def emit(event):job['events'].append({'time':time.time(),**event})
    async def run():
        try:job.update(status='completed',result=await tutor_step(owner,emit,body.use_model))
        except asyncio.CancelledError:job.update(status='cancelled',error='Paused. Completed evidence stays in the notebook.')
        except httpx_errors as e:job.update(status='failed',error='The local model is not reachable. Use the policy mode or start Ollama. '+str(e)[:120])
        except Exception as e:job.update(status='failed',error=str(e)[:240])
    job['task']=asyncio.create_task(run())
    return {'id':jid}

import httpx
httpx_errors=(httpx.ConnectError,httpx.TimeoutException)

class TutorAnswer(BaseModel):
    task:str=Field(pattern='^[a-f0-9]{32}$')
    response:dict

@app.post('/api/tutor/answer')
def tutor_answer(body:TutorAnswer,request:Request):
    if len(json.dumps(body.response))>2000:raise HTTPException(413,'Response too large')
    return tutor.answer(token(request),body.task,body.response)

class TutorHint(BaseModel):
    task:str=Field(pattern='^[a-f0-9]{32}$')

@app.get('/api/tutor/report')
def tutor_report(request:Request):return tutor.report(token(request))

@app.post('/api/tutor/hint')
def tutor_hint(body:TutorHint,request:Request):return tutor.hint(token(request),body.task)

app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
