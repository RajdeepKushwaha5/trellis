"""Bounded model-selected investigation tools over actual stdio MCP."""
import json
import os
import sys
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .core import ROOT, digest

async def choose(token, emit=None, model_override=None):
    env=dict(os.environ,TRELLIS_SESSION=token)
    trace=[];usage=[];inspected=set();ranked=None;offered=[]
    model=model_override or os.getenv('TRELLIS_MODEL','qwen2.5:7b')
    def event(kind,**data):
        if emit:emit({'type':kind,**data})
    async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','backend.mcp_server'],cwd=str(ROOT),env=env)) as (read,write):
      async with ClientSession(read,write) as client:
        await client.initialize()
        async def call(name,args):
            event('tool_started',tool=name,arguments=args)
            value=await client.call_tool(name,args)
            if value.is_error:raise ValueError('MCP action refused: '+name)
            result=json.loads(next(b.text for b in value.content if b.type=='text'))
            trace.append({'tool':name,'arguments':args,'result_hash':digest(result),'offered_tools':list(offered),
                          'source':'harness prerequisite' if name=='inspect_learning_goal' else 'model-selected' if name in ('rank_checks','inspect_concept','launch_diagnostic') else 'controller explanation'})
            event('tool_finished',**trace[-1])
            return result
        p=await call('inspect_learning_goal',{})
        if not p['candidates']:return {'complete':True,'trace':trace,'reason':'No unchecked criteria or prototype diagnostics remain. Review the route uncertainties.'}
        async with httpx.AsyncClient(timeout=90) as http:
            tags=await http.get('http://127.0.0.1:11434/api/tags');tags.raise_for_status()
            artifact=next((m for m in tags.json().get('models',[]) if m['name']==model),{})
            runtime=await http.get('http://127.0.0.1:11434/api/version')
            for step in range(5):
                offered=['rank_checks'] if ranked is None else ['launch_diagnostic']+(['inspect_concept'] if len(inspected)<2 else [])
                candidates=(ranked or {}).get('candidates',[])
                schema={'type':'object','properties':{'tool':{'type':'string','enum':offered},
                        'activity_id':{'type':'string','enum':[a['id'] for a in candidates] or ['']},
                        'reason':{'type':'string'}},'required':['tool','activity_id','reason'],'additionalProperties':False}
                evidence={'goal':p['goal']['name'],'allowed_tools':offered,'candidates':candidates,
                          'inspected':list(inspected),'revision':p['revision']}
                event('model_started',step=step+1,model=model,offered_tools=offered,candidate_count=len(candidates))
                response=await http.post('http://127.0.0.1:11434/api/chat',json={'model':model,'stream':False,'keep_alive':0,
                    'format':schema,'options':{'temperature':0,'num_ctx':4096,'num_predict':200},
                    'messages':[{'role':'system','content':'You guide a learning investigation using graph tools. First rank checks. Then launch a high-ranked unresolved foundation, or inspect a candidate concept if more detail helps. Parent reports are not graded answers. Choose only offered tools and candidate IDs. Keep the reason short.'},
                                {'role':'user','content':json.dumps(evidence)}]})
                response.raise_for_status();payload=response.json();decision=json.loads(payload['message']['content'])
                usage.append({'input':payload.get('prompt_eval_count'),'output':payload.get('eval_count')})
                event('model_decision',step=step+1,decision=decision,offered_tools=offered,usage=usage[-1],
                      ranked_options=[{'id':a['id'],'title':a['title']} for a in candidates])
                if decision['tool'] not in offered:raise ValueError('Model selected unavailable tool')
                if decision['tool']=='rank_checks':
                    ranked=await call('rank_checks',{});continue
                candidate=next((a for a in candidates if a['id']==decision['activity_id']),None)
                if not candidate:raise ValueError('Model selected an unsupported diagnostic')
                if decision['tool']=='inspect_concept':
                    details=await call('inspect_concept',{'concept_id':candidate['concept']});inspected.add(details['id'])
                    # Return bounded inspected evidence to the next model step.
                    ranked['candidates']=[{**a,'source_criteria':details['criteria'][:3],'evidence_status':details['status']} if a['concept']==details['id'] else a for a in candidates]
                    continue
                explanation=await call('explain_next_step',{'activity_id':candidate['id']})
                action=await call('launch_diagnostic',{'activity_id':candidate['id'],'revision':p['revision']})
                return {'action':action,'model':model,'reason':explanation['reason'],'witness':explanation['witness'],
                        'model_reason_unverified':decision['reason'],'trace':trace,'usage':{
                        'input':sum(u['input'] for u in usage) if all(u['input'] is not None for u in usage) else None,
                        'output':sum(u['output'] for u in usage) if all(u['output'] is not None for u in usage) else None,
                        'calls':len(usage),'records':usage},'plan_fingerprint':p['fingerprint'],
                        'provenance':{'model_digest':artifact.get('digest'),'ollama_version':runtime.json().get('version') if runtime.is_success else None,
                                      'options':{'temperature':0,'num_ctx':4096,'num_predict':200},'interface':'bounded schema-constrained tool selection over real MCP'}}
            raise ValueError('Investigation stopped at its five-decision budget. No further action was launched.')
