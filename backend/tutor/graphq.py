"""FalkorDB-native tutor reasoning over a learner graph. Each query is logged with its Cypher and server time.

Evidence lives as graph structure:
  (:TaskIssue)-[:CHECKS]->(:Concept)        the item that was issued, about which concept
  (:TaskIssue)-[:IN]->(:Representation)     strips, pies, grids, counters, number lines
  (:TaskIssue)-[:PRODUCED]->(:Observation)-[:ABOUT]->(:Concept)
  (:Activity)-[:TEACHES]->(:Concept), (:Activity)-[:OFFERS]->(:Representation), (:Activity)-[:ADDRESSES]->(:Objective)
The prerequisite structure is the imported curriculum: (:Concept)-[:REQUIRES]->(:Concept).
FalkorDB 6.0.1 note: no `WHERE NOT (pattern)` after MATCH; absence is tested with OPTIONAL MATCH and count().
"""
from ..reasoning import query

CHECKS = ['diagnostic', 'transfer', 'recheck']
SUPPORTED = ['supported_for_objective', 'supported_for_task']

# Correct checks without hints since the last incorrect check, for one concept. Rule v1 is evaluated on this.
STREAK = '''MATCH (o:Observation)-[:ABOUT]->(:Concept {id:$concept}) WHERE o.purpose IN $checks
WITH max(CASE WHEN o.correct THEN -1.0 ELSE o.time END) AS last_wrong
MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN $checks AND o.correct AND NOT o.hinted AND o.time > coalesce(last_wrong, -1.0)
MATCH (x)-[:IN]->(r:Representation)
RETURN collect(DISTINCT x.key), collect(DISTINCT r.rep), sum(CASE WHEN o.purpose = 'transfer' THEN 1 ELSE 0 END)'''

# The most recent check on a concept: its representation and the difficulty Assay named.
LAST_CHECK = '''MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN $checks
MATCH (x)-[:IN]->(r:Representation)
RETURN r.rep, o.correct, o.difficulty ORDER BY o.time DESC LIMIT 1'''

# Lens: every representation this lesson offers, and how many clean correct checks already used it in this run.
STRATEGIES = '''MATCH (a:Activity {id:$activity})-[e:OFFERS]->(r:Representation)
OPTIONAL MATCH (r)<-[:IN]-(x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN $checks AND o.correct AND NOT o.hinted AND o.time > $since
RETURN r.rep, r.label, e.order, count(o) ORDER BY e.order'''

# Scout, after a struggle: lessons on the route that sit below a concept whose latest evidence is a difficulty.
SUSPECTS = '''MATCH (s:LearningState)-[:ABOUT]->(f:Concept)
WHERE f.id IN $ids AND s.status = 'needs_check' AND s.wrong > 0
MATCH path = (f)-[:REQUIRES*1..]->(p:Concept)
WHERE p.id IN $ids
MATCH (p)<-[:TEACHES]-(a:Activity {kind:'lesson'})
RETURN a.id, p.id, f.id, f.name, min(length(path)) AS steps ORDER BY steps'''

# A cautious hypothesis, not evidence: foundations below observed support that have no observation of their own.
INFERRED = '''MATCH (s:LearningState)-[:ABOUT]->(c:Concept)-[:REQUIRES*1..]->(p:Concept)
WHERE s.status IN $supported AND c.id IN $ids AND p.id IN $ids
OPTIONAL MATCH (own:LearningState)-[:ABOUT]->(p)
WITH p, collect(DISTINCT c.name) AS via, count(own) AS observed
WHERE observed = 0
RETURN p.id, via'''

# Scout's ordering. Suspected foundations first (nearest first), then unblocked, then not merely inferred,
# then widest reverse coverage. Later checks come after first checks.
RANK = '''UNWIND $options AS o
RETURN o.id ORDER BY o.recheck ASC, o.suspect DESC, o.steps ASC, o.blocked ASC, o.inferred ASC,
o.coverage DESC, o.depth DESC, o.id ASC'''

# Parent summary: what happened, per concept, straight from the evidence edges.
SUMMARY = '''MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(c:Concept)
RETURN c.id, c.name, x.activity, count(o) AS answers, sum(CASE WHEN o.correct THEN 1 ELSE 0 END),
sum(CASE WHEN o.hinted THEN 1 ELSE 0 END), sum(CASE WHEN o.purpose = 'lesson' THEN 1 ELSE 0 END),
collect(DISTINCT o.difficulty), max(o.time) AS latest ORDER BY latest DESC'''


