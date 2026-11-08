"""Read-only loopback tests of GPU residency and non-truncating CPU fallback."""
import argparse,json
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit
def main():
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8765');p.add_argument('--output',type=Path,required=True);p.add_argument('--expect-cpu',action='store_true');a=p.parse_args()
    assert urlsplit(a.base).hostname=='127.0.0.1' and urlsplit(a.base).scheme=='http'
    client=build_opener(ProxyHandler({}));calls=[]
    def request(path,body=None,status=200):
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode('utf-8')
        req=Request(a.base+path,data=data,headers={'Origin':a.base,'Content-Type':'application/json'})
        try:
            with client.open(req,timeout=45) as r:code,raw=r.status,r.read()
        except HTTPError as e:code,raw=e.code,e.read()
        assert code==status,(path,code,status);calls.append({'path':path,'status':code})
        return json.loads(raw) if code==200 else None
    before=request('/api/compute-status')
    assert before['preload']['scope']=='startup_result_not_current_state'
    if not a.expect_cpu:
        assert before['semantic']['gpu_ready'] and before['semantic']['gpu_resident']
        assert before['semantic']['dml_kernel_events']>0 and before['semantic']['gpu_sequence_length']==64
    assert isinstance(request('/api/semantic-guide-search',{'query':'오랜 나무 그늘과 화산송이 길을 따라 걷는 숲'}),list)
    normal=request('/api/compute-status')
    if a.expect_cpu:
        assert normal['requested_semantic_device']=='cpu' and not normal['semantic']['gpu_ready'] and not normal['road']['requested']
    else:
        assert normal['semantic']['last_execution_provider']=='DmlExecutionProvider'
        query=('제주 숲 해안 자연 산책 박물관 역사 화산 오름 바다 전통 마을 '*5)[:160]
        assert isinstance(request('/api/semantic-guide-search',{'query':query}),list)
        fallback=request('/api/compute-status')
        assert fallback['semantic']['last_execution_provider']=='CPUExecutionProvider'
        assert fallback['semantic']['gpu_ready'] and fallback['semantic']['gpu_resident']
        assert fallback['semantic']['cpu_long_query_fallbacks']>normal['semantic']['cpu_long_query_fallbacks']
        assert fallback['semantic']['last_query_token_count']>64
        request('/api/semantic-guide-search',{'query':'오랜 나무 그늘과 화산송이 길을 따라 걷는 숲'})
        assert request('/api/compute-status')['semantic']['last_execution_provider']=='DmlExecutionProvider'
    request('/models_semantic/encoder.fp32.onnx',status=404)
    after=request('/api/compute-status')
    result={'pass':True,'base':a.base,'requests':len(calls),'calls':calls,'expect_cpu':a.expect_cpu,'initial_state':before,'final_state':after,'real_device_gps_used':False,'model_and_source_policy_unchanged':True}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pass':True,'requests':len(calls),'cpu':a.expect_cpu,'gpu_ready':after['semantic']['gpu_ready'],'pid':after['server_process_id']},ensure_ascii=True))
if __name__=='__main__':main()
