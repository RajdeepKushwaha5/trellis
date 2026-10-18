"""Every generated task is verified by an independent method, not by re-running the engine's own answer logic."""
import json
import unittest
from collections import Counter
from math import isclose

from backend.tutor import fractions as e
from backend.tutor.session import catalog, family_of

LEAKS = ('answer', 'solution', 'correct', 'steps', 'explanation')


def every_task():
    for a in catalog()['activities']:
        for rep in a['representations']:
            for p in e.pool(family_of(a), rep, a['params']):
                yield a, p


def floats(parts):
    return [int(x.split('/')[0]) / int(x.split('/')[1]) for x in parts]


def equal_split(option, n):
    """Independent check with floats and cell counting: n parts, all the same size, covering one whole."""
    if option['shape'] == 'grid':
        counts = Counter(option['cells'].replace('/', ''))
        return len(counts) == n and len(set(counts.values())) == 1
    sizes = floats(option['parts'])
    return len(sizes) == n and isclose(sum(sizes), 1) and all(isclose(s, 1 / n) for s in sizes)


class Engine(unittest.TestCase):
    def test_pools_are_finite_unique_and_mapped_to_real_criteria(self):
        seen, owners = set(), {}
        for a, p in every_task():
            k = e.key(p)
            owners.setdefault(k, set()).add(a['id'])
            seen.add(k)
        for a in catalog()['activities']:
            for rep in a['representations']:
                keys = [e.key(p) for p in e.pool(family_of(a), rep, a['params'])]
                self.assertEqual(len(keys), len(set(keys)), (a['id'], rep))
        # Identity is global: a quarters grid shared by two activities is one task, so using it in one retires it in both.
        shared = {k for k, o in owners.items() if len(o) > 1}
        self.assertTrue(shared)
        a, b = (x for x in catalog()['activities'] if x['id'] in ('fair-quarters', 'fair-shares'))
        used = {e.key(p) for p in e.pool('equal_parts', 'grid', a['params'])}
        self.assertNotIn(e.key(e.pick('equal_parts', 'grid', b['params'], used, 'seed')), used)
        self.assertGreater(len(seen), 500)
        self.assertTrue(all(a['criteria'] for a in catalog()['activities']))

    def test_every_answer_key_matches_an_independent_check(self):
        for a, p in every_task():
            view, sol = e.public(p), e.solution(p)
            if p['family'] == 'equal_parts':
                # Exactly one picture is a fair split, and the key points at it.
                fair = [i for i, o in enumerate(view['options']) if equal_split(o, p['n'])]
                self.assertEqual(fair, [sol['choice']], p)
                for o in view['options']:
                    if o['shape'] != 'grid':
                        self.assertTrue(isclose(sum(floats(o['parts'])), 1), p)
            elif p['family'] == 'build':
                target = p['a'] / p['b']
                accepted = [n for n in range(view['parts'] + 1)
                            if e.grade(p, {'shaded': list(range(n))})['correct']]
                self.assertEqual(accepted, [n for n in range(view['parts'] + 1) if isclose(n / view['parts'], target)], p)
                self.assertEqual(len(accepted), 1, p)
            elif p['rep'] == 'read':
                point = p['i'] / p['t']
                values = [int(x.split('/')[0]) / int(x.split('/')[1]) for x in view['options']]
                self.assertEqual([i for i, v in enumerate(values) if isclose(v, point)], [sol['choice']], p)
            else:
                ticks = view['ticks_per_unit'] * view['span']
                target = p['a'] / p['b']
                hits = [j for j in range(ticks + 1) if isclose(j / view['ticks_per_unit'], target)]
                self.assertEqual(hits, [sol['tick']], p)
                self.assertTrue(e.grade(p, sol)['correct'])

    def test_browser_payload_never_carries_the_answer(self):
        positions = Counter()
        for a, p in every_task():
            text = json.dumps(e.public(p)).lower()
            for word in LEAKS:
                self.assertNotIn(f'"{word}"', text)
            if 'choice' in e.solution(p):
                positions[e.solution(p)['choice']] += 1
        # The right picture is not always in the same slot.
        self.assertEqual(set(positions), {0, 1, 2})

    def test_invalid_responses_are_refused_not_scored(self):
        p = e.pool('build', 'bar', {'b': [4]})[0]
        for bad in [{}, {'shaded': [0, 0]}, {'shaded': [99]}, {'shaded': 'all'}, {'choice': 1}, None]:
            with self.assertRaises(ValueError):
                e.grade(p, bad)
        q = e.pool('number_line', 'ticks', {'b': [4], 'span': [1]})[0]
        for bad in [{'tick': -1}, {'tick': 5}, {'tick': 1.5}, {'tick': True}]:
            with self.assertRaises(ValueError):
                e.grade(q, bad)

    def test_wrong_answers_name_the_difficulty_without_claiming_a_misconception(self):
        p = next(x for x in e.pool('equal_parts', 'bar', {'n': [4]}))
        kinds = [e.grade(p, {'choice': i})['difficulty'] for i in range(3)]
        self.assertEqual(sorted(k or '' for k in kinds), ['', 'unequal_parts', 'wrong_count'])

    def test_exhaustion_is_disclosed_instead_of_repeating(self):
        allowed = {'b': [2, 3, 4], 'span': [1]}
        used = set()
        for _ in range(len(e.pool('number_line', 'ticks', allowed))):
            used.add(e.key(e.pick('number_line', 'ticks', allowed, used, 'seed')))
        with self.assertRaises(e.Exhausted):
            e.pick('number_line', 'ticks', allowed, used, 'seed')

    def test_hints_and_examples_are_finite_and_server_side(self):
        for a, p in every_task():
            self.assertTrue(2 <= len(e.hints(p)) <= 3)
            ex = e.example(p)
            self.assertTrue(e.grade(p, ex['solution'])['correct'])


if __name__ == '__main__':
    unittest.main()