def streak(g, concept, log):
    rows = query(g, 'support streak', STREAK, {'concept': concept, 'checks': CHECKS}, log)
    if not rows or rows[0][0] is None:
        return {'keys': [], 'reps': [], 'transfers': 0}
    keys, reps, transfers = rows[0]
    return {'keys': keys or [], 'reps': reps or [], 'transfers': transfers or 0}


def last_check(g, concept, log):
    rows = query(g, 'latest check on this concept', LAST_CHECK, {'concept': concept, 'checks': CHECKS}, log)
    return dict(zip(['rep', 'correct', 'difficulty'], rows[0])) if rows else {}


def strategies(g, activity, concept, since, log):
    rows = query(g, 'transfer strategies for Lens', STRATEGIES,
                 {'activity': activity, 'concept': concept, 'checks': CHECKS, 'since': since}, log)
    return [{'rep': r[0], 'label': r[1], 'order': r[2], 'clean_correct': r[3]} for r in rows]


LAST_WRONG = '''MATCH (o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN $checks AND o.correct = false
RETURN max(o.time)'''


def last_wrong_time(g, concept, log):
    rows = query(g, 'latest incorrect check', LAST_WRONG, {'concept': concept, 'checks': CHECKS}, log)
    return rows[0][0] if rows and rows[0][0] is not None else -1.0


def suspects(g, ids, log):
    out = {}
    for aid, cid, below, below_name, steps in query(g, 'suspected foundations below a difficulty', SUSPECTS, {'ids': ids}, log):
        if cid not in out or steps < out[cid]['steps']:
            out[cid] = {'activity': aid, 'below': below, 'below_name': below_name, 'steps': steps}
    return out


def inferred(g, ids, log):
    return {r[0]: r[1] for r in query(g, 'inferred support hypotheses', INFERRED, {'ids': ids, 'supported': SUPPORTED}, log)}


def rank(g, options, log):
    rows = [{'id': o['id'], 'recheck': o['purpose'] == 'recheck', 'suspect': bool(o.get('suspect')),
             'steps': (o.get('suspect') or {}).get('steps', 99), 'blocked': o['uncertain_prerequisites'] > 0,
             'inferred': bool(o.get('inferred')), 'coverage': o.get('coverage') or 0, 'depth': o.get('depth') or 0}
            for o in options]
    order = [r[0] for r in query(g, 'rank lessons for Scout', RANK, {'options': rows}, log)] if rows else []
    by = {o['id']: o for o in options}
    return [by[i] for i in order]


def summary(g, log):
    keys = ['concept', 'name', 'activity', 'answers', 'correct', 'hinted', 'lesson_answers', 'difficulties', 'latest']
    return [dict(zip(keys, r)) | {'difficulties': [d for d in r[7] if d]} for r in query(g, 'parent summary', SUMMARY, {}, log)]

# Evidence-grounded teaching choices. No task parameters or answers are returned.
TEACHING = '''MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN ['diagnostic','transfer','recheck','probe'] AND o.difficulty IS NOT NULL
WITH x,o ORDER BY o.time DESC LIMIT 1
OPTIONAL MATCH (o)-[:SUGGESTS]->(h:DifficultyHypothesis)<-[:ADDRESSES]-(s:TeachingStrategy)<-[:USES_STRATEGY]-(a:Activity {id:$activity})
RETURN o.id,o.difficulty,o.correct,x.rep,h.text,s.id,s.title,s.instruction,s.reps'''
PROBES = '''MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN ['diagnostic','transfer','recheck','probe']
WITH o ORDER BY o.time DESC LIMIT 1
MATCH (o)-[:SUGGESTS]->(h:DifficultyHypothesis {ambiguous:true})<-[:DISTINGUISHES]-(d:Diagnostic)
MATCH (d)-[:DISTINGUISHES]->(other:DifficultyHypothesis)
RETURN d.id,d.title,d.rep,d.why,h.text,collect(DISTINCT other.id) AS separates ORDER BY d.id'''
HISTORY = '''MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
RETURN o.id,o.purpose,o.correct,o.hinted,o.difficulty,x.rep,o.time ORDER BY o.time DESC LIMIT 6'''


