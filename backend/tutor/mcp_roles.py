"""Role-scoped stdio MCP server. TRELLIS_ROLE decides which tools exist at all; the controller checks again per call.

The session and role come from the harness environment, never from model arguments. No role has a tool that
grades, writes evidence, reads answer keys or runs arbitrary Cypher.
"""
import json
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .session import ROLE_TOOLS, call

ROLE = os.environ.get('TRELLIS_ROLE', '')
JOBS = {'scout': 'Scout, the pathfinder: choose which foundation on the graph route to check next.',
        'tinker': 'Tinker, the experiment guide: choose how to teach the foundation Scout handed over.',
        'lens': 'Lens, the challenger: choose what kind of fresh transfer task to ask for.'}
if ROLE not in ROLE_TOOLS:
    raise SystemExit('TRELLIS_ROLE must be scout, tinker or lens')
mcp = MCPServer('trellis-' + ROLE, instructions=JOBS[ROLE] + ' You cannot grade or record learning.')


def run(tool, **args):
    try:
        return json.dumps(call(ROLE, os.environ['TRELLIS_SESSION'], tool, args))
    except (ValueError, PermissionError, KeyError) as e:
        raise ToolError(str(e)) from e


def scout_route() -> str:
    return run('scout_route')


def scout_inspect(concept_id: str) -> str:
    return run('scout_inspect', concept_id=concept_id)


def scout_choose(activity_id: str, version: int) -> str:
    return run('scout_choose', activity_id=activity_id, version=version)


def tinker_handoff() -> str:
    return run('tinker_handoff')


def tinker_inspect() -> str:
    return run("tinker_inspect")


def tinker_probe(diagnostic_id: str, version: int) -> str:
    return run("tinker_probe", diagnostic_id=diagnostic_id, version=version)


def tinker_teach(representation: str, opening: str, version: int, strategy: str = "") -> str:
    return run('tinker_teach', representation=representation, opening=opening, version=version, strategy=strategy or None)


def lens_handoff() -> str:
    return run('lens_handoff')


def lens_transfer(representation: str, version: int) -> str:
    return run('lens_transfer', representation=representation, version=version)


DESCRIPTIONS = {
    'scout_route': 'Read the graph-ranked foundations on this goal that have a lesson, with FalkorDB rank, coverage and witness path.',
    'scout_inspect': 'Read one concept on this route: source criteria, evidence status and its lesson.',
    'scout_choose': 'Issue a fresh check for one listed foundation. Needs the current tutor version.',
    'tinker_handoff': "Read Scout's handoff, the permitted representations and lesson openings.",
    'tinker_inspect': 'Inspect recent responses once before teaching. No task parameters or answer keys.',
    'tinker_probe': 'Request one distinguishing check from graph-linked diagnostics. Never counts towards support.',
    'tinker_teach': 'Start a lesson with one permitted representation and opening. Needs the current tutor version.',
    'lens_handoff': "Read Tinker's handoff and the permitted transfer strategies. No task parameters or answers.",
    'lens_transfer': 'Request a fresh transfer task in one permitted representation. The controller picks the item.',
}
for name in ROLE_TOOLS[ROLE]:
    mcp.add_tool(globals()[name], name=name, description=DESCRIPTIONS[name])

if __name__ == '__main__':
    mcp.run(transport='stdio')
