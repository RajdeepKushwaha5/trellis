"""Tutor controller. Owns the loop state, role permissions, grading (Assay) and evidence writes (Notebook).

Roles never grade, never write evidence and never see answer keys. They choose among options this controller
computes from FalkorDB results and the notebook, and every choice is re-validated here before it takes effect.
"""
import json
import os
import time
from uuid import uuid4

from ..core import ROOT, LOCK, graph_for, digest, current_activities
from . import fractions as engine
from . import graphq, pedagogy

CATALOG = ROOT / 'activities/fractions.json'
ROLE_TOOLS = {
    'scout': ('scout_route', 'scout_inspect', 'scout_choose'),
    'tinker': ('tinker_handoff', 'tinker_inspect', 'tinker_probe', 'tinker_teach'),
    'lens': ('lens_handoff', 'lens_transfer'),
}
DUE = {'idle': 'scout', 'advance': 'scout', 'paused': 'scout', 'teach_due': 'tinker', 'transfer_due': 'lens'}
WAITING = {'diagnostic': 'checking', 'teaching': 'teaching', 'transfer': 'transfer check', 'investigating': 'distinguishing check'}
OPENINGS = {'example_first': 'Show a worked example first, then let the learner practise',
            'try_first': 'Let the learner try first, then explain with the worked example'}
LESSON_BUDGET, TRANSFER_BUDGET, SCOUT_INSPECTS = 2, 4, 2
CHECKS = ('diagnostic', 'transfer', 'recheck')
SUPPORT_RULE = ('Supported for this objective (rule v2): since the last incorrect check, correct checks without hints '
                'on different items in at least two representations, at least one a transfer task chosen by Lens, and at '
                'least one answer the learner built (shading or placing a point). Lessons that only have picture choices '
                'need three such checks instead, so a guess is unlikely to pass. A product policy for this prototype, '
                'not a validated mastery threshold.')
# Answers the learner constructs, rather than picks from three options.
CONSTRUCTED = {('build', 'bar'), ('build', 'circle'), ('build', 'set'), ('number_line', 'ticks'), ('number_line', 'fine')}


def choice_only(act):
    return not any((family_of(act), r) in CONSTRUCTED for r in act['representations'])
RECHECK_SECONDS = int(os.getenv('TRELLIS_RECHECK_SECONDS', str(24 * 3600)))
SUPPORTED_STATES = ('supported_for_objective', 'supported_for_task')
# Plain meanings of the difficulty codes Assay records. Tinker and Lens see these; they describe one response only.
DIFFICULTY = {'unequal_parts': 'picked parts that were not all the same size',
              'wrong_count': 'picked equal parts, but the wrong number of them',
              'shade_count': 'shaded the wrong number of equal parts',
              'counted_marks': 'counted the marks on the number line instead of the gaps',
              'off_by_one': 'was one gap off on the number line',
              'from_right': 'counted from 1 back towards 0',
              'placement': 'placed the point at the wrong mark'}


def _public_log(log):
    return [{'name': q['name'], 'server_ms': q['server_ms'], 'rows': q['rows'], 'cypher': q['cypher']} for q in log]


def catalog():
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def family_of(activity):
    return next(o['family'] for o in catalog()['objectives'] if o['id'] == activity['objective'])


def activities():
    return {a['id']: a for a in catalog()['activities']}


def by_concept(concept):
    return next((a for a in catalog()['activities'] if a['concept'] == concept), None)


# ---------- persisted state ----------

def _blank():
    return {'state': 'idle', 'version': 0, 'activity': None, 'concept': None, 'task': None, 'scout': None,
            'tinker': None, 'lessons': [], 'probes': [], 'inspections': 0, 'transfers': 0, 'paused': {}, 'history': [], 'queries': []}


def _tutor(g):
    rows = g.ro_query('MATCH (t:Tutor {id:"tutor"}) RETURN t.data,t.version').result_set
    if not rows:
        return _blank()
    data = json.loads(rows[0][0])
    data['version'] = rows[0][1]
    data.setdefault('probes', [])
    data.setdefault('inspections', 0)
    return data


def _save(g, t, note=None):
    """Optimistic write: refuses if another action changed the tutor since it was read."""
    if note:
        t['history'] = (t['history'] + [{'time': time.time(), 'state': t['state'], 'note': note}])[-40:]
    expected = t['version']
    body = {k: v for k, v in t.items() if k != 'version'}
    rows = g.query('MERGE (t:Tutor {id:"tutor"}) ON CREATE SET t.version=0 WITH t WHERE t.version=$expected '
                   'SET t.data=$data,t.state=$state,t.version=$expected+1 RETURN t.version',
                   {'expected': expected, 'data': json.dumps(body), 'state': t['state']}).result_set
    if not rows:
        raise ValueError('The tutor moved on in another tab. Refresh before acting.')
    t['version'] = rows[0][0]
    return t


def _used(g):
    return {r[0] for r in g.ro_query('MATCH (x:TaskIssue) RETURN x.key').result_set}


def _revision(g, token):
    return g.ro_query('MATCH (l:Learner {id:$id}) RETURN l.revision', {'id': token}).result_set[0][0]


