"""Graph-backed curriculum and evidence controller. No in-memory planning fallback."""
import hashlib
import json
import os
import re
import threading
import time
from jsonschema import Draft202012Validator
from collections import deque
from pathlib import Path
from uuid import uuid4

from falkordb import FalkorDB

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'vendor/os-taxonomy/data'
RELEASE = '96a7933754af'
BASE = 'trellis_curriculum_' + RELEASE
GOAL = 'mt_Qkewo5M3_c'
LOCK = threading.RLock()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def db():
    # Timeouts turn an unresponsive database into a RedisError, which the API reports as "learning graph unavailable".
    return FalkorDB(host=os.getenv('TRELLIS_DB_HOST', '127.0.0.1'), port=int(os.getenv('TRELLIS_DB_PORT', '6384')),
                    socket_timeout=float(os.getenv('TRELLIS_DB_TIMEOUT', '10')), socket_connect_timeout=3)


SUPPORTED = {'supported_for_task', 'supported_for_objective'}


def registry():
    return json.loads((ROOT / 'activities/registry.json').read_text(encoding='utf-8'))


def all_activities():
    """Water diagnostics plus fraction lessons, as the graph stores them: id, concept, title, kind."""
    lessons = json.loads((ROOT / 'activities/fractions.json').read_text(encoding='utf-8'))['activities']
    return [{'id': a['id'], 'concept': a['concept'], 'title': a['title'], 'kind': 'diagnostic'} for a in registry()] +            [{'id': a['id'], 'concept': a['concept'], 'title': a['title'], 'kind': 'lesson'} for a in lessons]


def lesson_structure():
    """Each lesson's objective, matched source criteria and offered representations, as graph rows."""
    from .tutor.fractions import FAMILIES
    catalog = json.loads((ROOT / 'activities/fractions.json').read_text(encoding='utf-8'))
    objectives = {o['id']: o for o in catalog['objectives']}
    rows = []
    for a in catalog['activities']:
        family = objectives[a['objective']]['family']
        rows.append({'id': a['id'], 'objective': a['objective'], 'objective_text': objectives[a['objective']]['text'],
                     'criteria': a['criteria'],
                     'reps': [{'id': family + ':' + r, 'rep': r, 'family': family, 'label': FAMILIES[family]['reps'][r],
                               'order': i} for i, r in enumerate(a['representations'])]})
    return rows


SCHEMA_VERSION = 'schema-v1'
# Every id the system writes is unique, enforced by FalkorDB itself rather than trusted to application code.
UNIQUE_KEYS = [('Concept', 'id'), ('Activity', 'id'), ('Representation', 'id'), ('Objective', 'id'),
               ('TaskIssue', 'id'), ('Observation', 'id'), ('LearningState', 'id'),
               ('DifficultyHypothesis', 'id'), ('TeachingStrategy', 'id'), ('Diagnostic', 'id')]


def ensure_schema(graph):
    """Range indexes and unique constraints on every written id, plus a full-text index for curriculum search.
    GRAPH.COPY carries all three into each learner graph. Safe to run repeatedly."""
    rows = graph.ro_query('CALL db.indexes()').result_set
    ranged = {(r[0], prop) for r in rows for prop, kinds in r[2].items() if 'RANGE' in kinds}
    fulltext = {r[0] for r in rows if any('FULLTEXT' in kinds for kinds in r[2].values())}
    for label, prop in UNIQUE_KEYS:
        if (label, prop) not in ranged:
            graph.create_node_range_index(label, prop)
    constrained = {(c['label'], tuple(c['properties'])) for c in graph.list_constraints()}
    for label, prop in UNIQUE_KEYS:
        if (label, (prop,)) not in constrained:
            graph.create_node_unique_constraint(label, prop)
    if 'Concept' not in fulltext:
        graph.create_node_fulltext_index('Concept', 'name', 'description')


def fulltext_terms(text):
    """User text to a safe RediSearch prefix query: letters and digits only, each word as a prefix."""
    words = re.findall(r'[a-z0-9]+', text.lower())[:6]
    return ' '.join(w + '*' if len(w) >= 2 else w for w in words if w)


def activity_digest():
    from .tutor.pedagogy import VERSION
    return digest({'activities': all_activities(), 'lessons': lesson_structure(), 'teaching_catalog': VERSION,
                   'schema': SCHEMA_VERSION})


