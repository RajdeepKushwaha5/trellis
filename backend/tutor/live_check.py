"""One real model-driven loop: Scout, then Tinker after a wrong check, then Lens. Writes evidence/tutor-live-loop.json.

The learner's responses are scripted (wrong check, correct practice) so the run exercises the teaching branch; the
roles' choices come from the local model. Run: python -m backend.tutor.live_check
"""
import asyncio
import json
import time

from ..core import ROOT, create_session, graph_for
from ..investigation import set_goal
from . import fractions as engine
from . import session as tutor
from .runner import step

GOAL = 'mt_NoB20kVa4w'


def respond(token, tid, correct):
    p = tutor._task_row(graph_for(token), tid)['params']
    sol = engine.solution(p)
    if not correct:
        sol = {'choice': (sol['choice'] + 1) % 3} if 'choice' in sol else {'shaded': []} if 'shaded' in sol else \
            {'tick': (sol['tick'] + 1) % (p['t'] * p['span'] + 1)}
    return tutor.answer(token, tid, sol)


async def main():
    token = create_session()['token']
    set_goal(token, GOAL)
    record = {'goal': GOAL, 'synthetic': True, 'scripted_responses': ['wrong check', 'correct practice', 'transfer as answered'],
              'steps': []}
    try:
        for role, correct in [('scout', False), ('tinker', True), ('lens', True)]:
            events, start = [], time.perf_counter()
            result = await step(token, events.append, use_model=True)
            assert result['role'] == role, (role, result.get('role'), result.get('note'))
            decision = result['decisions'][-1]
            outcome = respond(token, result['task']['task'], correct)
            record['steps'].append({'role': role, 'seconds': round(time.perf_counter() - start, 1),
                                    'tools': next(e['tools'] for e in events if e['type'] == 'tools_listed'),
                                    'decisions': result['decisions'], 'task_purpose': result['task']['purpose'],
                                    'representation': result['task']['representation'],
                                    'response_correct': outcome['correct'], 'next_state': outcome['next_state']})
            print(f"{role}: chose option {decision['rank_in_options']} of {len(decision['options'])} "
                  f"({decision['label']}) in {record['steps'][-1]['seconds']} s -> {outcome['next_state']}")
        record['final'] = tutor.status(token)['history']
        (ROOT / 'evidence/tutor-live-loop.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    finally:
        graph_for(token).delete()


if __name__ == '__main__':
    asyncio.run(main())
