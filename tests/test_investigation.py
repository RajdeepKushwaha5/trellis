import unittest
from backend.core import create_session,graph_for,db,BASE,GOAL
from backend.investigation import learning_plan,set_goal,launch_check,submit_check,launch_parent_criterion,preview

class Investigation(unittest.TestCase):
    def setUp(self):self.token=create_session()['token'];self.children=[]
    def tearDown(self):
        for token in self.children+[self.token]:graph_for(token).delete()

    def foreign_goal(self):
        return db().select_graph(BASE).ro_query('MATCH (c:Concept) WHERE c.subject="Mathematics" RETURN c.id ORDER BY c.id LIMIT 1').result_set[0][0]

    def test_any_goal_and_report_is_not_graded(self):
        p=set_goal(self.token,self.foreign_goal())
        selected=next(a for a in p['candidates'] if a['kind']=='parent_check')
        a=launch_check(self.token,selected['id'],p['revision'])
        result=submit_check(self.token,a['action'],0)
        self.assertIsNone(result['correct']);self.assertEqual(result['kind'],'parent_check')
        self.assertEqual(submit_check(self.token,a['action'],0),result)
        self.assertEqual(graph_for(self.token).ro_query('MATCH (o:Observation) RETURN count(o)').result_set[0][0],0)
        self.assertEqual(learning_plan(self.token)['goal']['id'],p['goal']['id'])

    def test_all_yes_reports_never_become_task_support(self):
        p=set_goal(self.token,self.foreign_goal());cid=p['goal']['id']
        for _ in p['goal']['criteria']:
            p=learning_plan(self.token);a=launch_check(self.token,'check:'+cid,p['revision']);submit_check(self.token,a['action'],0)
        n=learning_plan(self.token)['goal']
        self.assertEqual(n['status'],'reported_ready');self.assertEqual(n['task_status'],'unknown')

    def test_goal_change_invalidates_action(self):
        p=learning_plan(self.token);a=launch_check(self.token,p['selected']['id'],p['revision'])
        set_goal(self.token,self.foreign_goal())
        with self.assertRaisesRegex(ValueError,'Stale'):submit_check(self.token,a['action'],0)

    def test_preview_leaves_notebook_untouched_and_deletes_clone(self):
        p=learning_plan(self.token);before=set(db().list_graphs())
        result=preview(self.token,p['selected']['concept'])
        self.assertTrue(result['hypothetical']);self.assertEqual(set(db().list_graphs()),before)
        self.assertEqual(learning_plan(self.token)['fingerprint'],p['fingerprint'])

    def test_long_hard_closure_not_truncated(self):
        # Derive the deepest hard path from pinned source data independently of the planner.
        import json
        from backend.core import DATA
        edges=json.loads((DATA/'dependencies.json').read_text())['dependencies'];parents={}
        for e in edges:
            if e['strength']=='hard':parents.setdefault(e['topicId'],[]).append(e['prerequisiteId'])
        cache={}
        def depth(cid):
            if cid not in cache:cache[cid]=max((depth(p)+1 for p in parents.get(cid,[])),default=0)
            return cache[cid]
        goal=max(parents,key=depth);p=set_goal(self.token,goal)
        self.assertGreater(depth(goal),4)
        seen=set();todo=[goal]
        while todo:
            cid=todo.pop()
            if cid in seen:continue
            seen.add(cid);todo.extend(parents.get(cid,[]))
        self.assertEqual({n['id'] for n in p['nodes']},seen)

    def test_parent_can_revise_report_without_rewriting_history(self):
        p=set_goal(self.token,self.foreign_goal());cid=p['goal']['id']
        a=launch_parent_criterion(self.token,cid,0,p['revision']);submit_check(self.token,a['action'],0)
        a=launch_parent_criterion(self.token,cid,0,p['revision']+1);submit_check(self.token,a['action'],1)
        rows=graph_for(self.token).ro_query('MATCH (o:ReportedObservation) RETURN count(o)').result_set
        self.assertEqual(rows[0][0],2)
        n=learning_plan(self.token)['goal'];self.assertEqual(n['reports'][0]['response'],'no')

    def test_conflicting_report_cannot_turn_task_failure_into_support(self):
        g=graph_for(self.token)
        g.query('MATCH (l:Learner),(c:Concept {id:$id}) CREATE (s:LearningState {id:$id,status:"needs_check",correct_items:[],wrong:1}) CREATE (l)-[:HAS_STATE]->(s) CREATE (s)-[:ABOUT]->(c)',{'id':GOAL})
        p=learning_plan(self.token)
        for i in range(len(p['goal']['criteria'])):
            a=launch_parent_criterion(self.token,GOAL,i,learning_plan(self.token)['revision']);submit_check(self.token,a['action'],0)
        self.assertEqual(learning_plan(self.token)['goal']['status'],'conflicting')

if __name__=='__main__':unittest.main()
