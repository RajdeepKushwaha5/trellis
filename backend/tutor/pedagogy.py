"""Small prototype teaching catalog. Hypotheses are possibilities, never diagnoses.
Text and strategy mappings are authored policy, not validated pedagogy.
"""
import hashlib
import json

STRATEGIES = [
 {'id':'compare-area','family':'equal_parts','title':'Compare the areas, then count','addresses':['unequal_parts'], 'reps':['grid','bar','circle'],
  'instruction':'First compare how much space each share covers. Equal shares must cover the same amount. Then count the shares.'},
 {'id':'count-shares','family':'equal_parts','title':'Count the equal shares','addresses':['wrong_count'], 'reps':['bar','circle','grid'],
  'instruction':'Check that the shares are equal. Touch each share once as you count. Halves need two equal shares; quarters need four.'},
 {'id':'group-whole','family':'build','title':'Group the whole into denominator shares','addresses':['shade_count'], 'reps':['set','bar','circle'],
  'instruction':'Find the whole first. Split all its pieces into the number of equal groups on the bottom of the fraction. Shade the number of groups on top.'},
 {'id':'walk-gaps','family':'number_line','title':'Walk the gaps from zero','addresses':['counted_marks','off_by_one','placement'], 'reps':['ticks','fine'],
  'instruction':'Put your finger on zero. A jump to the next mark is one gap. Count equal jumps, not the starting mark. Each jump is one part of the unit.'},
 {'id':'anchor-zero','family':'number_line','title':'Anchor the whole between zero and one','addresses':['from_right','placement'], 'reps':['ticks','read','fine'],
  'instruction':'Find zero and one first. Start at zero and move right. The denominator counts equal gaps in one whole; the numerator counts gaps from zero.'},
 {'id':'read-intervals','family':'number_line','title':'Read the unit before the point','addresses':['counted_marks','placement'], 'reps':['read','ticks','fine'],
  'instruction':'Count the equal gaps from zero to one for the denominator. Then count gaps from zero to the point for the numerator. A mark is an endpoint, not an extra gap.'},
]
HYPOTHESES = {
 'unequal_parts':'May be counting pieces without comparing their areas',
 'wrong_count':'May be overlooking how many equal shares are required',
 'shade_count':'May be treating pieces as shares without identifying the whole',
 'counted_marks':'May be counting marks instead of intervals',
 'off_by_one':'May be including the starting mark in the count',
 'from_right':'May be counting from one rather than zero',
 'placement':'The response does not distinguish interval counting, unit size or direction',
}
PROBES = [
 {'id':'read-unit','family':'number_line','rep':'read','title':'Read a marked point','distinguishes':['counted_marks','from_right','off_by_one','placement'],
  'why':'A fresh reading task can reveal marks-versus-gaps or direction errors. One response still cannot establish a diagnosis.'},
 {'id':'place-unit','family':'number_line','rep':'ticks','title':'Place a point from zero','distinguishes':['placement','from_right','counted_marks'],
  'why':'Compare placement with the previous response before choosing an explanation.'},
 {'id':'compare-shares','family':'equal_parts','rep':'grid','title':'Compare equal-area shares','distinguishes':['unequal_parts','wrong_count'],
  'why':'The alternatives separate unequal areas from the wrong number of shares.'},
]
VERSION=hashlib.sha256(json.dumps([STRATEGIES,HYPOTHESES,PROBES],sort_keys=True).encode()).hexdigest()


def ensure(g):
    rows=g.ro_query('MATCH (p:TeachingCatalog {id:"teaching-v1"}) RETURN p.version').result_set
    if rows and rows[0][0]==VERSION:return
    g.query('UNWIND $rows AS h MERGE (x:DifficultyHypothesis {id:h.id}) SET x.text=h.text',
            {'rows':[{'id':k,'text':v} for k,v in HYPOTHESES.items()]})
    g.query('UNWIND $rows AS s MERGE (x:TeachingStrategy {id:s.id}) SET x.title=s.title,x.family=s.family,'
            'x.instruction=s.instruction,x.reps=s.reps WITH x,s UNWIND s.addresses AS code '
            'MATCH (h:DifficultyHypothesis {id:code}) MERGE (x)-[:ADDRESSES]->(h)',{'rows':STRATEGIES})
    g.query('UNWIND $rows AS d MERGE (x:Diagnostic {id:d.id}) SET x.title=d.title,x.family=d.family,x.rep=d.rep,x.why=d.why '
            'WITH x,d UNWIND d.distinguishes AS code MATCH (h:DifficultyHypothesis {id:code}) MERGE (x)-[:DISTINGUISHES]->(h)',{'rows':PROBES})
    g.query('MATCH (a:Activity)-[:ADDRESSES]->(o:Objective) MATCH (s:TeachingStrategy) '
            'WHERE (o.id="number-line-v1" AND s.family="number_line") OR '
            '(o.id="equal-parts-v1" AND s.family="equal_parts") OR (o.id="build-fraction-v1" AND s.family="build") '
            'MERGE (a)-[:USES_STRATEGY]->(s)')
    g.query('MERGE (p:TeachingCatalog {id:"teaching-v1"}) SET p.version=$v',{'v':VERSION})


def link_observation(g,task):
    ensure(g)
    g.query('MATCH (x:TaskIssue {id:$task})-[:PRODUCED]->(o:Observation) '
            'MATCH (h:DifficultyHypothesis) WHERE h.id=o.difficulty MERGE (o)-[:SUGGESTS]->(h)',{'task':task})