def _issue(g, token, act, rep, purpose, used=False, extra=None, want=None):
    """Draws a fresh, never-used task from the pool. The answer stays in the graph, server side."""
    current_activities(g)
    params = engine.pick(family_of(act), rep, act['params'], _used(g), seed=token + act['id'] + rep, want=want)
    tid = uuid4().hex
    made = g.query('MATCH (c:Concept {id:$concept}), (r:Representation {id:$representation}) '
            'CREATE (x:TaskIssue {id:$id,concept:$concept,activity:$activity,'
            'objective:$objective,family:$family,rep:$rep,key:$key,purpose:$purpose,params:$params,revision:$revision,'
            'used:$used,hints:0,extra:$extra,time:$time}) CREATE (x)-[:CHECKS]->(c) CREATE (x)-[:IN]->(r) RETURN x.id',
            {'id': tid, 'concept': act['concept'], 'activity': act['id'], 'objective': act['objective'],
             'representation': family_of(act) + ':' + rep,
             'family': family_of(act), 'rep': rep, 'key': engine.key(params), 'purpose': purpose,
             'params': json.dumps(params), 'revision': _revision(g, token), 'used': used,
             'extra': json.dumps(extra or {}), 'time': time.time()}).result_set
    if not made:
        raise ValueError('This notebook graph is missing the lesson structure. Refresh and try again.')
    return tid, params


def _task_row(g, tid):
    rows = g.ro_query('MATCH (x:TaskIssue {id:$id}) RETURN x.concept,x.activity,x.objective,x.family,x.rep,x.key,'
                      'x.purpose,x.params,x.revision,x.used,x.hints,x.result,x.extra', {'id': tid}).result_set
    if not rows:
        raise ValueError('Unknown task')
    keys = ['concept', 'activity', 'objective', 'family', 'rep', 'key', 'purpose', 'params', 'revision', 'used',
            'hints', 'result', 'extra']
    row = dict(zip(keys, rows[0]))
    row['params'] = json.loads(row['params'])
    row['extra'] = json.loads(row['extra'] or '{}')
    return row


def task_payload(g, tid):
    """Everything the browser may see for a task. No answer, solution or correctness for unanswered checks."""
    row = _task_row(g, tid)
    act = activities()[row['activity']]
    lesson = row['purpose'] == 'lesson'
    ladder = engine.hints(row['params']) if lesson else []
    out = {'task': tid, 'kind': 'fraction', 'purpose': row['purpose'], 'representation': row['rep'],
           'representation_label': engine.label(row['family'], row['rep']), 'concept': row['concept'],
           'activity': {'id': act['id'], 'title': act['title'], 'objective': act['objective']},
           'render': engine.public(row['params']), 'revision': row['revision'], 'answered': bool(row['used']),
           'hints_available': len(ladder), 'hints': ladder[:row['hints']], 'rubric': engine.RUBRIC,
           'hints_allowed': lesson, 'opening': row['extra'].get('opening'),
           'teaching_strategy': row['extra'].get('strategy'), 'investigation': row['extra'].get('investigation'),
           'separates': row['extra'].get('separates_text', [])}
    if lesson and row['extra'].get('example'):
        ex = _task_row(g, row['extra']['example'])
        out['example'] = engine.example(ex['params'])
    if row['used']:
        out['result'] = json.loads(row['result'])
    return out


# ---------- shared reads ----------

def status(token):
    g = graph_for(token)
    t = _tutor(g)
    acts = activities()
    from ..investigation import learning_plan
    p = learning_plan(token)
    ids = [n['id'] for n in p['nodes']]
    nodes = {n['id']: n for n in p['nodes']}
    log, now = [], time.time()
    suspected, hypotheses = graphq.suspects(g, ids, log), graphq.inferred(g, ids, log)
    due = {r[0]: r[1] for r in g.ro_query('MATCH (s:LearningState) WHERE s.status="supported_for_objective" '
                                          'RETURN s.id,s.recheck_after').result_set}
    route = []
    for a in acts.values():
        if a['concept'] not in nodes:
            continue
        status = nodes[a['concept']]['status']
        route.append({'activity': a['id'], 'title': a['title'], 'concept': a['concept'], 'status': status,
                      'suspect': suspected.get(a['concept']) if status not in SUPPORTED_STATES else None,
                      'inferred_from': hypotheses.get(a['concept']),
                      'paused_until': t['paused'].get(a['concept']) if t['paused'].get(a['concept'], 0) > now else None,
                      'recheck_after': due.get(a['concept']), 'recheck_due': bool(due.get(a['concept']) and due[a['concept']] <= now)})
    return {'state': t['state'], 'version': t['version'], 'due_role': DUE.get(t['state']),
            'waiting': WAITING.get(t['state']), 'activity': t['activity'], 'concept': t['concept'],
            'task': task_payload(g, t['task']) if t['state'] in WAITING and t['task'] else None,
            'lessons': t['lessons'], 'history': t['history'][-8:], 'stations': route, 'available': bool(route),
            'budgets': {'lessons': LESSON_BUDGET, 'transfers': TRANSFER_BUDGET}, 'rule': SUPPORT_RULE,
            'paused': t['paused'], 'decision_queries': t.get('queries', []), 'view_queries': _public_log(log),
            'scout': t['scout'],
            'investigation': graphq.teaching(g, t['concept'], t['activity'], log) if t['concept'] else None,
            'episode': episode_view(token)}


