"""Runs whichever role is due, each in its own MCP process and its own prompt context.

The model (or, when asked, a declared policy fallback) chooses one option from a set the controller computed.
Prompts contain only that role's visible inputs. Nothing from one role's conversation is passed to another; the
handoff is the structured record the controller stored.
"""
import json
import os
import random
import sys

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..core import ROOT, digest
from .session import DUE, ROLE_TOOLS, WAITING, graph_for, _tutor, pause_if_stuck, record_decision, status

PROMPTS = {
    'scout': 'You are Scout, the pathfinder. You read a learning route computed by a graph database and decide which '
             'foundation to check next. Prefer foundations that are uncertain and support much of the route. You may '
             'inspect a concept first if its criteria would change your choice. You cannot teach, grade or record learning.',
    'tinker': 'You are Tinker, the experiment guide. A foundation was not yet shown on a check. Choose one permitted '
              'representation and opening for a short lesson. If an earlier lesson did not work, a different '
              'representation is required. Use the recorded mistake to select a connected teaching strategy, not just a picture style. '
              'For an ambiguous placement error, prefer a distinguishing probe before assuming a cause. You can inspect history once. '
              'Hypotheses are uncertain. You cannot see transfer answers, grade, or declare success.',
    'lens': 'You are Lens, the challenger. Choose the kind of fresh transfer task that best tests whether the idea '
            'carries over to a different representation from the one taught. Consider the observed difficulty. You never '
            'see task parameters or answers and cannot grade.',
}
OPTIONS = {'temperature': 0, 'num_ctx': 4096, 'num_predict': 160}


def options_for(role, ctx, inspected):
    """(option id, label, tool, arguments) for every permitted move. Built by code, not by the model."""
    if role == 'scout':
        out = [(o['id'], f'Check {o["title"]} ({o["concept_name"]})' + (f'; {o["reasons"][0]}' if o.get('reasons') else ''),
                'scout_choose', {'activity_id': o['id'], 'version': ctx['version']}) for o in ctx['options']]
        if len(inspected) < 2:
            out += [('inspect:' + o['concept'], f'Inspect {o["concept_name"]} first', 'scout_inspect',
                     {'concept_id': o['concept']}) for o in ctx['options'] if o['concept'] not in inspected][:4]
        return out
    if role == 'tinker':
        out = [(f'{r["id"]}+{o["id"]}', f'Teach with {r["label"]}; {o["label"].lower()}', 'tinker_teach',
                 {'representation': r['id'], 'opening': o['id'], 'version': ctx['version']})
                for r in ctx['representations'] for o in ctx['openings']]
        out += [(f'strategy:{s["id"]}:{r["id"]}:{o["id"]}', f'{s["title"]}; {r["label"]}; {o["label"]}', 'tinker_teach',
                 {'representation': r['id'], 'opening': o['id'], 'strategy': s['id'], 'version': ctx['version']})
                for s in ctx['teaching_strategies'] for r in ctx['representations'] if r['id'] in s['reps']
                for o in ctx['openings']]
        out += [('probe:' + d['id'], 'Investigate first: ' + d['title'] + '. ' + d['why'], 'tinker_probe',
                 {'diagnostic_id':d['id'], 'version':ctx['version']}) for d in ctx['probe_options']]
        if ctx['inspection_available']:
            out.append(('inspect:history', 'Inspect recent responses before choosing', 'tinker_inspect', {}))
        return out
    return [(s['id'], f'Transfer task using {s["label"]} ({s["remaining"]} unused)', 'lens_transfer',
             {'representation': s['id'], 'version': ctx['version']}) for s in ctx['strategies']]


RULE_WHY = {'scout': "Take FalkorDB's top-ranked foundation.",
            'tinker': 'No strategy is connected to this mistake; teach with the first permitted representation.',
            'lens': 'Take the first permitted transfer representation.'}