def _sync_activities(graph):
    """Activities are our own content layered on the immutable curriculum. MERGE keeps nodes that learner evidence
    already points at (TaskIssue-[:IN]->Representation), and removes only activities the catalog no longer has."""
    rows = all_activities()
    graph.query('MATCH (a:Activity) WHERE NOT a.id IN $ids DELETE a', {'ids': [r['id'] for r in rows]})
    graph.query('UNWIND $rows AS row MATCH (c:Concept {id:row.concept}) '
                'MERGE (a:Activity {id:row.id}) SET a.version=1,a.title=row.title,a.kind=row.kind '
                'MERGE (a)-[:TEACHES]->(c)', {'rows': rows})
    lessons = lesson_structure()
    graph.query('UNWIND $rows AS row MATCH (a:Activity {id:row.id})-[t:TEACHES]->(:Concept) '
                'SET t.criteria=row.criteria MERGE (o:Objective {id:row.objective}) SET o.text=row.objective_text '
                'MERGE (a)-[:ADDRESSES]->(o)', {'rows': lessons})
    graph.query('UNWIND $rows AS row MATCH (a:Activity {id:row.id}) UNWIND row.reps AS rep '
                'MERGE (r:Representation {id:rep.id}) SET r.rep=rep.rep,r.family=rep.family,r.label=rep.label '
                'MERGE (a)-[e:OFFERS]->(r) SET e.order=rep.order', {'rows': lessons})
    from .tutor.pedagogy import ensure
    ensure(graph)
    ensure_schema(graph)
    graph.query('MATCH (d:Dataset {ready:true}) SET d.activity_hash=$hash', {'hash': activity_digest()})


def import_data():
    """Verify original bytes, then publish a complete immutable graph. Retry deletes only our incomplete graph."""
    with LOCK:
        client = db()
        graph = client.select_graph(BASE)
        if BASE in client.list_graphs():
            ready = graph.ro_query('MATCH (d:Dataset {ready:true}) RETURN d.activity_hash').result_set
            if ready:
                if ready[0][0] != activity_digest():
                    _sync_activities(graph)
                return {'graph': BASE, 'reused': True}
        manifest = json.loads((DATA / 'manifest.json').read_text(encoding='utf-8'))
        for name, meta in manifest['files'].items():
            if hashlib.sha256((DATA / name).read_bytes()).hexdigest() != meta['sha256']:
                raise ValueError('Upstream checksum mismatch: ' + name)
            schema = json.loads((DATA.parent / 'schema' / name.replace('.json','.schema.json')).read_text(encoding='utf-8'))
            Draft202012Validator(schema).validate(json.loads((DATA / name).read_text(encoding='utf-8')))
        topics = json.loads((DATA / 'topics.json').read_text(encoding='utf-8'))['topics']
        deps = json.loads((DATA / 'dependencies.json').read_text(encoding='utf-8'))['dependencies']
        ids = {t['id'] for t in topics}
        if len(ids) != len(topics) or any(d['topicId'] not in ids or d['prerequisiteId'] not in ids for d in deps):
            raise ValueError('Invalid curriculum identities')
        # Kahn's algorithm checks the full dependency graph before import.
        incoming = {i: 0 for i in ids}; outgoing = {i: [] for i in ids}
        for d in deps:
            incoming[d['prerequisiteId']] += 1; outgoing[d['topicId']].append(d['prerequisiteId'])
        queue = deque(i for i,n in incoming.items() if not n); visited = 0
        while queue:
            i = queue.popleft(); visited += 1
            for p in outgoing[i]:
                incoming[p] -= 1
                if not incoming[p]: queue.append(p)
        if visited != len(ids): raise ValueError('Curriculum contains a cycle')
        if BASE in client.list_graphs(): graph.delete()
        graph = client.select_graph(BASE)
        graph.query('CREATE INDEX FOR (c:Concept) ON (c.id)')
        for start in range(0, len(topics), 100):
            rows = [{'id': t['id'], 'name': t['name'] or t['id'], 'subject': t['subject'],
                     'description': t['description'], 'age_start': t.get('ageRangeStart'),
                     'age_end': t.get('ageRangeEnd'), 'criteria': t['evidence'], 'standards': t['standards']} for t in topics[start:start+100]]
            graph.query('UNWIND $rows AS row CREATE (c:Concept) SET c = row', {'rows': rows})
        for strength, relation in [('hard', 'REQUIRES'), ('soft', 'BENEFITS_FROM')]:
            edges = [e for e in deps if e['strength'] == strength]
            for start in range(0, len(edges), 100):
                graph.query('UNWIND $rows AS row MATCH (c:Concept {id:row.topicId}), '
                            '(p:Concept {id:row.prerequisiteId}) CREATE (c)-[:' + relation +
                            ' {reason:row.reason,source:"Marble v1"}]->(p)', {'rows': edges[start:start+100]})
        counts = graph.ro_query('MATCH (c:Concept) RETURN count(c)').result_set[0][0]
        edges = graph.ro_query('MATCH ()-[r:REQUIRES|BENEFITS_FROM]->() RETURN count(r)').result_set[0][0]
        if counts != 1590 or edges != 3221: raise ValueError('Partial import refused')
        graph.query('CREATE (:Dataset {ready:true,release:$release,manifest:$manifest,activity_hash:""})',
                    {'release': RELEASE, 'manifest': digest(manifest)})
        _sync_activities(graph)
        return {'graph': BASE, 'topics': counts, 'dependencies': edges}