def report(token):
    """The parent's view: what happened per foundation, help used, difficulties seen, what is next, what comes back later."""
    g = graph_for(token)
    log = []
    rows = graphq.summary(g, log)
    titles = {a['id']: a['title'] for a in activities().values()}
    for r in rows:
        r['title'] = titles.get(r['activity'], r['activity'])
        r['difficulties'] = [DIFFICULTY.get(d, d) for d in r['difficulties']]
    st = status(token)
    later = [{'title': s['title'], 'when': s['paused_until'], 'why': 'paused after two lessons; a fresh start later'}
             for s in st['stations'] if s['paused_until']] + \
            [{'title': s['title'], 'when': s['recheck_after'], 'why': 'a later check of support, not proof of lasting learning'}
             for s in st['stations'] if s['recheck_after'] and not s['recheck_due']]
    # Why each foundation is marked supported, rebuilt from the graph's records, never from model text.
    receipts = []
    for station in st['stations']:
        if station['status'] != 'supported_for_objective':
            continue
        act = activities()[station['activity']]
        checks = graphq.receipt(g, station['concept'], log)
        built = [c for c in checks if (c['family'], c['rep']) in CONSTRUCTED]
        receipts.append({'title': station['title'], 'concept': station['concept'], 'checks': checks,
                         'items': len(checks), 'representations': sorted({c['representation'] for c in checks}),
                         'transfers': sum(c['purpose'] == 'transfer' for c in checks), 'built': len(built),
                         'items_needed': 3 if choice_only(act) else 2, 'rule': 'v2',
                         'later_check': station['recheck_after']})
    return {'activity': rows, 'receipts': receipts, 'return_later': sorted(later, key=lambda x: x['when']), 'due_role': st['due_role'],
            'stations': st['stations'], 'queries': _public_log(log),
            'scope': 'Synthetic notebook. Each line is observed task evidence, not a grade or a diagnosis.'}


def _require(t, role, version):
    if DUE.get(t['state']) != role:
        raise ValueError(f'It is not {role.capitalize()}\'s turn. The tutor is {WAITING.get(t["state"], t["state"])}.')
    if version != t['version']:
        raise ValueError('Stale handoff. The tutor state changed; refresh before acting.')


# ---------- Scout ----------

def scout_route(token):
    """Foundations on the current route that have a lesson, in the order FalkorDB ranked them."""
    from ..investigation import learning_plan
    g = graph_for(token)
    t = _tutor(g)
    p = learning_plan(token)
    acts, now, used = activities(), time.time(), _used(g)
    names = {n['id']: n['name'] for n in p['nodes']}
    nodes = {n['id']: n for n in p['nodes']}
    options = []
    for rank, c in enumerate(p['candidates']):
        if c['kind'] != 'activity' or c['id'] not in acts:
            continue
        if t['paused'].get(c['concept'], 0) > now:
            continue
        a = acts[c['id']]
        if not any(engine.remaining(family_of(a), r, a['params'], used) for r in a['representations']):
            continue
        options.append({'id': c['id'], 'title': acts[c['id']]['title'], 'concept': c['concept'],
                        'concept_name': names[c['concept']], 'graph_rank': len(options) + 1, 'overall_rank': rank + 1,
                        'coverage': c['coverage'],
                        'uncertain_prerequisites': len(c['missing']), 'evidence': nodes[c['concept']]['status'],
                        'witness': [names[i] for i in c['witness']], 'purpose': 'diagnostic'})
    rows = g.ro_query('MATCH (s:LearningState) WHERE s.status="supported_for_objective" AND s.recheck_after<=$now '
                      'RETURN s.id', {'now': now}).result_set
    for (cid,) in rows:
        a = by_concept(cid)
        if a and cid in nodes:
            options.append({'id': 'recheck:' + a['id'], 'title': 'Later check: ' + a['title'], 'concept': cid,
                            'concept_name': names[cid], 'graph_rank': None, 'overall_rank': None, 'coverage': None,
                            'uncertain_prerequisites': 0, 'evidence': 'supported_for_objective',
                            'witness': [names[i] for i in p['graph_reasoning']['witnesses'][cid]], 'purpose': 'recheck'})
    log = list(p['graph_reasoning']['queries'])
    ids = [n['id'] for n in p['nodes']]
    suspected, hypotheses = graphq.suspects(g, ids, log), graphq.inferred(g, ids, log)
    for o in options:
        o['depth'] = nodes[o['concept']]['depth']
        if o['concept'] in suspected and o['evidence'] not in SUPPORTED_STATES:
            o['suspect'] = suspected[o['concept']]
        if o['concept'] in hypotheses:
            o['inferred'] = hypotheses[o['concept']]
        o['reasons'] = _reasons(o)
    options = graphq.rank(g, options, log)
    n = 0
    for o in options:
        n += o['purpose'] != 'recheck'
        o['graph_rank'] = n if o['purpose'] != 'recheck' else None
    return {'goal': p['goal']['name'], 'goal_id': p['goal']['id'], 'revision': p['revision'],
            'version': t['version'], 'fingerprint': p['fingerprint'], 'options': options,
            'queries': _public_log(log),
            'policy': 'FalkorDB ranks: foundations below a recent difficulty first (nearest first), then those with no '
                      'unchecked prerequisites, then those not merely inferred, then widest reverse coverage. '
                      'Inferred support is a hypothesis that lowers priority; it is never recorded as evidence.'}


def _reasons(o):
    out = []
    if o.get('suspect'):
        s = o['suspect']
        out.append(f'{s["steps"]} prerequisite step{"s" if s["steps"] != 1 else ""} below {s["below_name"]}, '
                   'where the latest check was not yet right')
    if o.get('inferred'):
        out.append('inferred only: it sits below ' + ', '.join(o['inferred'][:2]) +
                   ', which has observed support. Checked later, not counted')
    if o.get('coverage'):
        out.append(f'{o["coverage"]} concept{"s" if o["coverage"] != 1 else ""} on this route depend{"" if o["coverage"] != 1 else "s"} on it')
    if o.get('uncertain_prerequisites'):
        n = o['uncertain_prerequisites']
        out.append(f'{n} of its own prerequisites {"is" if n == 1 else "are"} still unchecked')
    if o['purpose'] == 'recheck':
        out.append('supported earlier; due for a later check')
    return out


