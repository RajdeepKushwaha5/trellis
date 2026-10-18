"""One foundation episode end to end: ambiguity forces investigation, a failed strategy is not repeated."""
import unittest
from uuid import uuid4

from backend.core import graph_for
from backend.tutor import fractions as e
from backend.tutor import session as t
from backend.tutor.fixtures import respond_with, seed


class Recovery(unittest.TestCase):
    def setUp(self):
        self.token, self.ctx = seed({'id': 'recovery', 'activity': 'line-first', 'rep': 'ticks', 'difficulty': 'placement'})

    def tearDown(self):
        graph_for(self.token).delete()

    def test_ambiguity_forces_a_check_then_a_failed_strategy_is_not_repeated(self):
        ctx = self.ctx
        # 1. An ambiguous placement: teaching is refused on the server until a distinguishing check is asked.
        self.assertTrue(ctx['investigation_status']['required'])
        with self.assertRaisesRegex(ValueError, 'Investigation is required'):
            t.tinker_teach(self.token, 'fine', 'example_first', ctx['version'])
        probe = t.tinker_probe(self.token, 'read-unit', ctx['version'])
        # 2. The check points to counting marks; the next lesson uses the strategy connected to that.
        result = respond_with(self.token, probe['task'], 'counted_marks')
        self.assertIn('counting marks', result['note'])
        ctx = t.tinker_handoff(self.token)
        self.assertEqual(ctx['investigation_status']['probe_outcome']['kind'], 'pointed')
        self.assertFalse(ctx['investigation_status']['required'])
        ids = [s['id'] for s in ctx['teaching_strategies']]
        self.assertIn('walk-gaps', ids)
        rep = next(r['id'] for r in ctx['representations'] if r['id'] in ('ticks', 'fine'))
        lesson = t.tinker_teach(self.token, rep, 'example_first', ctx['version'], 'walk-gaps')
        respond_with(self.token, lesson['task'], None)
        # 3. A fresh transfer check still fails.
        lens = t.lens_handoff(self.token)
        transfer = t.lens_transfer(self.token, lens['strategies'][0]['id'], lens['version'])
        self.assertEqual(respond_with(self.token, transfer['task'], 'any')['next_role'], 'tinker')
        # 4. The tried strategy is excluded, with a reason, and refused if asked for again.
        ctx = t.tinker_handoff(self.token)
        tried = ctx['investigation_status']['tried_strategies']
        self.assertEqual([x['id'] for x in tried], ['walk-gaps'])
        self.assertNotIn('walk-gaps', [s['id'] for s in ctx['teaching_strategies']])
        self.assertTrue(ctx['teaching_strategies'])
        with self.assertRaisesRegex(ValueError, 'already tried'):
            t.tinker_teach(self.token, ctx['representations'][0]['id'], 'try_first', ctx['version'], 'walk-gaps')
        nxt = ctx['teaching_strategies'][0]
        rep2 = next(r['id'] for r in ctx['representations'] if r['id'] in nxt['reps'])
        second = t.tinker_teach(self.token, rep2, 'try_first', ctx['version'], nxt['id'])
        self.assertNotEqual(second['teaching_strategy']['id'], 'walk-gaps')
        # 5. The graph keeps the whole episode: observed, suggested, tried.
        steps = t.episode_view(self.token)['steps']
        self.assertEqual([s['purpose'] for s in steps], ['diagnostic', 'probe', 'lesson', 'transfer'])
        self.assertTrue(steps[0]['ambiguous'])
        self.assertIn('marks', steps[1]['explanation'])
        self.assertEqual(steps[2]['strategy'], 'Walk the gaps from zero')
        self.assertFalse(steps[3]['correct'])

    def test_an_inconclusive_check_falls_back_to_the_original_mistake(self):
        probe = t.tinker_probe(self.token, 'read-unit', self.ctx['version'])
        result = respond_with(self.token, probe['task'], None)
        self.assertIn('did not single out', result['note'])
        ctx = t.tinker_handoff(self.token)
        self.assertEqual(ctx['investigation_status']['probe_outcome']['kind'], 'inconclusive')
        self.assertFalse(ctx['investigation_status']['required'])
        self.assertTrue({'walk-gaps', 'anchor-zero'} & {s['id'] for s in ctx['teaching_strategies']})

    def test_an_unavailable_check_is_disclosed_not_required(self):
        # Exhaust every item of both distinguishing checks (reading and placing), as a long-running notebook would.
        act = t.activities()['line-first']
        keys = [e.key(p) for rep in ('read', 'ticks') for p in e.pool('number_line', rep, act['params'])]
        graph_for(self.token).query('UNWIND $keys AS k CREATE (:TaskIssue {id:k + $suffix, key:k, purpose:"example", used:true})',
                                    {'keys': keys, 'suffix': uuid4().hex})
        ctx = t.tinker_handoff(self.token)
        self.assertFalse(ctx['investigation_status']['required'])
        self.assertIn('none is available', ctx['investigation_status']['note'])
        self.assertTrue(ctx['teaching_strategies'])


if __name__ == '__main__':
    unittest.main()
