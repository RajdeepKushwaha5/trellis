"""Repeatable software evaluation, without claiming learning effectiveness."""
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from .core import ROOT, db, BASE, registry, all_activities


def main():
    tests=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(verbosity=2).run(tests)
    g=db().select_graph(BASE)
    counts={
        'concepts':g.ro_query('MATCH (c:Concept) RETURN count(c)').result_set[0][0],
        'hard_edges':g.ro_query('MATCH ()-[r:REQUIRES]->() RETURN count(r)').result_set[0][0],
        'soft_edges':g.ro_query('MATCH ()-[r:BENEFITS_FROM]->() RETURN count(r)').result_set[0][0],
        'concepts_without_source_criteria':g.ro_query('MATCH (c:Concept) WHERE size(c.criteria)=0 RETURN count(c)').result_set[0][0],
        'prototype_activities':len(registry()),
        'fraction_lessons':len([a for a in all_activities() if a['kind']=='lesson']),
        'activity_nodes':g.ro_query('MATCH (a:Activity)-[:TEACHES]->(:Concept) RETURN count(a)').result_set[0][0]}
    code={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
          for folder in ('backend','web','tests','activities') for p in (ROOT/folder).rglob('*')
          if p.is_file() and p.suffix in ('.py','.js','.css','.html','.json') and '__pycache__' not in p.parts}
    report={'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'counts':counts,'source_hashes':code,
            'scope':'Software behaviour on synthetic profiles. No learning-effectiveness or token-reduction claim.'}
    folder=ROOT/'artifacts';folder.mkdir(exist_ok=True)
    (folder/'evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_hashes'},indent=2))
    if not report['passed']:sys.exit(1)

if __name__=='__main__':main()
