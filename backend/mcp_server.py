"""Real stdio MCP server. Session capability comes from the harness, never model arguments."""
import json
import os
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from .investigation import learning_plan as plan, launch_check as launch

mcp = MCPServer('trellis', instructions='Use graph evidence to select a diagnostic. Do not invent learner responses or mastery.')

@mcp.tool(description='Read hard prerequisite closure, learner evidence, eligible diagnostic coverage and current revision from FalkorDB.')
def inspect_learning_goal() -> str:
    return json.dumps(plan(os.environ['TRELLIS_SESSION']))

@mcp.tool(description='Rank graph-derived diagnostics and source-criterion checks, with uncertainty, coverage and witness paths. Returns a bounded choice set.')
def rank_checks() -> str:
    p=plan(os.environ['TRELLIS_SESSION'])
    ready=[a for a in p['candidates'] if not a['missing']]
    return json.dumps({'candidates':(ready or p['candidates'])[:12],'revision':p['revision'],
                       'total_candidates':len(p['candidates']),'policy':'Prefer unresolved foundations; reports are not graded performance.'})

@mcp.tool(description='Inspect one concept from the current goal closure, its source criteria and scoped evidence. No arbitrary graph access.')
def inspect_concept(concept_id:str) -> str:
    p=plan(os.environ['TRELLIS_SESSION'])
    n=next((n for n in p['nodes'] if n['id']==concept_id),None)
    if not n:raise ToolError('Concept is outside this learning goal')
    return json.dumps(n)

@mcp.tool(description='Explain a permitted next diagnostic using source-backed graph paths, not model assertions.')
def explain_next_step(activity_id:str) -> str:
    p=plan(os.environ['TRELLIS_SESSION'])
    a=next((a for a in p['candidates'] if a['id']==activity_id),None)
    if not a:raise ToolError('Diagnostic no longer eligible')
    return json.dumps({'reason':a['title']+' investigates a foundation connected to '+str(a['coverage'])+' concepts in this route.',
                      'witness':a['witness'],'missing':a['missing'],'kind':a['kind'],'scope':p['scope']})

@mcp.tool(description='Launch one eligible diagnostic. ID and state revision must come from the graph plan.')
def launch_diagnostic(activity_id: str, revision: int) -> str:
    try:
        return json.dumps(launch(os.environ['TRELLIS_SESSION'], activity_id, revision))
    except ValueError as e:
        raise ToolError(str(e)) from e

if __name__ == '__main__':
    mcp.run(transport='stdio')
