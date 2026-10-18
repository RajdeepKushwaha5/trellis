"""Independent source-data oracle for native query semantics, not a mirrored planner."""
import json
import unittest
from collections import deque
from backend.core import DATA,BASE,db,create_session,graph_for
from backend.reasoning import ALL_CLOSURES,topology,rank


class NativeReasoning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        topics=json.loads((DATA/'topics.json').read_text(encoding='utf-8'))['topics']
        deps=json.loads((DATA/'dependencies.json').read_text(encoding='utf-8'))['dependencies']
        cls.parents={t['id']:[] for t in topics}
        for e in deps:
            if e['strength']=='hard':cls.parents[e['topicId']].append(e['prerequisiteId'])
        cls.oracle={}
        for goal in cls.parents:
            seen={goal};todo=[goal]
            for cid in todo:
                for parent in cls.parents[cid]:
                    if parent not in seen:seen.add(parent);todo.append(parent)
            cls.oracle[goal]=seen

    def test_every_goal_closure_matches_source_oracle(self):
        rows=db().select_graph(BASE).ro_query(ALL_CLOSURES,timeout=5000).result_set
        self.assertEqual(len(rows),1590)
        self.assertEqual({r[0]:set(r[1]) for r in rows},self.oracle)

    def test_native_coverage_and_shortest_witnesses_match_independent_oracle(self):
        # Largest closures plus roots, in multiple subjects, exercise branching and self reachability.
        cases=sorted(self.oracle,key=lambda g:-len(self.oracle[g]))[:6]
        cases+=sorted(self.oracle,key=lambda g:len(self.oracle[g]))[:2]
        g=db().select_graph(BASE)
        for goal in cases:
            result=topology(g,goal);closure=self.oracle[goal]
            distances={goal:0};q=deque([goal])
            while q:
                cid=q.popleft()
                for parent in self.parents[cid]:
                    if parent not in distances:distances[parent]=distances[cid]+1;q.append(parent)
            for cid in closure:
                self.assertEqual(result['coverage'][cid],sum(cid in self.oracle[d] for d in closure))
                path=result['witnesses'][cid]
                self.assertEqual(path[0],cid);self.assertEqual(path[-1],goal)
                self.assertEqual(len(path)-1,distances[cid])
                for parent,child in zip(path,path[1:]):self.assertIn(parent,self.parents[child])

    def test_native_ranking_preserves_frozen_policy_order(self):
        g=db().select_graph(BASE)
        candidates=[{'id':'unready','missing':['x'],'coverage':90,'depth':4,'kind':'activity'},
                    {'id':'reported','missing':[],'coverage':90,'depth':4,'kind':'activity','reported_support':True},
                    {'id':'parent','missing':[],'coverage':3,'depth':2,'kind':'parent_check'},
                    {'id':'task','missing':[],'coverage':3,'depth':2,'kind':'activity'}]
        self.assertEqual([a['id'] for a in rank(g,candidates,[])],['task','parent','reported','unready'])

if __name__=='__main__':unittest.main()
