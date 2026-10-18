"""Fraction task engine. Exact rational arithmetic, finite enumerated parameter pools, answers kept on the server.

Every task is a parameter dict. `public()` turns it into what the browser may see (the picture and the question,
never the answer). `grade()` checks a structured response with `fractions.Fraction`. `solution()` and `hints()` are
server-side; a solution is only ever shown for a worked example, which is then retired from the check pool.
Rubric fractions-v1. Prototype content: answer logic is tested, the teaching design is not educator-reviewed.
"""
import hashlib
import json
import random
from fractions import Fraction as F
from itertools import permutations
from math import gcd

RUBRIC = 'fractions-v1'
NAMES = {2: 'halves', 3: 'thirds', 4: 'quarters', 5: 'fifths', 6: 'sixths', 8: 'eighths'}
ORDERS = list(permutations(range(3)))

# Unequal splits with the right number of parts. Each list sums to one whole (checked by tests).
UNEQUAL = {
    2: [['1/3', '2/3'], ['2/5', '3/5'], ['3/8', '5/8']],
    3: [['1/4', '1/4', '1/2'], ['1/6', '1/3', '1/2'], ['1/5', '2/5', '2/5']],
    4: [['1/8', '1/8', '1/4', '1/2'], ['1/6', '1/6', '1/3', '1/3'], ['1/5', '1/5', '1/5', '2/5']],
    6: [['1/12', '1/12', '1/6', '1/6', '1/4', '1/4'], ['1/8', '1/8', '1/8', '1/8', '1/4', '1/4'],
        ['1/10', '1/10', '1/10', '1/10', '3/10', '3/10']],
}
# Grid shares: one character per cell, rows separated by '/'. Same character = same share.
# 'equal' has n shares of equal area (often different-looking), 'unequal' has n shares of different areas,
# 'wrong' has equal shares but the wrong number of them. All three are checked independently by tests.
GRIDS = {
    2: {'equal': ['0001/0111', '0100/0111', '0011/0011'], 'unequal': ['0001/0011', '0000/0011', '0111/0111'],
        'wrong': ['0011/2233', '0123/0123']},
    3: {'equal': ['001/221', '012/012'], 'unequal': ['001/211', '000/122'], 'wrong': ['000/111', '012/345']},
    4: {'equal': ['0011/2233', '0123/0123', '0012/3312'], 'unequal': ['0012/0332', '0001/2233'],
        'wrong': ['0001/0111', '0011/0011']},
    6: {'equal': ['0011/2345/2345', '0123/0123/4455'], 'unequal': ['0012/3345/3345', '0011/2234/5555'],
        'wrong': ['0001/1122/2333', '0000/1111/2222']},
}

FAMILIES = {
    'equal_parts': {'objective': 'equal-parts-v1', 'reps': {'bar': 'fraction strips', 'circle': 'pie pieces',
                                                            'grid': 'grid shares that can look different'}},
    'build': {'objective': 'build-fraction-v1', 'reps': {'bar': 'a fraction strip', 'circle': 'a pie',
                                                         'set': 'a group of counters'}},
    'number_line': {'objective': 'number-line-v1', 'reps': {'ticks': 'a number line marked in the same parts',
                                                            'fine': 'a number line with finer marks',
                                                            'read': 'reading a marked point'}},
}


class Exhausted(ValueError):
    """No unused task remains in a pool. Reported to the learner, never papered over with a repeat."""


def gaps(n):
    return f'{n} gap' if n == 1 else f'{n} gaps'


def fs(x):
    return f'{x.numerator}/{x.denominator}'


def label(family, rep):
    return FAMILIES[family]['reps'][rep]


def key(params):
    """Stable identity of a task. Two tasks with the same parameters are the same task."""
    text = json.dumps(params, sort_keys=True)
    return params['family'] + ':' + params['rep'] + ':' + hashlib.sha1(text.encode()).hexdigest()[:12]


# ---------- pools ----------