def rule_choice(role, ctx, opts):
    """The deterministic mistake-aware rule: the no-model mode, and the baseline the model is compared against.
    Scout takes FalkorDB's ranking. Tinker asks a distinguishing check when the mistake is ambiguous, otherwise uses
    the strategy the graph connects to the recorded mistake. Returns (option, why)."""
    acting = [o for o in opts if o[2] not in ('scout_inspect', 'tinker_inspect')] or opts
    if role == 'tinker':
        if ctx.get('observed_difficulty') == 'placement':
            probe = next((o for o in acting if o[2] == 'tinker_probe' and o[3]['diagnostic_id'] == 'read-unit'), None) \
                or next((o for o in acting if o[2] == 'tinker_probe'), None)
            if probe:
                return probe, 'The mistake does not say why; ask a check whose wrong answers tell the explanations apart.'
        strategy = next((o for o in acting if o[3].get('strategy')), None)
        if strategy:
            return strategy, 'Use the teaching strategy the graph connects to the recorded mistake.'
    return acting[0], RULE_WHY[role]


def visible(role, ctx):
    """What the role's prompt may contain. Witness paths and ranks for Scout; handoffs for Tinker and Lens."""
    if role == 'scout':
        return {'goal': ctx['goal'], 'policy': ctx['policy'],
                'foundations': [{k: o[k] for k in ('id', 'title', 'concept_name', 'graph_rank', 'coverage',
                                                   'uncertain_prerequisites', 'evidence', 'witness', 'purpose', 'reasons')}
                                for o in ctx['options']], 'inspected': ctx.get('inspected', {})}
    if role == 'tinker':
        return {k: ctx[k] for k in ('objective_text', 'representations', 'openings', 'previous_lessons',
                                    'observed_difficulty', 'difficulty_meaning', 'difficulty_representation', 'investigation',
                                    'teaching_strategies', 'probe_options', 'probe_budget_remaining', 'boundary')} | {'foundation': ctx['handoff'], 'inspected':ctx.get('inspected', {})}
    return {k: ctx[k] for k in ('handoff', 'teaching_representation', 'teaching_opening', 'observed_difficulty',
                                'strategies', 'excluded', 'rule', 'difficulty_meaning', 'difficulty_representation', 'boundary')}


async def decide(http, role, model, ctx, opts):
    schema = {'type': 'object', 'properties': {'option': {'type': 'string', 'enum': [o[0] for o in opts]},
              'reason': {'type': 'string'}}, 'required': ['option', 'reason'], 'additionalProperties': False}
    r = await http.post('http://127.0.0.1:11434/api/chat', json={
        'model': model, 'stream': False, 'keep_alive': '5m', 'format': schema, 'options': OPTIONS,
        'messages': [{'role': 'system', 'content': PROMPTS[role] + ' Choose exactly one option id. Keep the reason to one sentence.'},
                     {'role': 'user', 'content': json.dumps({'inputs': visible(role, ctx),
                                                             'options': [{'id': o[0], 'label': o[1]} for o in opts]})}]})
    r.raise_for_status()
    payload = r.json()
    decision = json.loads(payload['message']['content'])
    if decision['option'] not in [o[0] for o in opts]:
        raise ValueError('Model chose an option that was not offered')
    return decision, {'input': payload.get('prompt_eval_count'), 'output': payload.get('eval_count'),
                      'ms': round((payload.get('total_duration') or 0) / 1e6)}


