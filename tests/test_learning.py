"""Integration checks against isolated synthetic FalkorDB graphs, never real learner data."""
import unittest
from backend.core import create_session, graph_for, plan, launch, submit, registry

class Learning(unittest.TestCase):
    def setUp(self): self.token=create_session()['token']
    def tearDown(self): graph_for(self.token).delete()

    def test_graph_changes_next_action_and_deduplicates(self):
        first=plan(self.token)
        self.assertEqual(len(first['nodes']),5)
        aid=first['selected']['id']
        answers=next(a['items'] for a in registry() if a['id']==aid)
        for item in answers:
            p=plan(self.token); action=launch(self.token,aid,p['revision'])
            result=submit(self.token,action['action'],item['answer'])
            self.assertEqual(submit(self.token,action['action'],item['answer']),result)
        after=plan(self.token)
        self.assertNotEqual(after['selected']['id'],aid)
        self.assertEqual(after['revision'],2)

    def test_stale_and_foreign_actions_refused(self):
        p=plan(self.token); aid=p['selected']['id']
        one=launch(self.token,aid,0); two=launch(self.token,aid,0)
        submit(self.token,one['action'],0)
        with self.assertRaisesRegex(ValueError,'Stale'): submit(self.token,two['action'],0)
        other=create_session()['token']
        try:
            with self.assertRaisesRegex(ValueError,'Unknown action'):submit(other,one['action'],0)
        finally:graph_for(other).delete()

    def test_wrong_response_does_not_create_support(self):
        p=plan(self.token); a=launch(self.token,p['selected']['id'],0)
        item=next(i for r in registry() for i in r['items'] if i['id']==a['item']['id'])
        result=submit(self.token,a['action'],(item['answer']+1)%len(item['options']))
        self.assertFalse(result['correct']);self.assertEqual(result['status'],'needs_check')
        self.assertEqual(result['distinct_checks'],0)

if __name__=='__main__':unittest.main()
