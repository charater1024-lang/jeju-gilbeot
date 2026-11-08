"""Independent read-only audit; never reruns or selects against holdout."""
import hashlib
import json
import math
from pathlib import Path

WORK=Path(__file__).resolve().parents[1]
STAGE=WORK/'site';OUT=WORK/'validation'
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
parts=read(WORK/'evaluation/source_partitions.json')
rows=parts['rows'];by_id={r['id']:r for r in rows}
protocol=read(WORK/'evaluation/protocol.json')
receipt=read(WORK/'evaluation/freeze_receipt.json')
for name,digest in receipt['files_sha256'].items():assert sha(WORK/'evaluation'/name)==digest,name
settings=read(WORK/'semantic/settings_frozen.json')
gpu=read(WORK/'semantic/gpu_dev_results.json')
gpu_select=read(WORK/'semantic/selection_frozen.json')
cpu=read(WORK/'semantic/cpu_dev_results.json')
freeze=read(WORK/'semantic/cpu_selection_frozen.json')
held=read(WORK/'semantic/holdout_results.json')
assert settings['holdout_opened'] is False and freeze['holdout_opened'] is False
assert settings['source_partitions_sha256']==sha(WORK/'evaluation/source_partitions.json')
assert settings['dev_sha256']==sha(WORK/'evaluation/dev_queries.json')
assert settings['evaluation_protocol_sha256']==sha(WORK/'evaluation/protocol.json')
assert set(settings['candidates'])=={'small_pretrained','small_source40','base_pretrained','base_source40'}
assert len(gpu['candidates'])==4 and {r['candidate'] for r in gpu['candidates']}==set(settings['candidates'])
train={r['id'] for r in rows if r['partition']=='train'}
other={r['id'] for r in rows if r['partition']!='train'}
assert len(train)==40 and train.isdisjoint(other)
records=[]
for record in gpu['candidates']:
    assert record['gpu_device']=='NVIDIA GeForce RTX 4090 Laptop GPU'
    assert record['best']['metrics']['unsupported_false_responses']==0
    assert [x['threshold'] for x in record['threshold_grid']]==settings['thresholds']
    if record['candidate'].endswith('source40'):
        assert record['training_pairs']==40 and record['training_steps']==30
        assert record['training_seconds']>0 and math.isfinite(record['gradient_norm_final'])
        assert record['gradient_norm_final']>0
    else:assert record['training_pairs']==record['training_steps']==0
    allowed=[r for r in record['threshold_grid'] if r['metrics']['unsupported_false_responses']==0]
    best=max(allowed,key=lambda r:(r['metrics']['hit_at_3'],r['metrics']['mrr_at_3'],r['metrics']['hit_at_1'],r['threshold']))
    assert best==record['best'],record['candidate']
    records.append({k:record[k] for k in ['candidate','parameters','dimension','gpu_device','torch_version',
        'cuda_version','training_pairs','training_steps','training_seconds','gradient_norm_final','peak_vram_bytes','best']})
chosen=max(gpu['candidates'],key=lambda r:(r['best']['metrics']['hit_at_3'],r['best']['metrics']['mrr_at_3'],
    r['best']['metrics']['hit_at_1'],r['best']['threshold'],-r['parameters']))
assert chosen['candidate']==gpu_select['candidate']==freeze['candidate']=='small_pretrained'
assert sha(WORK/'semantic'/(chosen['candidate']+'_dev.json'))==gpu_select['candidate_record_sha256']
assert sha(WORK/'semantic/settings_frozen.json')==gpu_select['settings_sha256']
assert sha(WORK/'semantic/selection_frozen.json')==freeze['gpu_selection_sha256']
assets=STAGE/'models_semantic'
for name,key in [('config.json','config_sha256'),('encoder.int8.onnx','model_sha256'),
                 ('tokenizer.json','tokenizer_sha256'),('corpus.json','corpus_sha256')]:
    assert sha(assets/name)==freeze[key],name
assert sha(STAGE/'jeju_agent/semantic_search.py')==freeze['semantic_backend_sha256']
assert sha(WORK/'evaluation/protocol.json')==freeze['evaluation_protocol_sha256']
assert sha(WORK/'evaluation/dev_queries.json')==freeze['dev_queries_sha256']
assert sha(WORK/'evaluation/source_partitions.json')==freeze['source_partitions_sha256']
allowed=[r for r in cpu['grid'] if r['metrics']['unsupported_false_responses']==0]
cpu_best=max(allowed,key=lambda r:(r['metrics']['hit_at_3'],r['metrics']['mrr_at_3'],r['metrics']['hit_at_1'],r['threshold']))
assert cpu_best==cpu['best'] and cpu_best['threshold']==freeze['score_threshold']==0.86
assert cpu['actual_runtime_matches_calibration'] is True and cpu['cpu_only_providers']==['CPUExecutionProvider']
config=read(assets/'config.json')
assert config['candidate']=='small_pretrained' and config['training_source_pairs']==0
assert config['does_not_generate_text'] is True
assert held['candidate']==freeze['candidate'] and held['cpu_config_sha256']==freeze['config_sha256']
assert held['holdout_queries_sha256']==sha(WORK/'evaluation/holdout_queries.json')
cases=read(WORK/'evaluation/holdout_queries.json')['cases'];cases_by_id={c['id']:c for c in cases}
assert len(held['cases'])==len(cases)==36

