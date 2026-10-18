"""Frozen synthetic action-choice comparison; no claim of educational effectiveness.
Run: python -m backend.tutor.choice_eval [--model] [--limit N]
"""
import argparse,asyncio,hashlib,json,os,random,time
from pathlib import Path
import httpx
from ..core import ROOT,create_session,graph_for
from ..investigation import set_goal
from . import session as t, fractions as e
from .runner import options_for,decide,OPTIONS

FIXTURE=ROOT/'tests/fixtures/teaching-choice-v1.json'


def meaning(option):
    return 'probe:'+option[3]['diagnostic_id'] if option[2]=='tinker_probe' else option[3].get('strategy',option[2])


def aware(ctx,opts):
    # A real deterministic comparator: inspect the observed error, rather than always choosing position one.
    if ctx['observed_difficulty']=='placement':
        p=next((o for o in opts if meaning(o)=='probe:read-unit'),None)
        if p:return p
    return next((o for o in opts if o[3].get('strategy')),opts[0])


def seed(case):
    token=create_session()['token'];set_goal(token,'mt_NoB20kVa4w');g=graph_for(token)
    act=t.activities()[case['activity']];response=None;params=None
    for p in e.pool(t.family_of(act),case['rep'],act['params']):
        candidates=([{'choice':i} for i in range(3)] if 'choice' in e.solution(p) else
                    [{'shaded':[]}] if 'shaded' in e.solution(p) else
                    [{'tick':i} for i in range(p['t']*p['span']+1)])
        for a in candidates:
            if e.grade(p,a)['difficulty']==case['difficulty']:params,response=p,a;break
        if params:break
    if params is None:
        g.delete();raise ValueError('Unconstructable fixture '+case['id'])
    # Actual controller task and answer, using a known parameter item for this synthetic fixture.
    tid,_=t._issue(g,token,act,case['rep'],'diagnostic')
    g.query('MATCH (x:TaskIssue {id:$id}) SET x.params=$params,x.key=$key',{'id':tid,'params':json.dumps(params),'key':e.key(params)})
    state=t._tutor(g);state.update(state='diagnostic',task=tid,concept=act['concept'],activity=act['id'],
      scout={'goal_id':'mt_NoB20kVa4w','foundation_id':act['concept'],'activity_id':act['id']})
    t._save(g,state);t.answer(token,tid,response)
    return token,t.tinker_handoff(token)


async def run(use_model=False,limit=12):
    fixture=json.loads(FIXTURE.read_text(encoding='utf-8-sig'))
    result={'fixture_sha256':hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),'scope':fixture['scope'],
      'model':os.getenv('TRELLIS_MODEL','qwen2.5:7b') if use_model else None,'options':OPTIONS,'cases':[],
      'model_protocol':'terminal action choice after a shared controller history inspection; two shuffled orders per case. Full role MCP execution is covered separately by integration tests',
      'fixture_revision_note':'v2 replaces two unconstructable direction-error cases with generated off-by-one cases before the completed comparison. No valid result was reported for the initial fixture.'}
    async with httpx.AsyncClient(timeout=120) as http:
      if use_model:
        tags=(await http.get('http://127.0.0.1:11434/api/tags')).json()
        result['model_digest']=next((m['digest'] for m in tags['models'] if m['name']==result['model']),None)
      for case in fixture['cases'][:limit]:
        token=None
        try:
          token,ctx=seed(case)
          # Compare terminal actions after the same bounded history inspection for every strategy.
          history=t.tinker_inspect(token)['history'];ctx=t.tinker_handoff(token);ctx['inspected']={'history':history}
          opts=options_for('tinker',ctx,{})
          row={'id':case['id'],'difficulty':case['difficulty'],'acceptable':case['acceptable'],
            'first_permitted':meaning(opts[0]),'mistake_aware':meaning(aware(ctx,opts)),'model_orders':[]}
          if use_model:
            for order in range(2):
              offered=list(opts);random.Random(case['id']+str(order)).shuffle(offered)
              start=time.perf_counter()
              decision,usage=await decide(http,'tinker',result['model'],ctx,offered)
              chosen=next(o for o in offered if o[0]==decision['option'])
              row['model_orders'].append({'choice':meaning(chosen),'valid':True,'acceptable':meaning(chosen) in case['acceptable'],
                'offered_order':[o[0] for o in offered],'choice_position':[o[0] for o in offered].index(chosen[0])+1,
                'seconds':round(time.perf_counter()-start,3),'usage':usage,'reason_unverified':decision['reason']})
          result['cases'].append(row)
          print(case['id'],row['first_permitted'],row['mistake_aware'],[x['choice'] for x in row['model_orders']],flush=True)
        finally:
          if token:graph_for(token).delete()
    result['summary']={'cases':len(result['cases']),
      'first_permitted_acceptable':sum(c['first_permitted'] in c['acceptable'] for c in result['cases']),
      'mistake_aware_acceptable':sum(c['mistake_aware'] in c['acceptable'] for c in result['cases']),
      'model_trials':sum(len(c['model_orders']) for c in result['cases']),
      'model_acceptable':sum(r['acceptable'] for c in result['cases'] for r in c['model_orders']),
      'order_stable_cases':sum(len(c['model_orders'])==2 and c['model_orders'][0]['choice']==c['model_orders'][1]['choice'] for c in result['cases'])}
    output=ROOT/'evidence'/('teaching-choice-model.json' if use_model else 'teaching-choice-policy.json')
    output.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result['summary']))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model',action='store_true');p.add_argument('--limit',type=int,default=12)
 a=p.parse_args();asyncio.run(run(a.model,a.limit))