def pool(family, rep, allowed):
    """Every task this activity can produce for one representation, in a fixed order. Finite by construction."""
    out = []
    if family == 'equal_parts':
        for n in allowed['n']:
            if rep == 'grid':
                g = GRIDS[n]
                for e in range(len(g['equal'])):
                    for u in range(len(g['unequal'])):
                        for w in range(len(g['wrong'])):
                            for o in range(len(ORDERS)):
                                out.append({'family': family, 'rep': rep, 'n': n, 'e': e, 'u': u, 'w': w, 'order': o})
            else:
                for u in range(len(UNEQUAL[n])):
                    for w in [m for m in (n - 1, n + 1) if m >= 2]:
                        for o in range(len(ORDERS)):
                            out.append({'family': family, 'rep': rep, 'n': n, 'u': u, 'w': w, 'order': o})
    elif family == 'build':
        for b in allowed['b']:
            for a in range(1, b):
                if gcd(a, b) != 1:
                    continue
                ks = [k for k in (2, 3, 4) if b * k <= 16] if rep == 'set' else [1, 2]
                for k in ks:
                    out.append({'family': family, 'rep': rep, 'a': a, 'b': b, 'k': k})
    elif family == 'number_line':
        for span in allowed.get('span', [1]):
            for b in allowed['b']:
                if rep == 'read':
                    if span != 1:
                        continue
                    for i in range(1, b):
                        for o in range(len(ORDERS)):
                            if len(_read_options({'i': i, 't': b})) == 3:
                                out.append({'family': family, 'rep': rep, 'i': i, 't': b, 'order': o})
                    continue
                t = b if rep == 'ticks' else 2 * b
                for a in range(1, b * span):
                    if a % b and gcd(a, b) == 1:
                        out.append({'family': family, 'rep': rep, 'a': a, 'b': b, 't': t, 'span': span})
    else:
        raise ValueError('Unknown task family')
    return out


READ_CODES = {'marks': 'counted_marks', 'extra': 'off_by_one', 'from_right': 'from_right'}


def reveals(p):
    """The mistakes this item's wrong answers can expose. A distinguishing check prefers items that split open ones."""
    if p['family'] == 'equal_parts':
        return {'unequal_parts', 'wrong_count'}
    if p['family'] == 'build':
        return {'shade_count'}
    if p['rep'] == 'read':
        return {READ_CODES[k] for k, _ in _read_options(p) if k in READ_CODES}
    return {'placement'}


def pick(family, rep, allowed, used, seed, want=None):
    """First unused task in this learner's own shuffled order. Raises Exhausted instead of repeating.
    With `want`, items whose wrong answers expose more of those mistakes come first."""
    tasks = pool(family, rep, allowed)
    random.Random(seed).shuffle(tasks)
    if want:
        tasks.sort(key=lambda t: -len(reveals(t) & set(want)))
    for t in tasks:
        if key(t) not in used:
            return t
    raise Exhausted(f'Every {label(family, rep)} task for this activity has been used in this notebook. '
                    'No task is repeated, so this check cannot run again here.')


def remaining(family, rep, allowed, used):
    return sum(key(t) not in used for t in pool(family, rep, allowed))


# ---------- what the browser sees ----------

def _picture_options(p):
    n = p['n']
    if p['rep'] == 'grid':
        g = GRIDS[n]
        shapes = [('equal', g['equal'][p['e']]), ('unequal', g['unequal'][p['u']]), ('count', g['wrong'][p['w']])]
        drawn = [{'shape': 'grid', 'cells': c} for _, c in shapes]
    else:
        shapes = [('equal', [fs(F(1, n))] * n), ('unequal', UNEQUAL[n][p['u']]), ('count', [fs(F(1, p['w']))] * p['w'])]
        drawn = [{'shape': p['rep'], 'parts': parts} for _, parts in shapes]
    order = ORDERS[p['order']]
    return [shapes[i][0] for i in order], [drawn[i] for i in order]


def _read_options(p):
    i, t = p['i'], p['t']
    right = F(i, t)
    # Distractors are the common miscounts: counting marks instead of gaps, one gap too many, counting from 1.
    candidates = [('right', f'{i}/{t}'), ('marks', f'{i}/{t + 1}'), ('extra', f'{i + 1}/{t}'), ('from_right', f'{t - i}/{t}')]
    out, values = [], set()
    for kind, text in candidates:
        num, den = map(int, text.split('/'))
        if num <= 0 or den <= 0:
            continue
        v = F(num, den)
        if (v in values) or (kind != 'right' and v == right):
            continue
        values.add(v)
        out.append((kind, text))
        if len(out) == 3:
            break
    return out


