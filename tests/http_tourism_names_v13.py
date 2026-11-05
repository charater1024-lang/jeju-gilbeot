"""Read-only requests verify canonical names; never use device location."""
import argparse, json, sys
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parent))
from http_smoke_v5 import Client, artifact_hashes

def smoke(root,base,report_path):
    root=Path(root).resolve();client=Client(base);before=artifact_hashes(root);checks={}
    places=client.request('/api/tourism',{'limit':100})['items']
    assert len(places)==68
    def names(items):
        assert items
        assert all(p['name']==p['cross_source']['hub']['name'].strip() and p['map_name']==p['cross_source']['osm']['name'] for p in items)
    names(places);checks['all_68_use_hub_names_and_preserve_map_names']=True
    changed=[p for p in places if p['name']!=p['map_name']]
    assert len(changed)==16
    featured=client.request('/api/destinations')['items'];names(featured)
    name_index={p['id']:p['name'] for p in places}
    slides=client.request('/api/hero-slides')['slides']
    assert slides and all(s['name']==name_index[s['id']] for s in slides)
    checks['home_catalogue_and_hero_names_match']=True
    point=next(p for p in places if p['id']=='osulloc')
    for ident in [point['id'],point['cross_source']['hub']['id'],point['cross_source']['osm']['id']]:
        names([client.request('/api/place-details?id='+ident)['item']])
    checks['canonical_and_original_source_ids_have_same_detail_name']=True
    for query in ['오설록티뮤지엄 정보','오설록 티뮤지엄 정보']:
        reply=client.request('/api/chat',{'message':query});names(reply['cards'])
        assert '오설록 티뮤지엄의 원자료 분류는' in reply['reply']
    checks['old_and_hub_spelling_chat_queries_use_hub_reply_name']=True
    route=client.request('/api/route-geometry',{'destination_ids':['osulloc'],'transport':'car','kind':'straight_line'})
    names(route['stops']);checks['route_uses_hub_names']=True
    search=client.request('/api/places?'+urlencode({'query':'협재','limit':12}));names(search['items'])
    assert search['items'][0]['name']=='협재해수욕장';checks['name_search_uses_hub_names']=True
    assert artifact_hashes(root)==before;checks['models_and_databases_unchanged']=True
    result={'pass':True,'checks':checks,'changed_display_names':16,'tourism_candidates':68,'http_requests':len(client.exchanges),'real_device_location_requested':False,'base_url':base}
    Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8782');p.add_argument('--root',type=Path,default=Path(__file__).parents[1]);p.add_argument('--report',default='docs/http_tourism_names_v13.json')
    a=p.parse_args();print(json.dumps(smoke(a.root,a.base_url,a.report),ensure_ascii=True))
