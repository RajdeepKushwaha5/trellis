"""Small paired live model comparison. Synthetic action quality, not educational effectiveness."""
import asyncio
import json
import time
from .core import ROOT,db,BASE,GOAL,create_session,graph_for
from .investigation import set_goal,learning_plan
from .agent import choose

async def main():
    math=db().select_graph(BASE).ro_query('MATCH (c:Concept) WHERE c.name="Adding Fractions (Same Denominator)" RETURN c.id LIMIT 1').result_set[0][0]
    cases=[('water',GOAL),('fractions',math)];results=[]
    for name,goal in cases:
      for model in ('qwen2.5:3b','qwen2.5:7b'):
        token=create_session()['token'];start=time.perf_counter()
        try:
            set_goal(token,goal);p=learning_plan(token)
            ready=[a for a in p['candidates'] if not a['missing']]
            eligible=(ready or p['candidates'])[:12]
            result=await choose(token,model_override=model)
            selected=result['action']['activity']['id']
            record={'case':name,'model':model,'completed':True,'valid_action':selected in {a['id'] for a in eligible},
                    'top_ranked':selected==eligible[0]['id'],'selected':selected,'frozen_options':[a['id'] for a in eligible],
                    'wall_s':round(time.perf_counter()-start,3),'result':result}
        except Exception as e:record={'case':name,'model':model,'completed':False,'wall_s':round(time.perf_counter()-start,3),'error':str(e)}
        finally:graph_for(token).delete()
        results.append(record)
        report={'cases':results,'scope':'Two synthetic goals per model, identical goal/state settings. One trial each; not a model-quality or learning-effectiveness benchmark.'}
        (ROOT/'artifacts/model-comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k!='result'}),flush=True)

if __name__=='__main__':asyncio.run(main())