async def step(token, emit=None, use_model=True, model=None):
    """Run the due role once. Returns the task it issued, or the waiting task if the learner owes a response."""
    model = model or os.getenv('TRELLIS_MODEL', 'qwen2.5:7b')
    def event(kind, **data):
        if emit:
            emit({'type': kind, **data})
    t = _tutor(graph_for(token))
    if t['state'] in WAITING:
        return {'task': status(token)['task'], 'role': None, 'note': 'Waiting for the learner. No role ran.'}
    role = DUE[t['state']]
    env = dict(os.environ, TRELLIS_SESSION=token, TRELLIS_ROLE=role)
    event('role_started', role=role, chooser='model' if use_model else 'policy')
    trace, decisions = [], []
    params = StdioServerParameters(command=sys.executable, args=['-m', 'backend.tutor.mcp_roles'], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            listed = sorted(tool.name for tool in (await client.list_tools()).tools)
            if listed != sorted(ROLE_TOOLS[role]):
                raise ValueError('Role server exposed unexpected tools')
            event('tools_listed', role=role, tools=listed)

            async def call(name, args):
                value = await client.call_tool(name, args)
                text = next(b.text for b in value.content if b.type == 'text')
                if value.is_error:
                    raise ValueError(text)
                result = json.loads(text)
                trace.append({'role': role, 'tool': name, 'arguments': args, 'result_hash': digest(result)})
                event('tool_finished', **trace[-1])
                return result

            read_tool = {'scout': 'scout_route', 'tinker': 'tinker_handoff', 'lens': 'lens_handoff'}[role]
            ctx = await call(read_tool, {})
            inspected = {}
            async with httpx.AsyncClient(timeout=120) as http:
                for _ in range(5):
                    opts = options_for(role, ctx | {'inspected': inspected}, inspected)
                    if not opts:
                        note = {'scout': 'No foundation on this route has an unused lesson right now.',
                                'tinker': 'No permitted lesson representation remains.',
                                'lens': 'No permitted transfer task remains.'}[role]
                        if role != 'scout':
                            pause_if_stuck(token, note + ' Paused rather than repeating a task.')
                        event('role_finished', role=role, outcome='nothing permitted')
                        return {'task': None, 'role': role, 'note': note, 'trace': trace}
                    event('model_started', role=role, options=[{'id': o[0], 'label': o[1]} for o in opts],
                          chooser='model' if use_model else 'policy')
                    rule, rule_why = rule_choice(role, ctx | {'inspected': inspected}, opts)
                    offered = list(opts)
                    if use_model:
                        # Shuffled so a model that always takes the first option cannot look like judgement.
                        random.Random(f'{token}:{role}:{len(decisions)}').shuffle(offered)
                        decision, usage = await decide(http, role, model, ctx | {'inspected': inspected}, offered)
                    else:
                        decision, usage = {'option': rule[0], 'reason': 'Rule-based, no model: ' + rule_why}, None
                    chosen = next(o for o in opts if o[0] == decision['option'])
                    record = {'role': role, 'chooser': 'model' if use_model else 'policy', 'model': model if use_model else None,
                              'options': [{'id': o[0], 'label': o[1]} for o in offered], 'option': chosen[0], 'label': chosen[1],
                              'position_offered': [o[0] for o in offered].index(chosen[0]) + 1,
                              'rule_option': rule[0], 'rule_label': rule[1], 'rule_why': rule_why,
                              'agrees_with_rule': chosen[0] == rule[0],
                              'model_reason_unverified': decision['reason'], 'usage': usage}
                    decisions.append(record)
                    event('model_decision', **record)
                    if chosen[2] == 'tinker_inspect':
                        details = await call('tinker_inspect', {})
                        inspected['history'] = details['history']
                        ctx = await call('tinker_handoff', {})
                        continue
                    if chosen[2] == 'scout_inspect':
                        details = await call('scout_inspect', chosen[3])
                        inspected[details['id']] = {'criteria': details['criteria'][:4], 'status': details['status']}
                        continue
                    task = await call(chosen[2], chosen[3])
                    record_decision(token, {'role': role, 'decisions': decisions, 'trace': trace, 'task': task['task'],
                                            'tools': listed, 'options': OPTIONS if use_model else None})
                    event('role_finished', role=role, outcome=chosen[1], task=task['task'])
                    return {'task': task, 'role': role, 'decisions': decisions, 'trace': trace}
    raise ValueError(f'{role.capitalize()} stopped at its five-decision budget without acting.')
