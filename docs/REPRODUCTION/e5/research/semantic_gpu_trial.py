"""GPU encoder trials on observed name/guide pairs; dev-only selection.

The authored holdout questions are never opened by this training/selection script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time
import sys

WORK=Path(__file__).resolve().parent
STAGE=WORK/'site'
sys.dont_write_bytecode=True
sys.path.insert(0,str(STAGE))
from jeju_agent.assistant_search import search_assistant
from jeju_agent.semantic_search import semantic_query_supported

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

SETTINGS={'seed':20261107,'max_length':256,'epochs':3,'batch_size':4,'learning_rate':2e-5,
          'temperature':0.05,'weight_decay':0.01,'gradient_clip':1.0,
          'candidates':['small_pretrained','small_source40','base_pretrained','base_source40'],
          'thresholds':[.72,.75,.78,.80,.82,.84,.86,.88,.90,.92,.94,.96],
          'selection':'Unsupported dev false responses must be zero; maximize Hit@3, MRR@3, Hit@1, then higher threshold and smaller model.',
          'training_data':'Only the original names and summaries from 40 source-partition=train records.',
          'inference_documents':'All62 source records: canonical name + period + original summary.',
          'holdout_opened':False}

def metric(cases,ranked):
    hits1=[];hits3=[];rr=[];false=0
    for case,ids in zip(cases,ranked):
        if case['kind']=='unsupported':false+=int(bool(ids));continue
        positions=[i+1 for i,x in enumerate(ids[:3]) if x in case['relevant_ids']]
        hits1.append(int(bool(ids) and ids[0] in case['relevant_ids']))
        hits3.append(int(bool(positions)));rr.append(1/min(positions) if positions else 0.)
    return {'supported':len(hits3),'hit_at_1':sum(hits1)/len(hits1),'hit_at_3':sum(hits3)/len(hits3),
            'mrr_at_3':sum(rr)/len(rr),'unsupported_false_responses':false}

def rank(cases,rows,scores,threshold):
    out=[]
    for case,values in zip(cases,scores):
        if not semantic_query_supported(case['query']):out.append([]);continue
        order=sorted(range(len(rows)),key=lambda i:(-float(values[i]),rows[i]['name'],rows[i]['id']))
        out.append([rows[i]['id'] for i in order if float(values[i])>=threshold][:5])
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['freeze','dev','export']);p.add_argument('--candidate')
    args=p.parse_args();OUT=WORK/'semantic';OUT.mkdir(exist_ok=True)
    partitions=read(WORK/'evaluation/source_partitions.json');rows=partitions['rows']
    if args.mode=='freeze':
        assert not (OUT/'settings_frozen.json').exists()
        save(OUT/'settings_frozen.json',dict(SETTINGS,source_partitions_sha256=sha(WORK/'evaluation/source_partitions.json'),
             dev_sha256=sha(WORK/'evaluation/dev_queries.json'),evaluation_protocol_sha256=sha(WORK/'evaluation/protocol.json')))
        print('Froze four candidates and training settings before encoding/evaluation.');return
    settings=read(OUT/'settings_frozen.json')
    for key,value in SETTINGS.items():assert settings[key]==value,key
    assert settings['source_partitions_sha256']==sha(WORK/'evaluation/source_partitions.json')
    import numpy as np
    import torch
    import torch.nn.functional as F
    from transformers import AutoModel,AutoTokenizer
    from huggingface_hub import HfApi,snapshot_download
    torch.set_num_threads(2);torch.manual_seed(SETTINGS['seed']);random.seed(SETTINGS['seed']);np.random.seed(SETTINGS['seed'])
    assert torch.cuda.is_available(),'A real CUDA device is required for this GPU trial'
    device='cuda:0'

    class Encoder(torch.nn.Module):
        def __init__(self,model):super().__init__();self.model=model
        def forward(self,input_ids,attention_mask):
            hidden=self.model(input_ids=input_ids,attention_mask=attention_mask).last_hidden_state
            mask=attention_mask.unsqueeze(-1).to(hidden.dtype)
            return F.normalize((hidden*mask).sum(1)/mask.sum(1).clamp(min=1),p=2,dim=1)

    def load(path):
        tok=AutoTokenizer.from_pretrained(path,local_files_only=True,trust_remote_code=False)
        model=AutoModel.from_pretrained(path,local_files_only=True,trust_remote_code=False,
                                        use_safetensors=True,attn_implementation='eager')
        return tok,Encoder(model).to(device)

    def batch(tok,texts):
        tokens=tok(texts,padding=True,truncation=True,max_length=settings['max_length'],return_tensors='pt')
        return {key:tokens[key].to(device) for key in ['input_ids','attention_mask']}

    def encode(tok,model,texts,batch_size=8):
        model.eval();vectors=[];start=time.perf_counter()
        with torch.inference_mode():
            for i in range(0,len(texts),batch_size):vectors.append(model(**batch(tok,texts[i:i+batch_size])).cpu())
        torch.cuda.synchronize()
        return torch.cat(vectors).numpy(),(time.perf_counter()-start)*1000

    if args.mode=='dev':
        assert not (OUT/'selection_frozen.json').exists(), 'Selection is already frozen'
        dev=read(WORK/'evaluation/dev_queries.json')['cases']
        baseline=[ [r['id'] for r in search_assistant(STAGE,c['query'],include_route_restricted=True)] for c in dev]
        baseline_metrics=metric(dev,baseline)
        results=[];available=[]
        for size in ['small','base']:
            repo='intfloat/multilingual-e5-'+size
            # The revision is recorded before use; no remote model code is executed.
            receipt=OUT/(size+'_download.json')
            if receipt.is_file() and (OUT/(size+'_asset_hashes.json')).is_file():
                revision=read(receipt)['revision'];local=OUT/'pretrained'/size
                for name,entry in read(OUT/(size+'_asset_hashes.json')).items():
                    assert sha(local/name)==entry['sha256'],name
            else:
                revision=HfApi().model_info(repo,expand=['sha']).sha
                save(receipt,{'repo':repo,'revision':revision,'source':'https://huggingface.co/'+repo,'license':'MIT'})
                local=Path(snapshot_download(repo,revision=revision,local_dir=OUT/'pretrained'/size,
                    allow_patterns=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json',
                                    'special_tokens_map.json','sentencepiece.bpe.model','README.md'],max_workers=4))
                save(OUT/(size+'_asset_hashes.json'),{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in local.iterdir() if p.is_file()})
            tok,model=load(local)
            for adapted in [False,True]:
                candidate=size+('_source40' if adapted else '_pretrained')
                torch.cuda.reset_peak_memory_stats();fit_seconds=0.;losses=[];grad_norm=None
                if adapted:
                    train=[r for r in rows if r['partition']=='train'];assert len(train)==40
                    optimizer=torch.optim.AdamW(model.parameters(),lr=settings['learning_rate'],weight_decay=settings['weight_decay'])
                    generator=random.Random(settings['seed']);start=time.perf_counter();model.train()
                    for epoch in range(settings['epochs']):
                        order=list(range(len(train)));generator.shuffle(order)
                        for i in range(0,len(order),settings['batch_size']):
                            part=[train[j] for j in order[i:i+settings['batch_size']]]
                            q=model(**batch(tok,['query: '+r['name'] for r in part]))
                            docs=model(**batch(tok,['passage: '+r['name']+'. '+r['summary'] for r in part]))
                            logits=q@docs.T/settings['temperature'];labels=torch.arange(len(part),device=device)
                            loss=(F.cross_entropy(logits,labels)+F.cross_entropy(logits.T,labels))/2
                            optimizer.zero_grad(set_to_none=True);loss.backward()
                            grad_norm=float(torch.nn.utils.clip_grad_norm_(model.parameters(),settings['gradient_clip']))
                            optimizer.step();losses.append(float(loss.detach()))
                    torch.cuda.synchronize();fit_seconds=time.perf_counter()-start
                    del optimizer
                    model.model.save_pretrained(OUT/'adapted'/size,safe_serialization=True)
                    tok.save_pretrained(OUT/'adapted'/size)
                docs,doc_ms=encode(tok,model,['passage: '+r['name']+'. '+r['summary'] for r in rows])
                queries,query_ms=encode(tok,model,['query: '+c['query'] for c in dev])
                scores=queries@docs.T;thresholds=[]
                for threshold in settings['thresholds']:
                    ranked=rank(dev,rows,scores,threshold)
                    thresholds.append({'threshold':threshold,'metrics':metric(dev,ranked),'ranked_ids':ranked})
                acceptable=[r for r in thresholds if r['metrics']['unsupported_false_responses']==0]
                best=max(acceptable,key=lambda r:(r['metrics']['hit_at_3'],r['metrics']['mrr_at_3'],r['metrics']['hit_at_1'],r['threshold']))
                path=OUT/'adapted'/size if adapted else local
                record={'candidate':candidate,'repo':repo,'revision':revision,'path':str(path),
                        'dimension':int(docs.shape[1]),'parameters':sum(p.numel() for p in model.parameters()),
                        'gpu_device':torch.cuda.get_device_name(),'torch_version':torch.__version__,'cuda_version':torch.version.cuda,
                        'training_pairs':40 if adapted else 0,'training_steps':len(losses),'training_seconds':fit_seconds,
                        'gradient_norm_final':grad_norm,'loss_first':losses[0] if losses else None,'loss_final':losses[-1] if losses else None,
                        'peak_vram_bytes':torch.cuda.max_memory_allocated(),'document_encode_ms':doc_ms,'dev_encode_ms':query_ms,
                        'best':best,'threshold_grid':thresholds}
                save(OUT/(candidate+'_dev.json'),record);results.append(record)
                print(json.dumps({k:record[k] for k in ['candidate','parameters','training_steps','training_seconds','peak_vram_bytes','best']},ensure_ascii=True),flush=True)
            del model,tok;torch.cuda.empty_cache()
        eligible=[r for r in results if r['best']['metrics']['unsupported_false_responses']==0]
        chosen=max(eligible,key=lambda r:(r['best']['metrics']['hit_at_3'],r['best']['metrics']['mrr_at_3'],r['best']['metrics']['hit_at_1'],r['best']['threshold'],-r['parameters']))
        save(OUT/'gpu_dev_results.json',{'baseline':baseline_metrics,'baseline_ids':baseline,'candidates':results})
        save(OUT/'selection_frozen.json',{'candidate':chosen['candidate'],'candidate_record_sha256':sha(OUT/(chosen['candidate']+'_dev.json')),
             'candidate_path':chosen['path'],'model_id':chosen['repo'],'revision':chosen['revision'],
             'dimension':chosen['dimension'],'threshold_gpu_dev':chosen['best']['threshold'],
             'settings_sha256':sha(OUT/'settings_frozen.json'),'source_partitions_sha256':settings['source_partitions_sha256'],
             'selection_scope':'dev only; CPU quantized dev recalibration precedes holdout; no holdout opened'})
        return
    selected=read(OUT/'selection_frozen.json')
    tok,model=load(selected['candidate_path']);model.cpu().eval()
    sample=tok(['query: 바다와 화산의 풍경'],return_tensors='pt')
    export=OUT/'export';export.mkdir(exist_ok=True)
    torch.onnx.export(model,(sample['input_ids'],sample['attention_mask']),str(export/'encoder.fp32.onnx'),
        input_names=['input_ids','attention_mask'],output_names=['embedding'],opset_version=17,dynamo=False,
        dynamic_axes={'input_ids':{0:'batch',1:'sequence'},'attention_mask':{0:'batch',1:'sequence'},'embedding':{0:'batch'}})
    from onnxruntime.quantization import quantize_dynamic,QuantType
    import onnx
    # Pass an in-memory proto: the native shape-inference path does not handle
    # this Windows workspace's Korean directory name reliably.
    quantize_dynamic(onnx.load(str(export/'encoder.fp32.onnx')),str(export/'encoder.int8.onnx'),
        weight_type=QuantType.QInt8,per_channel=True,op_types_to_quantize=['MatMul','Gemm','Gather'])
    tok.backend_tokenizer.save(str(export/'tokenizer.json'))
    save(export/'export_receipt.json',{'selection_sha256':sha(OUT/'selection_frozen.json'),
         'fp32_bytes':(export/'encoder.fp32.onnx').stat().st_size,'int8_bytes':(export/'encoder.int8.onnx').stat().st_size,
         'model_sha256':sha(export/'encoder.int8.onnx'),'tokenizer_sha256':sha(export/'tokenizer.json'),
         'note':'CPU quantized rankings must be dev-validated before holdout or deployment.'})
    print('Exported selected encoder for independent local CPU evaluation.',flush=True)

if __name__=='__main__':main()
