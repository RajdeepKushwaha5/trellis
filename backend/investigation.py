"""Any-goal investigation, reported evidence and explainable graph-derived routes."""
import json
import time
from uuid import uuid4
from .core import graph_for, create_session, plan as task_plan, launch, submit, registry, all_activities, GOAL, LOCK, digest, RELEASE, SUPPORTED

READY = SUPPORTED | {'reported_ready'}


def set_goal(token, goal):
    g = graph_for(token)
    rows = g.query('MATCH (l:Learner {id:$learner}), (c:Concept {id:$goal}) '
                   'SET l.goal=c.id,l.revision=l.revision+1 RETURN c.id', {'learner':token,'goal':goal}).result_set
    if not rows: raise ValueError('Unknown learning goal')
    from .tutor.session import leave_step
    leave_step(token, 'Goal changed. The open step was left unanswered and recorded nothing.')
    return learning_plan(token)


def learning_plan(token):
    """Hard closure is complete. Soft links are shown as context and never block readiness."""
    g = graph_for(token); p = task_plan(token)
    reports = g.ro_query('MATCH (r:ParentReport) RETURN r.concept,r.criterion,r.response,r.source').result_set
    by = {n['id']:n for n in p['nodes']}
    for n in p['nodes']:
        n['task_status'] = n['status']
        n['reports'] = [{'criterion':r[1],'response':r[2],'source':r[3]} for r in reports if r[0]==n['id']]
        all_yes = bool(n['criteria']) and all(any(r['criterion']==i and r['response']=='yes' for r in n['reports']) for i in range(len(n['criteria'])))
        reported_no = any(r['response']=='no' for r in n['reports'])
        if n['task_status'] in SUPPORTED and reported_no: n['status']='conflicting'
        elif n['task_status']=='needs_check' and all_yes: n['status']='conflicting'
        elif n['task_status']=='unknown': n['status']='reported_ready' if all_yes else 'reported_uncertain' if n['reports'] else 'unknown'
        n['evidence_kind'] = 'observed task' if n['task_status']!='unknown' else 'parent report' if n['reports'] else 'no evidence'
    # Reachability, coverage and witnesses are computed by FalkorDB.
    from .reasoning import rank
    parents={n:[] for n in by}
    for edge in p['edges']:parents[edge['from']].append(edge['to'])
    coverage=p['graph_reasoning']['coverage']
    def witness(cid):return p['graph_reasoning']['witnesses'][cid]
    candidates=[]
    for old in p['candidates']:
        n=by[old['concept']]
        candidates.append({**old,'kind':'activity','missing':[i for i in parents[n['id']] if by[i]['status'] not in READY],
                           'reported_support':n['status']=='reported_ready','witness':witness(n['id'])})
    for n in p['nodes']:
        if n['status'] in READY:continue
        unanswered=[i for i in range(len(n['criteria'])) if not any(r['criterion']==i for r in n['reports'])]
        if not unanswered:continue
        # One source-authored criterion per check. No invented answer key or child score.
        candidates.append({'id':'check:'+n['id'],'concept':n['id'],'title':'Check: '+n['name'],'kind':'parent_check',
                           'coverage':coverage[n['id']],'depth':n['depth'],'missing':[i for i in parents[n['id']] if by[i]['status'] not in READY],
                           'criterion':unanswered[0],'reported_support':False,'witness':witness(n['id'])})
    candidates=rank(g,candidates,p['graph_reasoning']['queries'])
    p['candidates']=candidates;p['selected']=candidates[0] if candidates else None
    soft = g.ro_query('MATCH (c:Concept)-[r:BENEFITS_FROM]->(s:Concept) WHERE c.id IN $ids '
                      'RETURN c.id,s.id,s.name,r.reason', {'ids':list(by)}).result_set
    p['soft_edges']=[{'from':r[0],'to':r[1],'name':r[2],'reason':r[3],'strength':'soft'} for r in soft]
    p['supported_count']=sum(n['status'] in SUPPORTED for n in by.values())
    p['reported_count']=sum(n['status']=='reported_ready' for n in by.values())
    p['coverage_gaps']=[{'id':n['id'],'name':n['name'],'reason':'No source criteria and no prototype activity'} for n in by.values()
                        if not n['criteria'] and not any(a['concept']==n['id'] for a in all_activities())]
    p['activity_count']=len([a for a in all_activities() if a['concept'] in by])
    p['lesson_count']=len([a for a in all_activities() if a['kind']=='lesson' and a['concept'] in by])
    p['scope']='Parent reports are not graded performance. Task support is provisional. Source prerequisites may be incomplete.'
    p['fingerprint']=digest({'release':RELEASE,'goal':p['goal']['id'],'revision':p['revision'],'edges':p['edges']})
    p['route']={'goal':p['goal']['name'],'observed_support':[n['name'] for n in by.values() if n['status'] in SUPPORTED],
                'reported_support':[n['name'] for n in by.values() if n['status']=='reported_ready'],
                'uncertain':[n['name'] for n in by.values() if n['status'] not in READY],
                'next':p['selected'],'gaps':p['coverage_gaps'],'scope':p['scope'],'fingerprint':p['fingerprint']}
    return p


