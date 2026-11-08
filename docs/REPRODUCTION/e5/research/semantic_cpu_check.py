"""Validate the exported encoder in the exact packaged CPU runtime.

Dev calibration freezes the final asset hashes before the one-shot holdout mode.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import sys
import time

WORK=Path(__file__).resolve().parent;STAGE=WORK/'site';OUT=WORK/'semantic'
sys.dont_write_bytecode=True;sys.path.insert(0,str(STAGE));sys.path.insert(0,str(WORK))
from semantic_gpu_trial import metric,rank,SETTINGS
from jeju_agent.assistant_search import search_assistant
from jeju_agent.semantic_search import _dependencies,search_semantic,semantic_query_supported

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['dev','holdout']);args=parser.parse_args()
    selected=read(OUT/'selection_frozen.json');rows=read(WORK/'evaluation/source_partitions.json')['rows']
    assets=STAGE/'models_semantic';assets.mkdir(exist_ok=True)
    if args.mode=='dev':
        assert not (OUT/'cpu_selection_frozen.json').exists(),'CPU calibration is already frozen'
        for name in ['encoder.int8.onnx','tokenizer.json']:
            if (assets/name).exists():assert sha(assets/name)==sha(OUT/'export'/name)
            else:shutil.copyfile(OUT/'export'/name,assets/name)
        numpy,tokenizers,ort=_dependencies(STAGE)
        tokenizer=tokenizers.Tokenizer.from_file(str(assets/'tokenizer.json'))
        tokenizer.enable_truncation(max_length=SETTINGS['max_length']);tokenizer.enable_padding(pad_id=1,pad_token='<pad>')
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        start=time.perf_counter();session=ort.InferenceSession(str(assets/'encoder.int8.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        load_ms=(time.perf_counter()-start)*1000
        def encode(texts,batch_size=4):
            vectors=[]
            for i in range(0,len(texts),batch_size):
                batch=tokenizer.encode_batch(texts[i:i+batch_size])
                feeds={'input_ids':numpy.asarray([t.ids for t in batch],dtype=numpy.int64),
                       'attention_mask':numpy.asarray([t.attention_mask for t in batch],dtype=numpy.int64)}
                vectors.extend(session.run(None,feeds)[0].tolist())
            data=numpy.asarray(vectors);return data/numpy.linalg.norm(data,axis=1,keepdims=True)
        docs=encode(['passage: '+r['name']+'. '+r['summary'] for r in rows])
        cases=read(WORK/'evaluation/dev_queries.json')['cases']
        # Dynamic activation quantization depends on batch contents. Match the
        # serving contract exactly: one query at a time, with the fixed index.
        queries=encode(['query: '+c['query'] for c in cases],batch_size=1);scores=queries@docs.T
        grid=[]
        for threshold in SETTINGS['thresholds']:
            ids=rank(cases,rows,scores,threshold);grid.append({'threshold':threshold,'metrics':metric(cases,ids),'ranked_ids':ids})
        good=[r for r in grid if r['metrics']['unsupported_false_responses']==0]
        best=max(good,key=lambda r:(r['metrics']['hit_at_3'],r['metrics']['mrr_at_3'],r['metrics']['hit_at_1'],r['threshold']))
        items=[{'id':r['id'],'name':r['name'],'summary_sha256':hashlib.sha256(r['summary'].strip().encode()).hexdigest(),
                'source_url':r['source_url'],'retrieved_at':r['retrieved_at'],'vector':v.tolist()} for r,v in zip(rows,docs)]
        corpus={'schema_version':1,'model_id':selected['model_id'],'embedding_dimension':selected['dimension'],'items':items}
        save(assets/'corpus.json',corpus)
        config={'schema_version':1,'enabled':True,'model_id':selected['model_id'],'revision':selected['revision'],
                'candidate':selected['candidate'],'embedding_dimension':selected['dimension'],'max_length':SETTINGS['max_length'],
                'query_prefix':'query: ','document_prefix':'passage: ','score_threshold':best['threshold'],
                'model_sha256':sha(assets/'encoder.int8.onnx'),'tokenizer_sha256':sha(assets/'tokenizer.json'),
                'corpus_sha256':sha(assets/'corpus.json'),'training_source_pairs':40 if 'source40' in selected['candidate'] else 0,
                'runtime':'onnxruntime_cpu_int8','does_not_generate_text':True}
        save(assets/'config.json',config)
        actual=[[r['id'] for r in search_semantic(STAGE,c['query'])] for c in cases]
        if actual!=best['ranked_ids']:
            save(OUT/'cpu_calibration_debug.json',{'actual':actual,'expected':best['ranked_ids'],'threshold':best['threshold']})
            raise AssertionError('Actual runtime and calibration ranking differ')
        baseline=[[r['id'] for r in search_assistant(STAGE,c['query'],include_route_restricted=True)] for c in cases]
        report={'pass':True,'cpu_threads':2,'model_load_ms':load_ms,'grid':grid,'best':best,
                'baseline':metric(cases,baseline),'actual_runtime_matches_calibration':True,
                'onnxruntime_version':ort.__version__,'numpy_version':numpy.__version__,
                'python_version':sys.version,'cpu_only_providers':session.get_providers()}
        save(OUT/'cpu_dev_results.json',report)
        freeze={'config_sha256':sha(assets/'config.json'),'model_sha256':config['model_sha256'],
                'semantic_backend_sha256':sha(STAGE/'jeju_agent/semantic_search.py'),
                'corpus_sha256':config['corpus_sha256'],'tokenizer_sha256':config['tokenizer_sha256'],
                'evaluation_protocol_sha256':sha(WORK/'evaluation/protocol.json'),
                'source_partitions_sha256':sha(WORK/'evaluation/source_partitions.json'),
                'dev_queries_sha256':sha(WORK/'evaluation/dev_queries.json'),'gpu_selection_sha256':sha(OUT/'selection_frozen.json'),
                'candidate':selected['candidate'],'score_threshold':best['threshold'],'holdout_opened':False}
        save(OUT/'cpu_selection_frozen.json',freeze)
        print(json.dumps({'cpu_dev':best['metrics'],'baseline':report['baseline'],'threshold':best['threshold']},ensure_ascii=True));return
    assert not (OUT/'holdout_results.json').exists(),'Do not reopen/tune against the frozen holdout'
    freeze=read(OUT/'cpu_selection_frozen.json')
    for name,key in [('config.json','config_sha256'),('encoder.int8.onnx','model_sha256'),('corpus.json','corpus_sha256'),('tokenizer.json','tokenizer_sha256')]:
        assert sha(assets/name)==freeze[key],name
    assert sha(WORK/'evaluation/protocol.json')==freeze['evaluation_protocol_sha256']
    assert sha(STAGE/'jeju_agent/semantic_search.py')==freeze['semantic_backend_sha256']
    cases=read(WORK/'evaluation/holdout_queries.json')['cases'];semantic=[];baseline=[];records=[];times=[]
    for case in cases:
        start=time.perf_counter();result=search_semantic(STAGE,case['query']);elapsed=(time.perf_counter()-start)*1000
        actual=[r['id'] for r in result];semantic.append(actual);times.append(elapsed)
        old=[r['id'] for r in search_assistant(STAGE,case['query'],include_route_restricted=True)];baseline.append(old)
        records.append({'id':case['id'],'query':case['query'],'kind':case['kind'],'relevant_ids':case['relevant_ids'],
                        'scope_guard_allows_query':semantic_query_supported(case['query']),
                        'semantic_ids':actual,'baseline_ids':old,'semantic_ms':elapsed,
                        'returned_sources':[{k:r.get(k) for k in ['id','name','official_intro','automatic_eligible','visit_restrictions']} for r in result]})
    new=metric(cases,semantic);old=metric(cases,baseline)
    gate=(new['unsupported_false_responses']==0 and new['hit_at_3']-old['hit_at_3']>=.1-1e-12 and new['mrr_at_3']>=old['mrr_at_3'])
    report={'experiment_completed':True,'adoption_metric_gate_pass':gate,'baseline':old,'semantic':new,
            'candidate':freeze['candidate'],'cpu_config_sha256':freeze['config_sha256'],
            'holdout_queries_sha256':sha(WORK/'evaluation/holdout_queries.json'),
            'cases':records,'cpu_threads':2,'latency_first_call_ms':times[0],
            'scope':'Developer-authored held-out source questions; not real-user accuracy or center field latency.',
            'real_device_gps_used':False,'generated_text':False}
    save(OUT/'holdout_results.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=True))

if __name__=='__main__':main()