def teaching(g, concept, activity, log):
    rows=query(g,'teaching strategies connected to latest evidence',TEACHING,{'concept':concept,'activity':activity},log)
    if not rows:return {'observation':None,'hypotheses':[],'strategies':[]}
    first=rows[0]
    strategies=[dict(zip(['id','title','instruction','reps'],r[5:9])) for r in rows if r[5]]
    return {'observation':{'id':first[0],'difficulty':first[1],'was_correct':first[2],'representation':first[3]},
            'hypotheses':list(dict.fromkeys(r[4] for r in rows if r[4])), 'strategies':strategies}


def probes(g, concept, log):
    rows=query(g,'diagnostics that distinguish the observed difficulty',PROBES,{'concept':concept},log)
    return [dict(zip(['id','title','rep','why','hypothesis','distinguishes'],r)) for r in rows]


def history(g, concept, log):
    return [dict(zip(['id','purpose','correct','hinted','difficulty','representation','time'],r))
            for r in query(g,'recent evidence for this foundation',HISTORY,{'concept':concept},log)]


# ---------- one foundation episode: ambiguity, strategies already tried, and the timeline ----------
LATEST_MISTAKE = '''MATCH (o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN ['diagnostic','transfer','recheck','probe'] AND o.difficulty IS NOT NULL AND o.time >= $since
WITH o ORDER BY o.time DESC LIMIT 1
MATCH (o)-[:SUGGESTS]->(h:DifficultyHypothesis)
RETURN o.id, h.id, h.text, h.ambiguous'''
TRIED = '''MATCH (x:TaskIssue)-[:USES_STRATEGY]->(s:TeachingStrategy)
WHERE x.id IN $lessons
RETURN DISTINCT s.id, s.title'''
EPISODE = '''MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.time >= $since
OPTIONAL MATCH (o)-[:SUGGESTS]->(h:DifficultyHypothesis)
OPTIONAL MATCH (x)-[:USES_STRATEGY]->(s:TeachingStrategy)
RETURN o.id, o.purpose, o.correct, o.hinted, o.difficulty, x.rep, o.label, h.text, h.ambiguous, s.title, o.time
ORDER BY o.time'''


def latest_mistake(g, concept, since, log):
    rows = query(g, 'latest mistake in this episode', LATEST_MISTAKE, {'concept': concept, 'since': since}, log)
    return dict(zip(['observation', 'hypothesis', 'text', 'ambiguous'], rows[0])) if rows else {}


def tried_strategies(g, lessons, log):
    return [{'id': r[0], 'title': r[1]} for r in query(g, 'strategies already tried in this episode', TRIED,
                                                         {'lessons': lessons}, log)] if lessons else []


def episode(g, concept, since, log):
    keys = ['id', 'purpose', 'correct', 'hinted', 'difficulty', 'representation', 'label', 'explanation',
            'ambiguous', 'strategy', 'time']
    return [dict(zip(keys, r)) for r in query(g, 'this episode, step by step', EPISODE,
                                              {'concept': concept, 'since': since}, log)]


# ---------- the receipt behind "supported": the exact checks that satisfied the rule ----------
RECEIPT = '''MATCH (o:Observation)-[:ABOUT]->(:Concept {id:$concept}) WHERE o.purpose IN $checks
WITH max(CASE WHEN o.correct THEN -1.0 ELSE o.time END) AS last_wrong
MATCH (x:TaskIssue)-[:PRODUCED]->(o:Observation)-[:ABOUT]->(:Concept {id:$concept})
WHERE o.purpose IN $checks AND o.correct AND NOT o.hinted AND o.time > coalesce(last_wrong, -1.0)
MATCH (x)-[:IN]->(r:Representation)
RETURN o.id, o.label, o.purpose, r.rep, r.family, r.label, o.time ORDER BY o.time'''


def receipt(g, concept, log):
    keys = ['id', 'label', 'purpose', 'rep', 'family', 'representation', 'time']
    return [dict(zip(keys, r)) for r in query(g, 'receipt: checks behind supported', RECEIPT,
                                              {'concept': concept, 'checks': CHECKS}, log)]