def metric(key):
    one=three=0;rr=0.;false=0;positive=0
    for row in held['cases']:
        if row['kind']=='unsupported':false+=bool(row[key]);continue
        positive+=1;positions=[i+1 for i,x in enumerate(row[key][:3]) if x in row['relevant_ids']]
        one+=bool(row[key] and row[key][0] in row['relevant_ids']);three+=bool(positions)
        rr+=1/min(positions) if positions else 0.
    return {'supported':positive,'hit_at_1':one/positive,'hit_at_3':three/positive,
            'mrr_at_3':rr/positive,'unsupported_false_responses':false}

for key,name in [('semantic_ids','semantic'),('baseline_ids','baseline')]:
    actual=metric(key)
    assert actual==held[name],(name,actual,held[name])
for row in held['cases']:
    case=cases_by_id[row['id']]
    assert all(row[k]==case[k] for k in ['query','kind','relevant_ids'])
    for result in row['returned_sources']:
        source=by_id[result['id']]
        assert result['name']==source['name']
        assert result['official_intro']['text']==source['summary'].strip()
        assert result['official_intro']['source_url']==source['source_url']
        assert result['official_intro']['retrieved_at']==source['retrieved_at']
        assert result['automatic_eligible']==source['automatic_eligible']
neg=[r for r in held['cases'] if r['kind']=='unsupported']
guarded=[r['id'] for r in neg if not r['scope_guard_allows_query']]
score_rejected=[r['id'] for r in neg if r['scope_guard_allows_query'] and not r['semantic_ids']]
assert len(guarded)+len(score_rejected)==12
supported=[r for r in held['cases'] if r['kind']=='supported']
misses=[r['id'] for r in supported if not any(i in r['relevant_ids'] for i in r['semantic_ids'][:3])]
tail_extras=[{'id':r['id'],'unlabelled_tail_ids':[i for i in r['semantic_ids'][1:] if i not in r['relevant_ids']]}
             for r in supported if any(i not in r['relevant_ids'] for i in r['semantic_ids'][1:])]
strict_returned=sum(len(r['semantic_ids']) for r in supported)
strict_relevant=sum(sum(i in r['relevant_ids'] for i in r['semantic_ids']) for r in supported)
gate=(held['semantic']['unsupported_false_responses']==0 and
      held['semantic']['hit_at_3']-held['baseline']['hit_at_3']>=.10-1e-12 and
      held['semantic']['mrr_at_3']>=held['baseline']['mrr_at_3'])
assert gate==held['adoption_metric_gate_pass'] is True
report={'pass':True,'scope':'Independent audit of frozen results; no candidate reselection, threshold adjustment or holdout re-execution.',
 'authored_query_count':36,'supported_queries':24,'held_out_anchor_places':12,
 'semantic_metrics':held['semantic'],'baseline_metrics':held['baseline'],'supported_misses':misses,
 'unsupported':{'total':12,'guard_blocked_count':len(guarded),'guard_blocked_ids':guarded,
                'model_score_rejected_count':len(score_rejected),'model_score_rejected_ids':score_rejected},
 'selected_candidate':'small_pretrained','additional_source_finetuning_selected':False,
 'gpu_candidate_records':records,'cpu_score_threshold':freeze['score_threshold'],
 'final_asset_and_source_hashes':freeze,
 'quantization_check':'Dev query encoding changed from batches to batch_size=1 to match serving before CPU selection freeze. No holdout-driven tuning.',
 'nonlabelled_tail_results':tail_extras,
 'strict_label_card_counts':{'returned_cards_on_supported_queries':strict_returned,'labelled_relevant_cards':strict_relevant},
 'limitations':['23/24 is first/top3 labelled-document hit rate for authored questions, not accuracy of every returned card.',
   'Some later cards do not support every compound query condition; text and original sources must be read.',
   'Unsupported safety combines explicit product scope guards and neural score rejection; it is not all model understanding.',
   'Two queries per holdout anchor are correlated, and the incumbent lexical parser returning0 on these paraphrases is not a general search failure rate.',
   'Fine-tuning pairs include the place name inside the passage, making the contrastive task partly a name-match task.',
   'Runtime remains subject to source review dates; results do not verify current opening or real entrances.']}
(OUT/'independent_semantic_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ['gpu_candidate_records','nonlabelled_tail_results','limitations','final_asset_and_source_hashes']},ensure_ascii=True))