def scout_inspect(token, concept_id):
    from ..investigation import learning_plan
    p = learning_plan(token)
    n = next((n for n in p['nodes'] if n['id'] == concept_id), None)
    if not n:
        raise ValueError('Concept is outside this learning goal')
    a = by_concept(concept_id)
    return {'id': n['id'], 'name': n['name'], 'description': n['description'], 'criteria': n['criteria'],
            'status': n['status'], 'lesson': a and {'id': a['id'], 'title': a['title'], 'objective': a['objective'],
                                                    'representations': a['representations']}}


def scout_choose(token, option_id, version, source='scout'):
    with LOCK:
        g = graph_for(token)
        t = _tutor(g)
        if source == 'scout':
            _require(t, 'scout', version)
        elif t['state'] in WAITING:
            raise ValueError('Finish or leave the current task first.')
        route = scout_route(token)
        option = next((o for o in route['options'] if o['id'] == option_id), None)
        if not option:
            raise ValueError('That foundation is not in the current graph-ranked set')
        act = activities()[option_id.removeprefix('recheck:')]
        purpose = option['purpose']
        reps = act['representations']
        if purpose == 'recheck':
            # A later check starts with a representation other than the one used by the latest check.
            last = graphq.last_check(g, act['concept'], []).get('rep')
            reps = [r for r in reps if r != last] + [r for r in reps if r == last]
        tid = params = None
        for rep in reps:
            try:
                tid, params = _issue(g, token, act, rep, purpose)
                break
            except engine.Exhausted:
                continue
        if not tid:
            raise engine.Exhausted('No unused check remains for this foundation in this notebook.')
        t.update(state='diagnostic', activity=act['id'], concept=act['concept'], task=tid, lessons=[], transfers=0,
                 tinker=None, probes=[], inspections=0, episode_started=time.time())
        t['scout'] = {'goal_id': route['goal_id'], 'foundation_id': act['concept'], 'activity_id': act['id'],
                      'plan_fingerprint': route['fingerprint'], 'evidence_revision': route['revision'],
                      'witness_concepts': option['witness'], 'graph_rank': option['graph_rank'],
                      'uncertainty': 'not yet checked' if purpose == 'diagnostic' else 'later check of earlier support',
                      'allowed_activity_ids': [act['id']], 'chosen_by': source,
                      'reasons': option.get('reasons', []), 'title': act['title'],
                      'ranked': [{'id': o['id'], 'title': o['title'], 'concept_name': o['concept_name'],
                                  'graph_rank': o['graph_rank'], 'reasons': o.get('reasons', [])} for o in route['options']]}
        t['queries'] = route['queries']
        _save(g, t, f'{"Scout" if source == "scout" else "Manual choice"} chose {act["title"]} '
                    f'({"FalkorDB rank " + str(option["graph_rank"]) if option["graph_rank"] else "later check"}).')
        return task_payload(g, tid) | {'handoff': t['scout']}


# ---------- Tinker ----------

def tinker_handoff(token):
    g = graph_for(token)
    t = _tutor(g)
    log = []
    if t['state'] != 'teach_due':
        raise ValueError('There is nothing for Tinker to teach right now.')
    act = activities()[t['activity']]
    taught = {l['rep'] for l in t['lessons']}
    used = _used(g)
    pedagogy.ensure(g)
    g.query('MATCH (o:Observation)-[:ABOUT]->(:Concept {id:$c}), (h:DifficultyHypothesis) WHERE h.id=o.difficulty MERGE (o)-[:SUGGESTS]->(h)', {'c':t['concept']})
    investigation = graphq.teaching(g, t['concept'], act['id'], log)
    probe_options = graphq.probes(g, t['concept'], log) if len(t['probes']) < 1 else []
    probe_options = [d for d in probe_options if d['rep'] in act['representations'] and engine.remaining(family_of(act), d['rep'], act['params'], used)]
    # A lesson needs two unused items: one retired as the worked example and one to practise.
    open_reps = [r for r in act['representations']
                 if r not in taught and engine.remaining(family_of(act), r, act['params'], used) >= 2]
    status = _investigation_status(g, t, probe_options, log)
    tried = {x['id'] for x in status['tried_strategies']}
    strategies = [s for s in investigation['strategies'] if s['id'] not in tried and any(r in open_reps for r in s['reps'])]
    if status['required']:
        # The controller requires a distinguishing check first; Tinker still chooses which one.
        open_reps, strategies = [], []
    return {'handoff': t['scout'], 'version': t['version'], 'objective': act['objective'],
            'objective_text': next(o['text'] for o in catalog()['objectives'] if o['id'] == act['objective']),
            'representations': [{'id': r, 'label': engine.label(family_of(act), r), 'taught_before': r in taught}
                                for r in open_reps],
            'openings': [{'id': k, 'label': v} for k, v in OPENINGS.items()],
            'previous_lessons': t['lessons'], 'lesson_budget': LESSON_BUDGET,
            'investigation': investigation,
            'teaching_strategies': strategies, 'investigation_status': status,
            'probe_options': probe_options, 'probe_budget_remaining': max(0,1-len(t['probes'])),
            'inspection_available': t['inspections'] < 1,
            **_difficulty(g, t['concept'], log), 'queries': _public_log(log),
            'boundary': 'Tinker teaches. It cannot see transfer tasks, grade, or mark anything learned.'}


