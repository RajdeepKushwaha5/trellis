"""Two learners, same goal and foundation, different mistakes. The graph links each mistake to a different
possible explanation and teaching strategy, so the agents' next moves differ.

Both learners are seeded synthetic fixtures. To keep the page instant, their roles act by the product's rule
(runner.rule_choice) through the same controller calls and permission table; the learning room runs the roles
through their MCP servers.
"""
import json
import time
from uuid import uuid4

from ..core import graph_for
from . import graphq, session
from .fixtures import seed
from .runner import options_for, rule_choice

PROFILES = [
    {'side': 'A', 'mistake': 'counted_marks', 'rep': 'read', 'title': 'Counted the marks, not the gaps'},
    {'side': 'B', 'mistake': 'placement', 'rep': 'ticks', 'title': 'Put the point on the wrong mark'},
]
READ = {'scout': 'scout_route', 'tinker': 'tinker_handoff', 'lens': 'lens_handoff'}


def rule_step(token):
    """One role move by the rule, through the controller's permission table. Recorded like any role decision."""
    t = session._tutor(graph_for(token))
    role = session.DUE.get(t['state'])
    if not role:
        return None
    ctx = session.call(role, token, READ[role], {})
    opts = [o for o in options_for(role, ctx, {}) if o[2] not in ('scout_inspect', 'tinker_inspect')]
    if not opts:
        session.pause_if_stuck(token, 'No permitted move remains, so the tutor pauses here.')
        return None
    choice, why = rule_choice(role, ctx, opts)
    task = session.call(role, token, choice[2], choice[3])
    decision = {'role': role, 'chooser': 'policy', 'model': None, 'options': [{'id': o[0], 'label': o[1]} for o in opts],
                'option': choice[0], 'label': choice[1], 'rule_option': choice[0], 'rule_label': choice[1],
                'rule_why': why, 'agrees_with_rule': True, 'model_reason_unverified': 'Rule-based, no model: ' + why}
    session.record_decision(token, {'role': role, 'decisions': [decision], 'trace': [], 'task': task['task'],
                                    'tools': list(session.ROLE_TOOLS[role]),
                                    'path': 'comparison page: rule-based move through the controller, no MCP process'})
    return decision


def view(token, profile):
    g = graph_for(token)
    log = []
    first = g.ro_query('MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation) RETURN o.label,o.choice,o.difficulty,x.id '
                       'ORDER BY o.time ASC LIMIT 1').result_set[0]
    seeded = session._task_row(g, first[3])
    st = session.status(token)
    link = graphq.query(g, 'mistake to explanation to strategy', '''MATCH (o:Observation)-[:SUGGESTS]->(h:DifficultyHypothesis)
OPTIONAL MATCH (x:TaskIssue)-[:USES_STRATEGY]->(s:TeachingStrategy)-[:ADDRESSES]->(h)
RETURN h.text, collect(DISTINCT s.title) ORDER BY h.text LIMIT 1''', {}, log)
    decisions = [d for r in g.ro_query('MATCH (d:RoleDecision) RETURN d.payload ORDER BY d.time').result_set
                 for d in json.loads(r[0])['decisions']]
    from .fractions import grade
    return {'side': profile['side'], 'title': profile['title'], 'mistake': profile['mistake'],
            'seeded': {'prompt': first[0], 'answer': grade(seeded['params'], json.loads(first[1]))['value'],
                       'meaning': session.DIFFICULTY.get(first[2])},
            'explanation': link[0][0] if link else None, 'strategies': link[0][1] if link else [],
            'decisions': [{'role': d['role'], 'label': d['label'], 'why': d['rule_why']} for d in decisions],
            'task': st['task'], 'state': st['state'], 'note': st['history'][-1]['note'] if st['history'] else '',
            'stations': [s for s in st['stations'] if s['concept'] == st['concept']], 'queries': log}


def open_comparison(owner):
    children = []
    try:
        for profile in PROFILES:
            token, _ = seed({'id': 'compare-' + profile['side'], 'activity': 'line-first', 'rep': profile['rep'],
                             'difficulty': profile['mistake']})
            children.append(token)
            graph_for(token).query('MATCH (l:Learner) SET l.synthetic_label=$label', {'label': profile['title']})
            rule_step(token)
        cid = uuid4().hex
        graph_for(owner).query('CREATE (:Comparison {id:$id,left:$left,right:$right,kind:"fractions",time:$time})',
                               {'id': cid, 'left': children[0], 'right': children[1], 'time': time.time()})
        return {'id': cid, 'synthetic': True, 'profiles': [view(c, p) for c, p in zip(children, PROFILES)]}
    except Exception:
        for token in children:
            graph_for(token).delete()
        raise


def answer(owner, cid, side, task, response):
    from ..investigation import comparison_child
    child = comparison_child(owner, cid, side)
    result = session.answer(child, task, response)
    moved = rule_step(child) if result['next_role'] else None
    return {'result': result, 'moved': moved, 'profile': view(child, PROFILES[side])}


def hint(owner, cid, side, task):
    from ..investigation import comparison_child
    return session.hint(comparison_child(owner, cid, side), task)