def launch_check(token, candidate_id, revision):
    with LOCK:
        p=learning_plan(token)
        if revision!=p['revision']:raise ValueError('State changed. Refresh the learning route.')
        candidate=next((a for a in p['candidates'] if a['id']==candidate_id),None)
        if candidate is None:raise ValueError('Diagnostic is not in the current eligible set')
        if candidate['kind']=='activity':
            result=launch(token,candidate_id,revision)
            return {**result,'kind':'activity','witness':candidate['witness'],'plan_fingerprint':p['fingerprint']}
        result=launch_parent_criterion(token,candidate['concept'],candidate['criterion'],revision)
        return result|{'witness':candidate['witness']}


def launch_parent_criterion(token, concept, criterion, revision):
    """Explicit parent recheck, scoped to the current goal. Does not broaden model tools."""
    p=learning_plan(token)
    if p['revision']!=revision:raise ValueError('State changed. Refresh the route.')
    n=next((n for n in p['nodes'] if n['id']==concept),None)
    if not n or type(criterion) is not int or not 0<=criterion<len(n['criteria']):raise ValueError('Invalid source criterion')
    action=uuid4().hex
    graph_for(token).query('CREATE (:ReportAction {id:$id,concept:$concept,criterion:$criterion,revision:$revision,goal:$goal,used:false})',
                          {'id':action,'concept':concept,'criterion':criterion,'revision':revision,'goal':p['goal']['id']})
    return {'action':action,'kind':'parent_check','revision':revision,'activity':{'id':'check:'+concept,'title':n['name']},
            'item':{'id':'criterion:'+str(criterion),'question':n['criteria'][criterion],
                    'options':['I have seen this independently','Not yet','I am not sure']},
            'source':'Marble source-authored evidence criterion. Parent-reported, not graded.',
            'plan_fingerprint':p['fingerprint']}


def submit_check(token, action, choice):
    with LOCK:
        g=graph_for(token)
        rows=g.ro_query('MATCH (a:ReportAction {id:$id}) RETURN a.concept,a.criterion,a.revision,a.used,a.result',{'id':action}).result_set
        if not rows:return submit(token,action,choice)
        cid,index,revision,used,result=rows[0]
        if used:return json.loads(result)
        if type(choice) is not int or choice not in range(3):raise ValueError('Invalid parent observation')
        if learning_plan(token)['revision']!=revision:raise ValueError('Stale action rejected. Refresh the route.')
        response=['yes','no','unsure'][choice]
        output={'kind':'parent_check','correct':None,'response':response,'concept':cid,'revision':revision+1,
                'explanation':'Recorded as a parent report. This is not a graded answer or proof of mastery.',
                'status':'reported','distinct_checks':None}
        rows=g.query('MATCH (l:Learner {id:$learner}), (a:ReportAction {id:$action}), (c:Concept {id:$concept}) '
             'WHERE l.revision=$expected AND a.used=false '
             'MERGE (r:ParentReport {id:$report_id}) SET r.concept=$concept,r.criterion=$criterion,r.response=$response,r.source="parent",r.time=$time '
             'MERGE (r)-[:ABOUT]->(c) CREATE (o:ReportedObservation {id:$oid,response:$response,criterion:$criterion,concept:$concept,source:"parent",time:$time}) '
             'CREATE (a)-[:PRODUCED]->(o) '
             'SET a.used=true,a.result=$result,l.revision=$revision RETURN l.revision',
             {'learner':token,'action':action,'concept':cid,'expected':revision,'report_id':cid+':'+str(index),
              'criterion':index,'response':response,'time':time.time(),'oid':uuid4().hex,'result':json.dumps(output),'revision':revision+1}).result_set
        if not rows:raise ValueError('Concurrent state change. Refresh the route.')
        return output


def preview(token, concept):
    before=learning_plan(token)
    if concept not in {n['id'] for n in before['nodes']}:raise ValueError('Preview must concern a concept in this route')
    temporary=uuid4().hex;graph=graph_for(token).copy('trellis_learner_'+temporary)
    try:
        graph.query('MATCH (l:Learner) SET l.id=$id',{'id':temporary})
        n=next(n for n in before['nodes'] if n['id']==concept)
        for i in range(len(n['criteria'])):
            graph.query('MERGE (r:ParentReport {id:$id}) SET r.concept=$concept,r.criterion=$i,r.response="yes",r.source="hypothetical"',
                        {'id':concept+':'+str(i),'concept':concept,'i':i})
        after=learning_plan(temporary)
        return {'hypothetical':True,'before':before['selected'],'after':after['selected'],'concept':concept,
                'changed':(before['selected'] or {}).get('id')!=(after['selected'] or {}).get('id'),
                'note':'A graph-copy planning preview of reported support, not evidence of learning. Actual notebook unchanged.'}
    finally:graph.delete()


def comparison_child(token, cid, side):
    if side not in (0,1):raise ValueError('Invalid profile')
    rows=graph_for(token).ro_query('MATCH (c:Comparison {id:$id}) RETURN c.left,c.right',{'id':cid}).result_set
    if not rows:raise ValueError('Comparison does not belong to this notebook')
    return rows[0][side]