def _investigation_status(g, t, probe_options, log):
    """What the evidence in this episode allows. Investigation is required when the latest mistake is linked to an
    ambiguous explanation, no distinguishing check has been asked yet, and one is available."""
    since = t.get('episode_started', 0)
    latest = graphq.latest_mistake(g, t['concept'], since, log)
    # A lesson still in progress has not failed yet, so its strategy is not listed as already tried.
    finished = t['lessons'][:-1] if t['state'] == 'teaching' else t['lessons']
    tried = graphq.tried_strategies(g, [l['task'] for l in finished], log)
    probe_done = len(t['probes']) >= 1
    outcome = None
    if probe_done:
        row = g.ro_query('MATCH (x:TaskIssue {id:$id})-[:PRODUCED]->(o:Observation) RETURN o.correct,o.difficulty',
                         {'id': t['probes'][-1]}).result_set
        if row:
            correct, code = row[0]
            if correct or not code:
                outcome = {'kind': 'inconclusive', 'text': 'The distinguishing check was answered correctly, so it did '
                           'not single out one explanation. Tinker teaches for the original mistake.'}
            elif code in pedagogy.AMBIGUOUS:
                outcome = {'kind': 'inconclusive', 'text': 'The distinguishing check was still ambiguous. Tinker '
                           'teaches for the original mistake.'}
            else:
                outcome = {'kind': 'pointed', 'text': 'The distinguishing check pointed to: '
                           + pedagogy.HYPOTHESES.get(code, code) + '.'}
    ambiguous = bool(latest.get('ambiguous'))
    required = ambiguous and not probe_done and bool(probe_options)
    note = None
    if required:
        note = ('The latest mistake does not say why, so the controller requires one distinguishing check before '
                'teaching. Tinker chooses which check.')
    elif ambiguous and not probe_done:
        note = ('A distinguishing check would help, but none is available here, so Tinker teaches using '
                'strategies for the original mistake.')
    return {'required': required, 'ambiguous': ambiguous, 'probe_done': probe_done, 'probe_outcome': outcome,
            'latest_explanation': latest.get('text'), 'note': note,
            'tried_strategies': [x | {'why': 'already tried in this episode, and the next check was not yet right'}
                                 for x in tried]}


def episode_view(token):
    """The current foundation's episode as the graph records it: each answer, what it suggested, what was tried."""
    g = graph_for(token)
    t = _tutor(g)
    if not t['concept']:
        return None
    log = []
    steps = graphq.episode(g, t['concept'], t.get('episode_started', 0), log)
    # The episode's status is shown in every state; probes only count as available while Tinker is due.
    probes = []
    if t['state'] == 'teach_due' and len(t['probes']) < 1:
        act = activities()[t['activity']]
        used = _used(g)
        probes = [d for d in graphq.probes(g, t['concept'], log)
                  if d['rep'] in act['representations'] and engine.remaining(family_of(act), d['rep'], act['params'], used)]
    status = _investigation_status(g, t, probes, log)
    if t['state'] != 'teach_due':
        status['required'], status['note'] = False, None
    return {'concept': t['concept'], 'activity': t['activity'], 'state': t['state'], 'steps': steps, 'status': status,
            'queries': _public_log(log)}


def _difficulty(g, concept, log):
    rows = graphq.history(g, concept, log)
    last = next((r for r in rows if r['purpose'] in (*CHECKS, 'probe')), {})
    return {'observed_difficulty': last.get('difficulty'), 'difficulty_meaning': DIFFICULTY.get(last.get('difficulty')),
            'difficulty_representation': last.get('representation')}


def tinker_inspect(token):
    """One bounded history read, with no answer keys or task parameters."""
    with LOCK:
        g = graph_for(token)
        t = _tutor(g)
        if t['state'] != 'teach_due' or t['inspections'] >= 1:
            raise ValueError('History inspection is unavailable or its budget is used')
        log = []
        rows = graphq.history(g, t['concept'], log)
        t['inspections'] += 1
        _save(g, t, 'Tinker inspected recent responses before deciding.')
        return {'history': rows, 'version': t['version'], 'queries': _public_log(log)}


def tinker_probe(token, diagnostic_id, version):
    """At most one fresh distinguishing probe per foundation episode, never support evidence."""
    with LOCK:
        g = graph_for(token)
        t = _tutor(g)
        _require(t, 'tinker', version)
        ctx = tinker_handoff(token)
        probe = next((p for p in ctx['probe_options'] if p['id'] == diagnostic_id), None)
        if not probe:
            raise ValueError('Diagnostic is not eligible or its one-probe budget is used')
        act = activities()[t['activity']]
        # Prefer an item whose wrong answers separate the explanations this probe is meant to tell apart.
        open_codes = sorted(set(probe['distinguishes']) - {'placement'})
        tid, params = _issue(g, token, act, probe['rep'], 'probe', want=open_codes,
                             extra={'investigation': ctx['investigation'], 'open': open_codes})
        separates = sorted(engine.reveals(params) & set(open_codes))
        g.query('MATCH (x:TaskIssue {id:$id}) SET x.extra=$extra', {'id': tid, 'extra': json.dumps(
            {'investigation': ctx['investigation'], 'open': open_codes, 'separates': separates,
             'separates_text': [pedagogy.HYPOTHESES[c] for c in separates]})})
        g.query('MATCH (x:TaskIssue {id:$task}), (d:Diagnostic {id:$diagnostic}) CREATE (x)-[:USES_DIAGNOSTIC]->(d)',
                {'task': tid, 'diagnostic': diagnostic_id})
        t['probes'].append(tid)
        t.update(state='investigating', task=tid, queries=ctx['queries'])
        _save(g, t, 'Tinker requested a distinguishing check: ' + probe['title'] + '. Not counted towards support.')
        return task_payload(g, tid)


