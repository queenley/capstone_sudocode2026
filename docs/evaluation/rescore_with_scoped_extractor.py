"""Diagnostic: re-extract a closed run's transcripts with the extractor v3, aligned with the agent's own grading instrument and score RQR/CCR with BTC's
reference_eval; the agent run is unchanged, only the instrument is. Not a replacement for evaluate; costs one extractor
call per turn (about 0.0006 USD each).

    python docs/evaluation/rescore_with_scoped_extractor.py scripts/evaluation/runs/<run>
"""
import glob, json, subprocess, sys, os, importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPO=Path(__file__).resolve().parents[2]
E=REPO/'scripts/evaluation'
sys.path.insert(0,str(E))
R=Path(sys.argv[1]).resolve()
spec=importlib.util.spec_from_file_location('ref',E/'evaluation-contracts/sources/btc/eval/reference_eval.py');ref=importlib.util.module_from_spec(spec);spec.loader.exec_module(ref)
cfg=json.load(open(R/'inputs/extractor.json'))['config']
prompt=(E/'extractor-prompt.txt').read_text(encoding='utf-8')
env={**os.environ,'PYTHONUTF8':'1'}
def run(doc):
    inp={k:doc[k] for k in ('agent_text','tool_texts','consultant_texts')}
    payload={'config':cfg,'prompt':prompt+'\n[INPUT DATA]\n'+json.dumps(inp,ensure_ascii=False)}
    r=subprocess.run([str(REPO/'apps/ai-agent-service/.venv/bin/python'),'-B','-m','agent.extract_command'],cwd=E,input=json.dumps(payload,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,env=env,timeout=150)
    o=json.loads(r.stdout.strip().splitlines()[-1])
    return json.loads(o['raw'])['items'],o.get('slots_outside_vocabulary',0)
sc={json.load(open(f))['scenario_id']:json.load(open(f)) for f in glob.glob(str(E/'datasets/create-data-diagnostic-v4/scenarios/*.json'))}; run_ids={json.load(open(p))['context']['scenario_id'] for p in glob.glob(str(R/'evidence/full/transcripts/*.json'))}; sc={k:v for k,v in sc.items() if k in run_ids}
out={}
for config,fn in (('full','full'),('baseline_no_memory','baseline_no_memory')):
    docs=[json.load(open(p)) for p in glob.glob(str(R/f'evidence/{fn}/transcripts/*.json'))]
    with ThreadPoolExecutor(6) as ex: res=list(ex.map(run,docs))
    trace={}
    for d,(items,_) in zip(docs,res):
        c=d['context']
        row={'turn':c['turn'],'agent_text':d['agent_text'],'tool_calls':[{'name':e['request']['name'],'args':e['request'].get('args',{})} for e in d['tools']],
             'questions':[{'slot':i['slot_or_field'],'type':i['question_type'],'text':i['quote']} for i in items if i['kind']=='question' and i['speaker']=='agent'],
             'facts_used':[i['slot_or_field'] for i in items if i['kind']=='fact_usage']}
        trace.setdefault((c['scenario_id'],c['call']),[]).append(row)
    for v in trace.values(): v.sort(key=lambda r:r['turn'])
    out[config]=(ref.repeat_question_rate(sc,trace),ref.context_carryover_rate(sc,trace),sum(n for _,n in res))
for config,(rq,cc,n) in out.items():
    print(config,'RQR',rq['value'],f"{rq['redundant']}/{rq['total_questions']}",'| CCR',cc['value'],f"{cc['used']}/{cc['required']}",'| outside-vocab fixes',n)
    if config=='full':
        for e in rq['examples']: print('   ',e['scenario'][-4:],e['call'],e['turn'],e['type'],e['slot'],'|',(e['text'] or '')[:70])
