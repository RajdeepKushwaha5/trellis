"""FalkorDB features the product relies on: constraints, full-text search, EXPLAIN and graph-decided probe offers."""
import unittest

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import BASE, create_session, db, fulltext_terms, graph_for


class Schema(unittest.TestCase):
    def test_learner_graphs_inherit_unique_constraints(self):
        token = create_session()['token']
        try:
            g = graph_for(token)
            constrained = {(c['label'], tuple(c['properties'])) for c in g.list_constraints()}
            self.assertIn(('TaskIssue', ('id',)), constrained)
            self.assertIn(('Observation', ('id',)), constrained)
            g.query('CREATE (:Observation {id:"same"})')
            with self.assertRaisesRegex(Exception, 'unique constraint'):
                g.query('CREATE (:Observation {id:"same"})')
        finally:
            graph_for(token).delete()

    def test_full_text_search_ranks_by_relevance(self):
        rows = db().select_graph(BASE).ro_query(
            "CALL db.idx.fulltext.queryNodes('Concept',$q) YIELD node,score RETURN node.name ORDER BY score DESC LIMIT 3",
            {'q': fulltext_terms('fractions number line')}).result_set
        self.assertIn('number line', rows[0][0].lower())
        self.assertEqual(fulltext_terms('frac"tions) OR *'), 'frac* tions* or*')


class Api(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.client.post('/api/session')

    def tearDown(self):
        token = self.client.cookies.get('trellis_session')
        if token:
            graph_for(token).delete()
        self.client.__exit__(None, None, None)

    def test_explain_accepts_only_the_products_own_queries(self):
        from backend.reasoning import CLOSURE
        ok = self.client.post('/api/explain', json={'cypher': CLOSURE})
        self.assertEqual(ok.status_code, 200)
        self.assertIn('Conditional Variable Length Traverse', ok.json()['plan'])
        refused = self.client.post('/api/explain', json={'cypher': 'MATCH (n) DETACH DELETE n'})
        self.assertEqual(refused.status_code, 400)

    def test_symbol_only_search_matches_nothing(self):
        for q in ['.*+?[](){}|^$', '%%%', '<>']:
            self.assertEqual(self.client.get('/api/curriculum', params={'q': q}).json()['total'], 0, q)
        self.assertEqual(self.client.get('/api/curriculum', params={'q': 'f'}).json()['total'], 1590)  # still typing

    def test_curriculum_search_uses_full_text(self):
        d = self.client.get('/api/curriculum', params={'subject': 'Mathematics', 'q': 'fractions'}).json()
        self.assertGreater(d['total'], 0)
        self.assertTrue(any('fraction' in c['name'].lower() for c in d['concepts'][:5]))


class ProbeOffers(unittest.TestCase):
    def test_probes_are_offered_only_for_ambiguous_mistakes(self):
        from backend.tutor.fixtures import seed
        for difficulty, rep, expect in [('placement', 'ticks', True), ('counted_marks', 'read', False)]:
            token, ctx = seed({'id': difficulty, 'activity': 'line-first', 'rep': rep, 'difficulty': difficulty})
            try:
                self.assertEqual(bool(ctx['probe_options']), expect, difficulty)
            finally:
                graph_for(token).delete()


if __name__ == '__main__':
    unittest.main()