def tinker_teach(token, representation, opening, version, strategy=None):
    with LOCK:
        g = graph_for(token)
        t = _tutor(g)
        _require(t, 'tinker', version)
        act = activities()[t['activity']]
        if representation not in act['representations'] or representation in {l['rep'] for l in t['lessons']}:
            raise ValueError('That representation is not allowed for this lesson')
        if opening not in OPENINGS:
            raise ValueError('Unknown lesson opening')
        if len(t['lessons']) >= LESSON_BUDGET:
            raise ValueError('Lesson budget used')
        ctx = tinker_handoff(token)
        if ctx['investigation_status']['required']:
            raise ValueError('Investigation is required first: the latest mistake is ambiguous and no distinguishing '
                             'check has been asked in this episode.')
        if strategy and strategy in {x['id'] for x in ctx['investigation_status']['tried_strategies']}:
            raise ValueError('That strategy was already tried in this episode. Choose a different approach.')
        selected_strategy = next((s for s in ctx['teaching_strategies'] if s['id'] == strategy and representation in s['reps']), None)
        if strategy and not selected_strategy:
            raise ValueError('Strategy is not connected to the current evidence or representation')
        # The worked example is retired from future checks.
        log = list(ctx['queries'])
        _difficulty(g, t['concept'], log)
        t['queries'] = _public_log(log)
        ex, _ = _issue(g, token, act, representation, 'example', used=True)
        tid, _ = _issue(g, token, act, representation, 'lesson', extra={'opening': opening, 'example': ex, 'strategy': selected_strategy, 'investigation': ctx['investigation']})
        t['lessons'].append({'rep': representation, 'opening': opening, 'task': tid, 'strategy': strategy})
        if strategy:
            g.query('MATCH (x:TaskIssue {id:$task}), (s:TeachingStrategy {id:$strategy}) CREATE (x)-[:USES_STRATEGY]->(s)', {'task':tid,'strategy':strategy})
        t.update(state='teaching', task=tid)
        _save(g, t, f'Tinker chose {engine.label(family_of(act), representation)}, {opening.replace("_", " ")}.')
        return task_payload(g, tid)


# ---------- Lens ----------

def _transfer_reps(g, t, log):
    """Lens's permitted strategies, from the representations this lesson OFFERS and the clean correct checks
    already in this run (both read from the learner graph)."""
    act = activities()[t['activity']]
    fam = family_of(act)
    since = graphq.last_wrong_time(g, t['concept'], log)
    rows = graphq.strategies(g, act['id'], t['concept'], since, log)
    last = graphq.last_check(g, t['concept'], log)
    taught = t['lessons'][-1]['rep'] if t['lessons'] else None
    used = _used(g)
    varied = sum(1 for r in rows if r['clean_correct']) >= 2
    out = []
    for r in rows:
        reason = None
        if r['rep'] == taught:
            reason = 'same representation as the lesson just taught'
        elif not t['lessons'] and r['rep'] == last.get('rep'):
            reason = 'same representation as the check just answered'
        elif r['clean_correct'] and not varied:
            reason = 'already used by a correct check in this run'
        left = engine.remaining(fam, r['rep'], act['params'], used)
        if not reason and not left:
            reason = 'no unused tasks remain'
        out.append({'id': r['rep'], 'label': r['label'], 'remaining': left, 'excluded': reason,
                    'clean_correct_in_run': r['clean_correct']})
    return out


def lens_handoff(token):
    g = graph_for(token)
    t = _tutor(g)
    if t['state'] != 'transfer_due':
        raise ValueError('There is no transfer check to choose right now.')
    log = []
    strategies = _transfer_reps(g, t, log)
    return {'handoff': t['tinker'] or {'concept_id': t['concept'], 'objective_id': activities()[t['activity']]['objective'],
                                       'lesson_attempt_id': None, 'used_item_ids': [], 'hinted': False,
                                       'transfer_pool_id': activities()[t['activity']]['objective'] + '-transfer'},
            'version': t['version'], 'teaching_representation': t['lessons'][-1]['rep'] if t['lessons'] else None,
            'teaching_opening': t['lessons'][-1]['opening'] if t['lessons'] else None,
            **_difficulty(g, t['concept'], log), 'queries': _public_log(log),
            'strategies': [s for s in strategies if not s['excluded']],
            'excluded': [s for s in strategies if s['excluded']], 'rule': SUPPORT_RULE,
            'boundary': 'Lens picks the kind of transfer task. It never sees the task parameters or answers.'}


def lens_transfer(token, representation, version):
    with LOCK:
        g = graph_for(token)
        t = _tutor(g)
        _require(t, 'lens', version)
        log = []
        allowed = [s['id'] for s in _transfer_reps(g, t, log) if not s['excluded']]
        if representation not in allowed:
            raise ValueError('That transfer strategy is not permitted now')
        act = activities()[t['activity']]
        tid, _ = _issue(g, token, act, representation, 'transfer')
        t['transfers'] += 1
        t.update(state='transfer', task=tid, queries=_public_log(log))
        _save(g, t, f'Lens chose a transfer task using {engine.label(family_of(act), representation)}.')
        return task_payload(g, tid)


