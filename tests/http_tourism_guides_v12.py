"""Read-only local guide integration using public place data, never GPS."""
import argparse,json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from http_smoke_v5 import Client,artifact_hashes

def smoke(root,base,report_path):
    root=Path(root).resolve();client=Client(base);checks={};before=artifact_hashes(root)
    guide_path=root/'data_reference/tourism_guides_v12.json';guide_sha=hashlib.sha256(guide_path.read_bytes()).hexdigest()
    source=json.loads(guide_path.read_text(encoding='utf-8'));guides={p['id']:p for p in source['guides']}
    featured=client.request('/api/destinations')['items']
    assert len(featured)==6 and all(p['tourism_guide_available'] and p.get('tourism_guide') for p in featured)
    checks['featured_guides_available']=True
    tourism=client.request('/api/tourism',{'limit':100})
    assert tourism['total']==68 and len(tourism['items'])==68
    available=[p for p in tourism['items'] if p.get('tourism_guide_available')]
    assert len(available)==len(guides)==62
    assert all(p['description']==p['tourism_guide']['summary']==guides[p['id']]['summary'] for p in available)
    assert all(p['source_overlap_verified'] for p in tourism['items'])
    checks['all_tourism_surfaces_same_62_of_68_guides']=True
    detail=client.request('/api/place-details?id=seongsan')['item']
    assert detail['tourism_guide']['source_url'].startswith('https://www.visitjeju.net/')
    assert 'openstreetmap.org' in detail['source_url'] and detail['tourism_guide']['source_url']!=detail['source_url']
    assert detail['description']==guides['seongsan']['summary'] and detail['map_description']!=detail['description']
    checks['detail_tourism_and_map_provenance_separate']=True
    missing=[p for p in tourism['items'] if not p['tourism_guide_available']]
    assert len(missing)==6 and all(p.get('tourism_guide') is None for p in missing)
    item=client.request('/api/place-details?id='+missing[0]['id'])['item']
    assert item['tourism_guide'] is None and item['tourism_guide_available'] is False
    checks['missing_sources_remain_explicit_without_synthetic_story']=True
    chat=client.request('/api/chat',{'message':'성산일출봉 정보'})
    assert chat['reply'].startswith(guides['seongsan']['summary']) and chat['cards'][0]['tourism_guide']['source_url']==guides['seongsan']['source_url']
    checks['prepared_chat_reuses_same_offline_guide']=True
    assert artifact_hashes(root)==before and hashlib.sha256(guide_path.read_bytes()).hexdigest()==guide_sha
    checks['models_databases_and_guide_file_unchanged']=True
    result={'pass':True,'checks':checks,'http_requests':len(client.exchanges),'tourism_candidates':68,'guides':62,'missing':6,'models_and_databases_unchanged':True,'real_device_location_requested':False,'base_url':base}
    Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:8780');parser.add_argument('--root',type=Path,default=Path(__file__).parents[1]);parser.add_argument('--report',default='docs/http_tourism_guides_v12.json')
    a=parser.parse_args();print(json.dumps(smoke(a.root,a.base_url,a.report),ensure_ascii=True))