def public(p):
    """Render spec and question. No answer, correctness flag or solution is ever included."""
    f, rep = p['family'], p['rep']
    if f == 'equal_parts':
        _, drawn = _picture_options(p)
        q = f'Which grid is split into {NAMES[p["n"]]}?' if rep == 'grid' else \
            f'Which {"strip" if rep == "bar" else "circle"} is cut into {NAMES[p["n"]]}?'
        return {'type': 'choose_picture', 'prompt': q, 'options': drawn}
    if f == 'build':
        parts = p['b'] * p['k']
        whole = {'bar': 'the strip', 'circle': 'the circle', 'set': f'these {parts} counters'}[rep]
        return {'type': 'shade', 'shape': rep, 'parts': parts,
                'prompt': f'Shade {p["a"]}/{p["b"]} of {whole}.', 'target': f'{p["a"]}/{p["b"]}'}
    if f == 'number_line':
        if rep == 'read':
            order = ORDERS[p['order']]
            opts = _read_options(p)
            return {'type': 'read_line', 'span': 1, 'ticks_per_unit': p['t'], 'point': p['i'],
                    'prompt': 'What fraction is marked on the number line?', 'options': [opts[i][1] for i in order]}
        return {'type': 'place', 'span': p['span'], 'ticks_per_unit': p['t'], 'target': f'{p["a"]}/{p["b"]}',
                'prompt': f'Put {p["a"]}/{p["b"]} on the number line.'}
    raise ValueError('Unknown task family')


# ---------- server-side answers ----------

