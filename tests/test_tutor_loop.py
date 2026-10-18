"""The diagnose, teach, transfer loop against isolated synthetic FalkorDB learner graphs."""
import asyncio
import json
import unittest

from backend.core import create_session, graph_for, plan
from backend.investigation import set_goal
from backend.tutor import fractions as engine
from backend.tutor import session as tutor
from backend.tutor.runner import step

GOAL = 'mt_NoB20kVa4w'  # Fractions on a number line (age 8+): every fraction lesson sits on this route


class Loop(unittest.TestCase):
    def setUp(self):
        self.token = create_session()['token']
        set_goal(self.token, GOAL)

    def tearDown(self):
        graph_for(self.token).delete()

    # helpers: the test plays the learner using server-side keys the browser never receives
    def params(self, tid):
        return tutor._task_row(graph_for(self.token), tid)['params']

    def right(self, tid):
        return tutor.answer(self.token, tid, engine.solution(self.params(tid)))

    def wrong(self, tid):
        p, sol = self.params(tid), engine.solution(self.params(tid))
        if 'choice' in sol:
            bad = {'choice': (sol['choice'] + 1) % 3}
        elif 'shaded' in sol:
            bad = {'shaded': []}
        else:
            bad = {'tick': (sol['tick'] + 1) % (p['t'] * p['span'] + 1)}
        result = tutor.answer(self.token, tid, bad)
        self.assertFalse(result['correct'])
        return result

    def state(self):
        return tutor.status(self.token)

    def scout(self, index=0):
        route = tutor.call('scout', self.token, 'scout_route', {})
        option = route['options'][index]
        return option, tutor.call('scout', self.token, 'scout_choose', {'activity_id': option['id'], 'version': route['version']})

    def teach(self, rep=None, opening='example_first'):
        ctx = tutor.call('tinker', self.token, 'tinker_handoff', {})
        rep = rep or ctx['representations'][0]['id']
        return tutor.call('tinker', self.token, 'tinker_teach', {'representation': rep, 'opening': opening, 'version': ctx['version']})

    def transfer(self):
        ctx = tutor.call('lens', self.token, 'lens_handoff', {})
        return ctx, tutor.call('lens', self.token, 'lens_transfer', {'representation': ctx['strategies'][0]['id'], 'version': ctx['version']})

    def test_wrong_check_leads_to_teaching_then_two_distinct_transfers(self):
        option, diag = self.scout()
        self.assertEqual(diag['purpose'], 'diagnostic')
        self.assertEqual(diag['hints_available'], 0)
        self.assertEqual(self.wrong(diag['task'])['next_role'], 'tinker')
        # Lens cannot act out of turn, and no role can call another role's tools.
        with self.assertRaises(PermissionError):
            tutor.call('lens', self.token, 'tinker_teach', {})
        with self.assertRaises(ValueError):
            tutor.call('lens', self.token, 'lens_handoff', {})
        lesson = self.teach()
        self.assertIn('example', lesson)
        self.assertNotIn('solution', json.dumps(lesson['render']))
        tutor.hint(self.token, lesson['task'])
        practice = self.right(lesson['task'])
        self.assertTrue(practice['hinted'])
        self.assertFalse(practice['counts_as_check'])
        self.assertEqual(practice['next_role'], 'lens')
        ctx, first = self.transfer()
        self.assertNotIn(lesson['representation'], [s['id'] for s in ctx['strategies']])
        self.assertNotIn('params', json.dumps(ctx))
        self.assertNotEqual(first['representation'], lesson['representation'])
        one = self.right(first['task'])
        self.assertEqual(one['status'], 'needs_check')  # one clean check after a wrong one is not enough
        ctx, second = self.transfer()
        self.assertNotIn(second['representation'], {first['representation'], lesson['representation']})
        two = self.right(second['task'])
        # Halves has only picture choices, so rule v2 needs a third clean check before support.
        self.assertEqual(two['status'], 'needs_check')
        self.assertEqual(two['evidence']['items_needed'], 3)
        ctx, third = self.transfer()
        three = self.right(third['task'])
        self.assertEqual(three['status'], 'supported_for_objective')
        self.assertEqual(three['next_role'], 'scout')
        self.assertNotIn(option['id'], [c['id'] for c in plan(self.token)['candidates']])
        keys = [r[0] for r in graph_for(self.token).ro_query('MATCH (x:TaskIssue) RETURN x.key').result_set]
        self.assertEqual(len(keys), len(set(keys)))

    def test_failed_transfer_revisits_with_a_new_representation_then_pauses(self):
        option, diag = self.scout()
        self.wrong(diag['task'])
        first = self.teach()
        self.right(first['task'])
        _, check = self.transfer()
        self.assertEqual(self.wrong(check['task'])['next_role'], 'tinker')
        with self.assertRaises(ValueError):
            self.teach(rep=first['representation'])
        second = self.teach(opening='try_first')
        self.assertNotEqual(second['representation'], first['representation'])
        self.right(second['task'])
        _, check = self.transfer()
        result = self.wrong(check['task'])
        self.assertEqual(result['next_state'], 'paused')
        self.assertEqual(result['status'], 'needs_check')
        self.assertNotIn(option['id'], [o['id'] for o in tutor.scout_route(self.token)['options']])

    def test_correct_check_goes_straight_to_a_transfer_in_another_representation(self):
        _, diag = self.scout()
        self.assertEqual(self.right(diag['task'])['next_role'], 'lens')
        _, check = self.transfer()
        self.assertNotEqual(check['representation'], diag['representation'])
        self.assertEqual(self.right(check['task'])['status'], 'needs_check')  # picture-only: two are not enough
        _, third = self.transfer()
        self.assertEqual(self.right(third['task'])['status'], 'supported_for_objective')

    def test_a_built_answer_lets_two_checks_count_on_the_number_line(self):
        route = tutor.scout_route(self.token)
        diag = tutor.scout_choose(self.token, 'line-first', route['version'])  # first representation: placing a point
        self.assertEqual(diag['render']['type'], 'place')
        self.right(diag['task'])
        _, check = self.transfer()
        result = self.right(check['task'])
        self.assertTrue(result['evidence']['built_answer'])
        self.assertEqual(result['status'], 'supported_for_objective')
        # The receipt behind "supported" is rebuilt from the graph: exactly these two checks, nothing else.
        receipt = next(r for r in tutor.report(self.token)['receipts'] if r['concept'] == diag['concept'])
        self.assertEqual([c['purpose'] for c in receipt['checks']], ['diagnostic', 'transfer'])
        self.assertEqual((receipt['items'], receipt['transfers'], receipt['items_needed']), (2, 1, 2))
        self.assertGreaterEqual(receipt['built'], 1)

    def test_duplicate_stale_foreign_and_hint_abuse_are_refused(self):
        route = tutor.scout_route(self.token)
        _, diag = self.scout()
        with self.assertRaises(ValueError):
            tutor.hint(self.token, diag['task'])  # checks are answered without help
        first = self.right(diag['task'])
        self.assertEqual(self.right(diag['task']), first)  # idempotent replay, no second observation
        with self.assertRaises(ValueError):
            tutor.call('scout', self.token, 'scout_choose', {'activity_id': route['options'][0]['id'], 'version': route['version']})
        ctx = tutor.lens_handoff(self.token)
        with self.assertRaises(ValueError):
            tutor.lens_transfer(self.token, ctx['strategies'][0]['id'], ctx['version'] - 1)
        _, check = self.transfer()
        other = create_session()['token']
        try:
            with self.assertRaisesRegex(ValueError, 'Unknown task'):
                tutor.answer(other, check['task'], {'choice': 0})
        finally:
            graph_for(other).delete()
        observations = graph_for(self.token).ro_query('MATCH (o:Observation) RETURN count(o)').result_set[0][0]
        self.assertEqual(observations, 1)

    def test_different_starting_evidence_changes_scouts_foundation(self):
        first = tutor.scout_route(self.token)['options'][0]
        other = create_session()['token']
        try:
            set_goal(other, GOAL)
            graph_for(other).query('MATCH (l:Learner), (c:Concept {id:$c}) CREATE (s:LearningState {id:$c,'
                                   'status:"supported_for_objective",correct_items:[],wrong:0,synthetic:true,recheck_after:9e12}) '
                                   'CREATE (l)-[:HAS_STATE]->(s) CREATE (s)-[:ABOUT]->(c)', {'c': first['concept']})
            self.assertNotEqual(tutor.scout_route(other)['options'][0]['id'], first['id'])
        finally:
            graph_for(other).delete()

    def test_a_struggle_sends_scout_down_the_prerequisite_edges(self):
        route = tutor.scout_route(self.token)
        top = next(o for o in route['options'] if o['concept'] == GOAL)  # the goal's own lesson
        diag = tutor.scout_choose(self.token, top['id'], route['version'])
        self.wrong(diag['task'])
        tutor.leave_step(self.token, 'test: back to Scout')
        after = tutor.scout_route(self.token)
        first = after['options'][0]
        self.assertEqual(first['suspect']['below'], GOAL)
        self.assertEqual(first['suspect']['steps'], 1)
        self.assertIn('below Fractions on a number line (age 8+)', first['reasons'][0])
        self.assertIn('suspected foundations below a difficulty', [q['name'] for q in after['queries']])

    def test_inferred_support_lowers_priority_and_writes_no_evidence(self):
        line = next(o for o in tutor.scout_route(self.token)['options'] if o['id'] == 'line-first')
        graph_for(self.token).query('MATCH (l:Learner), (c:Concept {id:$c}) CREATE (s:LearningState {id:$c,'
                                    'status:"supported_for_objective",correct_items:[],wrong:0,synthetic:true,recheck_after:9e12}) '
                                    'CREATE (l)-[:HAS_STATE]->(s) CREATE (s)-[:ABOUT]->(c)', {'c': line['concept']})
        options = tutor.scout_route(self.token)['options']
        inferred = [o for o in options if o.get('inferred')]
        self.assertTrue(inferred)
        self.assertTrue(all(o.get('inferred') for o in options[len(options) - len(inferred):]))  # ranked last
        states = graph_for(self.token).ro_query('MATCH (s:LearningState) RETURN count(s)').result_set[0][0]
        self.assertEqual(states, 1)
        station = next(s for s in tutor.status(self.token)['stations'] if s['concept'] == inferred[0]['concept'])
        self.assertEqual(station['status'], 'unknown')
        self.assertTrue(station['inferred_from'])

    def test_every_answer_is_graph_structure(self):
        _, diag = self.scout()
        result = self.right(diag['task'])
        g = graph_for(self.token)
        path = g.ro_query('MATCH (r:Representation)<-[:IN]-(x:TaskIssue {id:$t})-[:PRODUCED]->(o:Observation)-[:ABOUT]->'
                          '(c:Concept)<-[:TEACHES]-(a:Activity)-[:OFFERS]->(r) RETURN count(*)', {'t': diag['task']}).result_set
        self.assertEqual(path[0][0], 1)
        self.assertIn('support streak', [q['name'] for q in result['queries']])
        self.assertEqual(result['evidence']['clean_correct_items'], 1)

    def test_changing_goal_closes_the_open_step_without_evidence(self):
        _, diag = self.scout()
        set_goal(self.token, 'mt_a1FdAsRKOF')  # Simple Fraction Sums, also a lesson route
        self.assertEqual(self.state()['state'], 'idle')
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.right(diag['task'])
        self.assertEqual(graph_for(self.token).ro_query('MATCH (o:Observation) RETURN count(o)').result_set[0][0], 0)
        self.scout()  # Scout can start on the new route

    def test_notebook_copied_before_the_lessons_existed_is_brought_up_to_date(self):
        g = graph_for(self.token)
        g.query('MATCH (a:Activity {kind:"lesson"}) DELETE a')
        g.query('MATCH (d:Dataset) SET d.activity_hash="old"')
        self.assertEqual(g.ro_query('MATCH (a:Activity) RETURN count(a)').result_set[0][0], 5)
        self.assertEqual(len(tutor.scout_route(self.token)['options']), 7)
        self.assertEqual(g.ro_query('MATCH (a:Activity)-[:TEACHES]->(:Concept) RETURN count(a)').result_set[0][0], 12)

    def test_roles_run_through_separate_mcp_servers_with_only_their_tools(self):
        events = []
        result = asyncio.run(step(self.token, events.append, use_model=False))
        listed = next(e for e in events if e['type'] == 'tools_listed')
        self.assertEqual(listed['tools'], sorted(tutor.ROLE_TOOLS['scout']))
        self.wrong(result['task']['task'])
        events.clear()
        result = asyncio.run(step(self.token, events.append, use_model=False))
        self.assertEqual(result['role'], 'tinker')
        self.assertEqual(next(e for e in events if e['type'] == 'tools_listed')['tools'], sorted(tutor.ROLE_TOOLS['tinker']))
        decision = next(e for e in events if e['type'] == 'model_decision')
        self.assertEqual(decision['chooser'], 'policy')
        stored = graph_for(self.token).ro_query('MATCH (d:RoleDecision) RETURN count(d)').result_set[0][0]
        self.assertEqual(stored, 2)


if __name__ == '__main__':
    unittest.main()