# ---------- pause when no permitted move remains ----------

def leave_step(token, why):
    """Close any open loop step without evidence. An unanswered task becomes stale and can no longer be answered."""
    with LOCK:
        g = graph_for(token)
        t = _tutor(g)
        if t['state'] in ('idle', 'advance', 'paused'):
            return t
        t.update(state='idle', task=None, activity=None, concept=None, lessons=[], transfers=0, scout=None, tinker=None)
        return _save(g, t, why)


def pause_if_stuck(token, why):
    g = graph_for(token)
    t = _tutor(g)
    return _pause(g, t, why)


def _pause(g, t, why):
    t['paused'][t['concept']] = time.time() + RECHECK_SECONDS
    t.update(state='paused', task=None)
    _save(g, t, why)
    return t


# ---------- learner actions: hint and answer (controller only) ----------

def hint(token, tid):
    with LOCK:
        g = graph_for(token)
        row = _task_row(g, tid)
        t = _tutor(g)
        if row['purpose'] != 'lesson':
            raise ValueError('Hints are only part of lessons. Checks are answered without help.')
        if row['used'] or t['task'] != tid:
            raise ValueError('This lesson task is finished')
        ladder = engine.hints(row['params'])
        if row['hints'] >= len(ladder):
            raise ValueError('No more hints for this task')
        g.query('MATCH (x:TaskIssue {id:$id}) SET x.hints=x.hints+1', {'id': tid})
        return {'hint': ladder[row['hints']], 'shown': row['hints'] + 1, 'available': len(ladder)}