def graph_for(token):
    if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Invalid session')
    graph = db().select_graph('trellis_learner_' + token)
    if not graph.ro_query('MATCH (l:Learner {id:$id}) RETURN l.id', {'id': token}).result_set:
        raise ValueError('Session not found')
    return graph


def create_session():
    import_data()
    token = uuid4().hex
    g = db().select_graph(BASE).copy('trellis_learner_' + token)
    g.query('CREATE (:Learner {id:$id,revision:0,created:$time})', {'id': token, 'time': time.time()})
    return {'token': token}


def current_activities(graph):
    """A learner graph is a copy of the curriculum graph, including its Dataset marker. If it was copied before the
    activity catalog changed, bring its Activity nodes up to date so FalkorDB ranks what the product offers."""
    row = graph.ro_query('MATCH (d:Dataset {ready:true}) RETURN d.activity_hash').result_set
    if row and row[0][0] != activity_digest():
        with LOCK:
            _sync_activities(graph)


def plan(token, goal=None):
    g = graph_for(token); started = time.perf_counter()
    current_activities(g)
    if goal is None:
        goal = g.ro_query('MATCH (l:Learner {id:$id}) RETURN l.goal', {'id':token}).result_set[0][0] or GOAL
    if not g.ro_query('MATCH (c:Concept {id:$id}) RETURN c.id', {'id': goal}).result_set:
        raise ValueError('Unknown goal')
    from .reasoning import topology, rank
    topology_data=topology(g,goal)
    seen=set(topology_data['ids']);edges=topology_data['edges'];depth=topology_data['depth']
    rows = g.ro_query('MATCH (c:Concept) WHERE c.id IN $ids '
        'OPTIONAL MATCH (l:Learner {id:$learner})-[:HAS_STATE]->(s:LearningState)-[:ABOUT]->(c) '
        'RETURN c.id,c.name,c.subject,c.description,c.age_start,c.age_end,s.status,s.correct_items,s.wrong,c.criteria,c.standards',
        {'ids':list(seen), 'learner':token}).result_set
    nodes = [{'id':r[0],'name':r[1],'subject':r[2],'description':r[3],'ages':[r[4],r[5]],
              'status':r[6] or 'unknown','correct_items':r[7] or [],'wrong':r[8] or 0,'criteria':r[9] or [],'standards':r[10] or [],'depth':depth[r[0]]} for r in rows]
    by = {n['id']:n for n in nodes}
    activity_rows = g.ro_query('MATCH (a:Activity)-[:TEACHES]->(c:Concept) WHERE c.id IN $ids '
                               'RETURN a.id,c.id,a.title', {'ids':list(seen)}).result_set
    candidates = []
    # Rank diagnostic coverage by reverse reachability over the graph-returned closure.
    for aid,cid,title in activity_rows:
        n = by[cid]
        if n['status'] in SUPPORTED: continue
        coverage = topology_data['coverage'][cid]
        missing = [e['to'] for e in edges if e['from']==cid and by[e['to']]['status'] not in SUPPORTED]
        candidates.append({'id':aid,'concept':cid,'title':title,'coverage':coverage,'missing':missing,
                           'depth':depth[cid], 'diagnostic':True})
    candidates=rank(g,candidates,topology_data['queries'],reported=False)
    revision = g.ro_query('MATCH (l:Learner {id:$id}) RETURN l.revision', {'id':token}).result_set[0][0]
    return {'goal':by[goal], 'nodes':nodes,'edges':edges,'candidates':candidates,'revision':revision,
            'complete':True,'query_ms':round((time.perf_counter()-started)*1000,2),
            'selected':candidates[0] if candidates else None,
            'scope':'Reviewed diagnostic activities only. Supported for task is provisional evidence, not proven mastery.',
            'graph':g.name,'graph_reasoning':topology_data}


