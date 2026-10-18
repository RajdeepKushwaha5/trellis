"""Owned synthetic browser-check fixtures. Never used by the application."""
import json,sys
from ..core import graph_for
from .fixtures import seed
from . import session as t

if sys.argv[1]=='create':
    sessions={}
    try:
        for mode in ['probe','strategy']:
            # An ambiguous placement needs a distinguishing check; a specific mistake can be taught directly.
            case={'probe':{'rep':'ticks','difficulty':'placement'},'strategy':{'rep':'read','difficulty':'counted_marks'}}[mode]
            token,ctx=seed({'id':'browser-'+mode,'activity':'line-first'}|case)
            sessions[mode]=token
            if mode=='probe':
                t.tinker_probe(token,'read-unit',ctx['version'])
            else:
                s=next(s for s in ctx['teaching_strategies'] if s['id']=='walk-gaps')
                rep=next(r['id'] for r in ctx['representations'] if r['id'] in s['reps'])
                t.tinker_teach(token,rep,'example_first',ctx['version'],s['id'])
        print(json.dumps(sessions))
    except BaseException:
        for token in sessions.values():graph_for(token).delete()
        raise
elif sys.argv[1]=='create-recovery':
    from .fixtures import recovery_episode
    sessions={}
    try:
        sessions['required'],_=seed({'id':'browser-required','activity':'line-first','rep':'ticks','difficulty':'placement'})
        sessions['recovery']=recovery_episode()
        print(json.dumps(sessions))
    except BaseException:
        for token in sessions.values():graph_for(token).delete()
        raise
elif sys.argv[1]=='delete':
    for token in json.loads(sys.argv[2]).values():graph_for(token).delete()