def answer(token, tid, response):
    with LOCK:
        g = graph_for(token)
        row = _task_row(g, tid)
        if row['used']:
            if row['result']:
                return json.loads(row['result'])
            raise ValueError('This answer is still being recorded. Refresh in a moment.')
        if row['purpose'] == 'example':
            raise ValueError('A worked example is not answered')
        t = _tutor(g)
        if t['task'] != tid or t['state'] not in WAITING:
            raise ValueError('Stale task. It is no longer the current step.')
        revision = _revision(g, token)
        if revision != row['revision']:
            raise ValueError('Stale task rejected. The evidence changed since it was issued.')
        graded = engine.grade(row['params'], response)   # Assay
        concept, purpose, hinted = row['concept'], row['purpose'], row['hints'] > 0
        check = purpose in CHECKS
        log = []
        prior = g.ro_query('MATCH (s:LearningState {id:$id}) RETURN s.status,s.correct_items,s.wrong',
                           {'id': concept}).result_set
        old_status, items, wrong = prior[0] if prior else ('unknown', [], 0)
        supported, evidence = False, None
        if check:
            # Rule v1 over the graph: the streak FalkorDB returns, plus this response.
            before = graphq.streak(g, concept, log)
            if graded['correct'] and not hinted:
                keys, reps = set(before['keys']) | {row['key']}, set(before['reps']) | {row['rep']}
                transfers = before['transfers'] + (purpose == 'transfer')
            else:
                keys, reps, transfers = set(), set(), 0
            act_now = activities()[row['activity']]
            built = any((family_of(act_now), r) in CONSTRUCTED for r in reps)
            enough = len(keys) >= 3 if choice_only(act_now) else (len(keys) >= 2 and built)
            supported = bool(graded['correct'] and not hinted and enough and len(reps) >= 2 and transfers >= 1)
            if purpose == 'recheck' and graded['correct'] and old_status == 'supported_for_objective':
                supported = True
            evidence = {'clean_correct_items': len(keys), 'representations': sorted(reps), 'transfer_checks': transfers,
                        'built_answer': built, 'items_needed': 3 if choice_only(act_now) else 2}
            status = 'supported_for_objective' if supported else 'needs_check'
            if graded['correct'] and not hinted:
                items = sorted(set((items or []) + [row['key']]))
            wrong = (wrong or 0) + (not graded['correct'])
        else:
            status = old_status if old_status != 'unknown' else 'needs_check'
        # Notebook: the observation, linked to its task and concept, in one atomic write.
        updated = g.query(
            'MATCH (l:Learner {id:$learner}), (x:TaskIssue {id:$task}), (c:Concept {id:$concept}) '
            'WHERE l.revision=$expected AND x.used=false '
            'MERGE (s:LearningState {id:$concept}) SET s.status=$status,s.correct_items=$items,s.wrong=$wrong,'
            's.recheck_after=CASE WHEN $status="supported_for_objective" THEN $recheck ELSE s.recheck_after END '
            'MERGE (l)-[:HAS_STATE]->(s) MERGE (s)-[:ABOUT]->(c) '
            'CREATE (o:Observation {id:$oid,item:$key,choice:$response,correct:$correct,rubric:$rubric,time:$time,'
            'purpose:$purpose,rep:$rep,hinted:$hinted,label:$label,activity:$activity,difficulty:$difficulty}) '
            'CREATE (s)-[:DERIVED_FROM]->(o) CREATE (x)-[:PRODUCED]->(o) CREATE (o)-[:ABOUT]->(c) '
            'SET x.used=true,l.revision=$revision RETURN l.revision',
            {'learner': token, 'task': tid, 'concept': concept, 'expected': revision, 'status': status,
             'items': items or [], 'wrong': wrong or 0, 'recheck': time.time() + RECHECK_SECONDS, 'oid': uuid4().hex,
             'key': row['key'], 'response': json.dumps(response), 'correct': graded['correct'],
             'rubric': engine.RUBRIC, 'time': time.time(), 'purpose': purpose, 'rep': row['rep'], 'hinted': hinted,
             'label': engine.public(row['params'])['prompt'], 'activity': row['activity'],
             'difficulty': graded['difficulty'], 'revision': revision + 1}).result_set
        if not updated:
            raise ValueError('Concurrent state change. Refresh the route.')
        pedagogy.link_observation(g, tid)
        # The next role due, decided from the evidence just written.
        act = activities()[row['activity']]
        name = act['title']
        if purpose == 'probe':
            if graded['correct'] or not graded['difficulty']:
                finding = 'It was answered correctly, so it did not single out one explanation; Tinker will teach for the original mistake.'
            elif graded['difficulty'] in pedagogy.AMBIGUOUS:
                finding = 'It was still ambiguous; Tinker will teach for the original mistake.'
            else:
                finding = 'It pointed to: ' + pedagogy.HYPOTHESES.get(graded['difficulty'], graded['difficulty']) + '.'
            t['state'], note = 'teach_due', 'Distinguishing check recorded. ' + finding + ' It does not count towards support.'
        elif purpose == 'lesson':
            t['tinker'] = {'concept_id': concept, 'lesson_attempt_id': tid, 'objective_id': row['objective'],
                           'used_item_ids': [l['task'] for l in t['lessons']], 'hinted': hinted,
                           'transfer_pool_id': row['objective'] + '-transfer', 'practice_correct': graded['correct']}
            if graded['correct']:
                t['state'], note = 'transfer_due', f'Practice correct{" with hints" if hinted else ""}. Lens will choose a fresh transfer task.'
            elif len(t['lessons']) < LESSON_BUDGET:
                t['state'], note = 'teach_due', 'Practice not yet right. Tinker will try a different representation.'
            else:
                t['state'], note = 'transfer_due', 'Both lessons used. Lens will check once more without hints.'
        elif supported:
            t['state'], note = 'advance', (f'{name}: correct on a later check. One more observation, not proof of lasting learning.'
                                           if purpose == 'recheck' else
                                           f'{name}: supported for this objective under rule v1. Scout will pick the next foundation.')
        elif graded['correct']:
            if t['transfers'] < TRANSFER_BUDGET:
                t['state'], note = 'transfer_due', 'Correct. Rule v1 needs one more check in a different representation.'
            else:
                t['state'], note = 'paused', 'Transfer budget used without meeting rule v1. Paused for a later check.'
        else:
            if purpose in ('diagnostic', 'recheck'):
                t['state'], note = 'teach_due', 'This check was not yet right. Scout hands the foundation to Tinker to teach.'
            elif len(t['lessons']) < LESSON_BUDGET:
                t['state'], note = 'teach_due', 'Transfer not yet right. Revisiting with a different lesson.'
            else:
                t['state'], note = 'paused', ('Two lessons and the transfer checks did not settle it. Paused; Scout will '
                                              'look at the foundations below it.')
        t['task'] = None
        if t['state'] == 'transfer_due' and not [s for s in _transfer_reps(g, t, log) if not s['excluded']]:
            t['state'], note = 'paused', note + ' No permitted transfer task remains, so the tutor pauses here.'
        if t['state'] == 'paused':
            t['paused'][concept] = time.time() + RECHECK_SECONDS
        t['queries'] = _public_log(log)
        output = {'kind': 'fraction', 'purpose': purpose, 'correct': graded['correct'], 'value': graded['value'],
                  'explanation': graded['explanation'], 'difficulty': graded['difficulty'], 'hinted': hinted,
                  'status': status, 'concept': concept, 'revision': revision + 1, 'next_state': t['state'],
                  'next_role': DUE.get(t['state']), 'note': note, 'rubric': engine.RUBRIC, 'evidence': evidence,
                  'counts_as_check': check and not hinted, 'rule': SUPPORT_RULE if supported else None,
                  'queries': [{'name': q['name'], 'server_ms': q['server_ms']} for q in log]}
        g.query('MATCH (x:TaskIssue {id:$id}) SET x.result=$result', {'id': tid, 'result': json.dumps(output)})
        _save(g, t, note)
        return output


def record_decision(token, payload):
    graph_for(token).query('CREATE (:RoleDecision {id:$id,time:$time,payload:$payload,hash:$hash})',
                           {'id': uuid4().hex, 'time': time.time(), 'payload': json.dumps(payload),
                            'hash': digest(payload)})


# ---------- the permission table, enforced for every call ----------

TOOLS = {
    'scout_route': lambda token, args: scout_route(token),
    'scout_inspect': lambda token, args: scout_inspect(token, args['concept_id']),
    'scout_choose': lambda token, args: scout_choose(token, args['activity_id'], args['version']),
    'tinker_handoff': lambda token, args: tinker_handoff(token),
    'tinker_teach': lambda token, args: tinker_teach(token, args['representation'], args['opening'], args['version'], args.get('strategy')),
    'tinker_inspect': lambda token, args: tinker_inspect(token),
    'tinker_probe': lambda token, args: tinker_probe(token, args['diagnostic_id'], args['version']),
    'lens_handoff': lambda token, args: lens_handoff(token),
    'lens_transfer': lambda token, args: lens_transfer(token, args['representation'], args['version']),
}


def call(role, token, tool, args):
    if role not in ROLE_TOOLS or tool not in ROLE_TOOLS[role]:
        raise PermissionError(f'{role} may not call {tool}')
    return TOOLS[tool](token, args)
