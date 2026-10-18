"""FalkorDB-native reachability, coverage, witnesses and deterministic ranking."""
import time

CLOSURE = '''MATCH (g:Concept {id:$goal})-[:REQUIRES*0..]->(c:Concept)
RETURN DISTINCT c.id ORDER BY c.id'''
EDGES = '''MATCH (c:Concept)-[r:REQUIRES]->(p:Concept)
WHERE c.id IN $ids AND p.id IN $ids
RETURN c.id,p.id,r.reason ORDER BY c.id,p.id'''
COVERAGE = '''MATCH (c:Concept) WHERE c.id IN $ids
MATCH (d:Concept)-[:REQUIRES*0..]->(c) WHERE d.id IN $ids
RETURN c.id,count(DISTINCT d) ORDER BY c.id'''
WITNESSES = '''MATCH (g:Concept {id:$goal}), (c:Concept)
WHERE c.id IN $ids AND c.id <> $goal
WITH c,shortestPath((g)-[:REQUIRES*]->(c)) AS p
RETURN c.id,[n IN nodes(p)|n.id],length(p) ORDER BY c.id'''
RANK = '''UNWIND $candidates AS c
RETURN c.id ORDER BY c.blocked ASC,c.reported ASC,c.coverage DESC,
c.parent_check ASC,c.depth DESC,c.id ASC'''
ALL_CLOSURES = '''MATCH (g:Concept)-[:REQUIRES*0..]->(c:Concept)
RETURN g.id,collect(DISTINCT c.id) ORDER BY g.id'''


def query(graph,name,cypher,params,log):
    start=time.perf_counter()
    result=graph.ro_query(cypher,params,timeout=5000)
    log.append({'name':name,'cypher':cypher,'parameters':params,
                'server_ms':result.run_time_ms,'wall_ms':round((time.perf_counter()-start)*1000,3),
                'rows':len(result.result_set)})
    return result.result_set


def topology(graph,goal):
    log=[]
    ids=[r[0] for r in query(graph,'hard prerequisite closure',CLOSURE,{'goal':goal},log)]
    if not ids:raise ValueError('Unknown goal')
    if len(ids)>1590:raise ValueError('Curriculum budget exceeded')
    edges=[{'from':r[0],'to':r[1],'reason':r[2],'strength':'hard'} for r in query(graph,'hard edges',EDGES,{'ids':ids},log)]
    coverage={r[0]:r[1] for r in query(graph,'reverse branch coverage',COVERAGE,{'ids':ids},log)}
    witnesses={goal:[goal]};depth={goal:0}
    for cid,path,d in query(graph,'shortest witness paths',WITNESSES,{'goal':goal,'ids':ids},log):
        if not path:raise ValueError('Database witness missing for reachable concept')
        witnesses[cid]=list(reversed(path));depth[cid]=d
    return {'ids':ids,'edges':edges,'coverage':coverage,'witnesses':witnesses,'depth':depth,'queries':log}


def rank(graph,candidates,log,reported=True):
    if not candidates:return []
    rows=[{'id':a['id'],'blocked':bool(a['missing']),'reported':bool(a.get('reported_support',False)) if reported else False,
           'coverage':a['coverage'],'parent_check':a.get('kind')=='parent_check','depth':a['depth']} for a in candidates]
    order=query(graph,'rank tasks and parent checks' if reported else 'rank prototype tasks',RANK,{'candidates':rows},log)
    by={a['id']:a for a in candidates}
    return [by[r[0]] for r in order]
