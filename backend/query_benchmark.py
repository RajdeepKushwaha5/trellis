"""Local read-query timing, separate server execution from client wall time."""
import json
import statistics
import time
from .core import db,BASE,ROOT
from .reasoning import ALL_CLOSURES

def main():
    graph=db().select_graph(BASE);samples=[]
    for i in range(8):
        start=time.perf_counter();r=graph.ro_query(ALL_CLOSURES,timeout=5000)
        samples.append({'server_ms':r.run_time_ms,'wall_ms':round((time.perf_counter()-start)*1000,3)})
    warm=samples[1:]
    report={'query':ALL_CLOSURES,'goals':len(r.result_set),'largest_closure_including_goal':max(len(v[1]) for v in r.result_set),
            'samples':samples,'warm_median_server_ms':statistics.median(s['server_ms'] for s in warm),
            'warm_median_wall_ms':statistics.median(s['wall_ms'] for s in warm),
            'scope':'Local read-only bulk closure query, 1 warmup and 7 measured warm runs. Not end-to-end agent latency or learning effectiveness.'}
    (ROOT/'artifacts').mkdir(exist_ok=True);(ROOT/'artifacts/native-query-benchmark.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