def solution(p):
    f = p['family']
    if f == 'equal_parts':
        kinds, _ = _picture_options(p)
        return {'choice': kinds.index('equal')}
    if f == 'build':
        return {'shaded': list(range(p['a'] * p['k']))}
    if p['rep'] == 'read':
        order = ORDERS[p['order']]
        kinds = [_read_options(p)[i][0] for i in order]
        return {'choice': kinds.index('right')}
    return {'tick': p['a'] * p['t'] // p['b']}


def _choice(response, count):
    c = response.get('choice') if isinstance(response, dict) else None
    if type(c) is not int or not 0 <= c < count:
        raise ValueError('Invalid response for this task')
    return c


def grade(p, response):
    """Assay. Checks the structured response exactly. Returns correctness, the value given and a plain explanation."""
    f, rep = p['family'], p['rep']
    if f == 'equal_parts':
        kinds, _ = _picture_options(p)
        kind = kinds[_choice(response, 3)]
        n, name = p['n'], NAMES[p['n']]
        if kind == 'equal':
            extra = ' The shares look different, but each covers the same number of squares.' if rep == 'grid' else ''
            return {'correct': True, 'value': 'equal parts', 'difficulty': None,
                    'explanation': f'Yes. That whole is cut into {n} parts of exactly the same size, so they are {name}.{extra}'}
        if kind == 'unequal':
            return {'correct': False, 'value': 'unequal parts', 'difficulty': 'unequal_parts',
                    'explanation': f'That picture has {n} parts, but they are not all the same size, so they are not {name}.'}
        count = len(set(GRIDS[n]['wrong'][p['w']].replace('/', ''))) if rep == 'grid' else p['w']
        return {'correct': False, 'value': 'wrong number of parts', 'difficulty': 'wrong_count',
                'explanation': f'Those parts are equal, but there are {count} of them. {name.capitalize()} means {n} equal parts.'}
    if f == 'build':
        parts = p['b'] * p['k']
        shaded = response.get('shaded') if isinstance(response, dict) else None
        if not isinstance(shaded, list) or any(type(i) is not int or not 0 <= i < parts for i in shaded) \
                or len(set(shaded)) != len(shaded):
            raise ValueError('Invalid response for this task')
        got, want = F(len(shaded), parts), F(p['a'], p['b'])
        need = p['a'] * p['k']
        if got == want:
            same = f', the same amount as {fs(want)}' if p['k'] > 1 else ''
            return {'correct': True, 'value': f'{len(shaded)}/{parts}', 'difficulty': None,
                    'explanation': f'Yes. {len(shaded)} of the {parts} equal parts is {len(shaded)}/{parts}{same}.'}
        return {'correct': False, 'value': f'{len(shaded)}/{parts}', 'difficulty': 'shade_count',
                'explanation': f'You shaded {len(shaded)} of {parts} equal parts. {fs(want)} of this whole needs {need} of them.'}
    if rep == 'read':
        order = ORDERS[p['order']]
        opts = [_read_options(p)[i] for i in order]
        kind, text = opts[_choice(response, 3)]
        t, i = p['t'], p['i']
        if kind == 'right':
            return {'correct': True, 'value': text, 'difficulty': None,
                    'explanation': f'Yes. From 0 to 1 there are {t} equal gaps, and the point is {gaps(i)} from 0.'}
        why = {'marks': f'That counts the marks. Count the gaps instead: there are {t} equal gaps from 0 to 1.',
               'extra': f'That is one gap too many. The point is {gaps(i)} from 0.',
               'from_right': f'That counts from 1 back towards 0. Count the gaps from 0: the point is {gaps(i)} along.'}[kind]
        return {'correct': False, 'value': text, 'difficulty': {'marks': 'counted_marks', 'extra': 'off_by_one',
                                                                 'from_right': 'from_right'}[kind], 'explanation': why}
    tick = response.get('tick') if isinstance(response, dict) else None
    if type(tick) is not int or not 0 <= tick <= p['t'] * p['span']:
        raise ValueError('Invalid response for this task')
    got, want = F(tick, p['t']), F(p['a'], p['b'])
    if got == want:
        same = f', which is the same point as {fs(want)}' if p['t'] != p['b'] else ''
        return {'correct': True, 'value': fs(got), 'difficulty': None,
                'explanation': f'Yes. That point is {gaps(tick)} of 1/{p["t"]} from 0{same}.'}
    return {'correct': False, 'value': f'{tick}/{p["t"]}' if tick else '0', 'difficulty': 'placement',
            'explanation': f'That point is {gaps(tick)} of 1/{p["t"]} from 0, which is {fs(got) if tick else "0"}. '
                           f'{fs(want)} is {gaps(p["a"] * p["t"] // p["b"])} along.'}


# ---------- teaching material (finite, reviewed ladder) ----------

def hints(p):
    f, rep = p['family'], p['rep']
    if f == 'equal_parts':
        n, name = p['n'], NAMES[p['n']]
        second = ('Count the small squares in each share. Equal shares cover the same number of squares, '
                  'even when their shapes differ.') if rep == 'grid' else \
            'Compare the biggest part with the smallest part. Equal parts are all exactly the same size.'
        return ['Look at the size of each part, not only how many parts there are.',
                f'{name.capitalize()} means {n} parts that are all the same size. Check both things. ' + second]
    if f == 'build':
        a, b, k = p['a'], p['b'], p['k']
        out = ['First count how many equal parts the whole has.',
               f'In {a}/{b}, the bottom number says the whole is cut into {b} equal parts. The top number says how many of those to shade.']
        if k > 1:
            out.append(f'Here the whole has {b * k} small parts, so each 1/{b} is {k} of them.')
        return out
    if rep == 'read':
        return ['Count the gaps between 0 and 1, not the marks.',
                'The number of gaps from 0 to 1 goes on the bottom. The gaps from 0 to the point go on top.']
    out = ['Count the gaps between 0 and 1, not the marks.', f'Each gap from 0 to 1 is 1/{p["t"]}.']
    if p['t'] != p['b']:
        out.append(f'1/{p["b"]} is {p["t"] // p["b"]} of these gaps.')
    return out


def example(p):
    """A worked example: the task, its solution and the reasoning steps. Only used for items retired from checks."""
    f = p['family']
    if f == 'equal_parts':
        steps = [f'Each picture is checked for two things: {p["n"]} parts, and all parts the same size.',
                 'Only one picture passes both checks.']
    elif f == 'build':
        steps = [f'The whole has {p["b"] * p["k"]} equal parts.',
                 f'{p["a"]}/{p["b"]} means {p["a"]} out of every {p["b"]} equal parts, so shade {p["a"] * p["k"]}.']
    elif p['rep'] == 'read':
        steps = [f'There are {p["t"]} equal gaps from 0 to 1, so each gap is 1/{p["t"]}.',
                 f'The point is {gaps(p["i"])} from 0, so it shows {p["i"]}/{p["t"]}.']
    else:
        steps = [f'There are {p["t"]} equal gaps from 0 to 1, so each gap is 1/{p["t"]}.',
                 f'{p["a"]}/{p["b"]} is {gaps(p["a"] * p["t"] // p["b"])} from 0.']
    return {'render': public(p), 'solution': solution(p), 'steps': steps}
