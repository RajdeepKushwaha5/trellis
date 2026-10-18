"""Synthetic learner fixtures: a real controller task and a real scripted wrong answer of a chosen kind.
Used by the comparison page, the choice evaluation and browser checks. Never presented as a real child's data."""
import json
from ..core import create_session, graph_for
from ..investigation import set_goal
from . import session as t, fractions as e


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


def respond_with(token, tid, difficulty):
    """Answer a task the way a learner with this difficulty would; None answers correctly, 'any' answers wrongly."""
    p = t._task_row(graph_for(token), tid)['params']
    sol = e.solution(p)
    if difficulty is None:
        return t.answer(token, tid, sol)
    options = [{'choice': i} for i in range(3)] if 'choice' in sol else \
        [{'shaded': list(range(n))} for n in range(p['b'] * p['k'] + 1)] if 'shaded' in sol else \
        [{'tick': i} for i in range(p['t'] * p['span'] + 1)]
    for r in options:
        g = e.grade(p, r)
        if not g['correct'] and (difficulty == 'any' or g['difficulty'] == difficulty):
            return t.answer(token, tid, r)
    raise ValueError(f'No response with difficulty {difficulty}')


def recovery_episode():
    """A synthetic learner up to the point of recovery: an ambiguous placement, a check that points to counting
    marks, a lesson using 'Walk the gaps from zero', and a transfer check that still fails. Tinker is due next."""
    token, ctx = seed({'id': 'recovery', 'activity': 'line-first', 'rep': 'ticks', 'difficulty': 'placement'})
    try:
        probe = t.tinker_probe(token, 'read-unit', ctx['version'])
        respond_with(token, probe['task'], 'counted_marks')
        ctx = t.tinker_handoff(token)
        rep = next(r['id'] for r in ctx['representations'] if r['id'] in ('ticks', 'fine'))
        lesson = t.tinker_teach(token, rep, 'example_first', ctx['version'], 'walk-gaps')
        respond_with(token, lesson['task'], None)
        lens = t.lens_handoff(token)
        transfer = t.lens_transfer(token, lens['strategies'][0]['id'], lens['version'])
        respond_with(token, transfer['task'], 'any')
        return token
    except Exception:
        graph_for(token).delete()
        raise