def launch(token, aid, revision):
    with LOCK:
        p = plan(token)
        if revision != p['revision']: raise ValueError('State changed. Refresh the plan before choosing an activity.')
        if aid not in [a['id'] for a in p['candidates']]: raise ValueError('Activity is not in the current diagnostic set')
        from .tutor.session import activities as lessons, scout_choose
        if aid in lessons():
            # A fraction foundation starts the tutor loop: a fresh generated check, then teaching and transfer.
            return scout_choose(token, aid, None, source='manual')
        a = next(a for a in registry() if a['id']==aid)
        node = next(n for n in p['nodes'] if n['id']==a['concept'])
        item = next((i for i in a['items'] if i['id'] not in node['correct_items']), a['items'][0])
        action = uuid4().hex
        graph_for(token).query('CREATE (:Action {id:$id,activity:$activity,item:$item,revision:$revision,used:false})',
            {'id':action,'activity':aid,'item':item['id'],'revision':revision})
        return {'action':action,'activity':{k:v for k,v in a.items() if k!='items'},
                'item':{k:v for k,v in item.items() if k not in ('answer','explanation')},'revision':revision}


def submit(token, action, choice):
    with LOCK:
        g = graph_for(token)
        row = g.ro_query('MATCH (a:Action {id:$id}) RETURN a.activity,a.item,a.revision,a.used,a.result', {'id':action}).result_set
        if not row: raise ValueError('Unknown action')
        aid,iid,revision,used,result = row[0]
        if used: return json.loads(result)
        p = plan(token)
        if p['revision'] != revision: raise ValueError('Stale action rejected. Start again from the current plan.')
        a = next(a for a in registry() if a['id']==aid); item = next(i for i in a['items'] if i['id']==iid)
        if type(choice) is not int or choice < 0 or choice >= len(item['options']): raise ValueError('Invalid response')
        n = next(n for n in p['nodes'] if n['id']==a['concept']); correct = choice == item['answer']
        positives = sorted(set(n['correct_items'] + [iid])) if correct else []
        status = 'supported_for_task' if len(positives)>=2 and correct else 'needs_check' if not correct else 'needs_check'
        output = {'correct':correct,'explanation':item['explanation'],'status':status,'revision':revision+1,
                  'concept':a['concept'],'distinct_checks':len(positives)}
        # One atomic scoped query records response, deduplicates action and advances the evidence revision.
        updated = g.query('MATCH (l:Learner {id:$learner}), (a:Action {id:$action}), (c:Concept {id:$concept}) '
                'WHERE l.revision=$expected AND a.used=false '
                'MERGE (s:LearningState {id:$concept}) SET s.status=$status,s.correct_items=$items,s.wrong=$wrong '
                'MERGE (l)-[:HAS_STATE]->(s) MERGE (s)-[:ABOUT]->(c) '
                'CREATE (o:Observation {id:$observation,item:$item,choice:$choice,correct:$correct,rubric:1,time:$time}) '
                'CREATE (s)-[:DERIVED_FROM]->(o) CREATE (a)-[:PRODUCED]->(o) '
                'SET a.used=true,a.result=$result,l.revision=$revision RETURN l.revision',
                {'learner':token,'action':action,'concept':a['concept'],'expected':revision,'status':status,'items':positives,
                 'wrong':n['wrong']+(not correct),'observation':uuid4().hex,'item':iid,'choice':choice,
                 'correct':correct,'time':time.time(),'result':json.dumps(output),'revision':revision+1}).result_set
        if not updated: raise ValueError('Concurrent state change. Refresh the route.')
        return output

