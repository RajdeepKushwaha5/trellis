"""Investigation safeguards against real isolated learner graphs."""
import unittest
from backend.core import create_session, graph_for
from backend.investigation import set_goal
from backend.tutor import session as t, fractions as e
from backend.tutor.runner import options_for, visible

class InvestigationTools(unittest.TestCase):
 def setUp(self):
  self.token=create_session()['token'];set_goal(self.token,'mt_NoB20kVa4w')
 def tearDown(self):graph_for(self.token).delete()
 def start(self,aid='line-first'):
  route=t.scout_route(self.token);o=next(x for x in route['options'] if x['id']==aid)
  x=t.scout_choose(self.token,aid,route['version']);p=t._task_row(graph_for(self.token),x['task'])['params']
  bad={'tick':(e.solution(p)['tick']+1)%(p['t']*p['span']+1)} if p['family']=='number_line' else {'choice':(e.solution(p)['choice']+1)%3}
  t.answer(self.token,x['task'],bad);return t.tinker_handoff(self.token)
 def test_graph_links_evidence_to_strategies_and_diagnostics(self):
  ctx=self.start();self.assertTrue(ctx['teaching_strategies']);self.assertTrue(ctx['probe_options'])
  g=graph_for(self.token)
  n=g.ro_query('MATCH (:Observation)-[:SUGGESTS]->(:DifficultyHypothesis)<-[:ADDRESSES]-(:TeachingStrategy) RETURN count(*)').result_set[0][0]
  self.assertGreater(n,0)
  v=visible('tinker',ctx);self.assertEqual(v['difficulty_meaning'],'placed the point at the wrong mark')
  self.assertNotIn('params',str(v))
 def test_probe_is_fresh_bounded_and_never_support(self):
  ctx=self.start();d=ctx['probe_options'][0];x=t.tinker_probe(self.token,d['id'],ctx['version'])
  self.assertEqual(x['purpose'],'probe');self.assertFalse(x['hints_allowed'])
  with self.assertRaises(ValueError):t.hint(self.token,x['task'])
  p=t._task_row(graph_for(self.token),x['task'])['params'];r=t.answer(self.token,x['task'],e.solution(p))
  self.assertFalse(r['counts_as_check']);self.assertEqual(r['next_role'],'tinker')
  self.assertNotEqual(r['status'],'supported_for_objective')
  ctx=t.tinker_handoff(self.token);self.assertEqual(ctx['probe_options'],[])
  with self.assertRaises(ValueError):t.tinker_probe(self.token,d['id'],ctx['version'])
 def test_strategy_is_validated_and_rendered_without_answer_key(self):
  ctx=self.start();s=ctx['teaching_strategies'][0];rep=next(r['id'] for r in ctx['representations'] if r['id'] in s['reps'])
  with self.assertRaises(ValueError):t.tinker_teach(self.token,rep,'example_first',ctx['version'],'invented')
  x=t.tinker_teach(self.token,rep,'example_first',ctx['version'],s['id'])
  self.assertEqual(x['teaching_strategy']['id'],s['id']);self.assertIn('instruction',x['teaching_strategy'])
  self.assertNotIn('solution',str(x['render']))
 def test_inspection_is_bounded_private_and_refreshes_version(self):
  ctx=self.start();v=ctx['version'];r=t.tinker_inspect(self.token)
  self.assertTrue(r['history']);self.assertGreater(r['version'],v)
  self.assertNotIn('params',str(r));self.assertNotIn('solution',str(r))
  with self.assertRaises(ValueError):t.tinker_inspect(self.token)
  with self.assertRaises(ValueError):t.tinker_probe(self.token,ctx['probe_options'][0]['id'],v)
  with self.assertRaises(PermissionError):t.call('lens',self.token,'tinker_inspect',{})
 def test_graph_ablation_removes_connected_choices(self):
  self.start();g=graph_for(self.token)
  before=t.tinker_handoff(self.token)
  g.query('MATCH (:TeachingStrategy)-[r:ADDRESSES]->(:DifficultyHypothesis) DELETE r')
  after=t.tinker_handoff(self.token)
  self.assertTrue(before['teaching_strategies']);self.assertEqual(after['teaching_strategies'],[])
  self.assertTrue(after['probe_options'])

class RuleAndProbe(unittest.TestCase):
 def test_rule_probes_an_ambiguous_mistake_and_teaches_a_specific_one(self):
  from backend.tutor.choice_eval import seed
  from backend.tutor.runner import rule_choice
  tok,ctx=seed({'id':'r1','activity':'line-first','rep':'ticks','difficulty':'placement'})
  try:
   choice,why=rule_choice('tinker',ctx,options_for('tinker',ctx,{}))
   self.assertEqual(choice[2],'tinker_probe');self.assertIn('tell the explanations apart',why)
   probe=t.tinker_probe(tok,choice[3]['diagnostic_id'],ctx['version'])
   self.assertGreaterEqual(len(probe['separates']),2)  # its wrong answers split at least two explanations
  finally:graph_for(tok).delete()
  tok,ctx=seed({'id':'r2','activity':'line-first','rep':'read','difficulty':'counted_marks'})
  try:
   choice,_=rule_choice('tinker',ctx,options_for('tinker',ctx,{}))
   self.assertIn(choice[3].get('strategy'),('walk-gaps','read-intervals'))
  finally:graph_for(tok).delete()

if __name__=='__main__':unittest.main()
