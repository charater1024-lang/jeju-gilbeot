"""Local HTTP location-chat smoke with a public airport fixture, never device GPS."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from http_smoke_v5 import Client,artifact_hashes

PUBLIC_AIRPORT={'latitude':33.5104142,'longitude':126.4913534}


def smoke(root,base,report_path):
    root=Path(root).resolve();client=Client(base);before=artifact_hashes(root);checks={}
    def ask(message,location=None,state=None,declined=False,status=200):
        return client.request('/api/chat',{'message':message,'state':state or {},'location':location,'location_declined':declined},status=status)
    missing=ask('내 근처 관광지 추천')
    assert missing['needs_location'] and not missing['location_used'] and not missing['cards']
    checks['missing_origin_requests_consent']=True
    nearby=ask('내 근처 관광지 추천',PUBLIC_AIRPORT)
    assert nearby['location_used'] and not nearby['needs_location'] and nearby['radius_km']==20 and nearby['cards']
    assert nearby['location_source']=='device'
    assert all(isinstance(p['distance_km'],(int,float)) and 0<=p['distance_km']<=20 for p in nearby['cards'])
    assert 'latitude' not in json.dumps(nearby['state']) and 'longitude' not in json.dumps(nearby['state'])
    checks['source_model_and_request_only_origin']=True
    next_page=ask('다른 곳 추천',PUBLIC_AIRPORT,nearby['state'])
    assert next_page['location_used'] and not ({p['id'] for p in nearby['cards']}&{p['id'] for p in next_page['cards']})
    assert ask('다른 곳 추천',state=nearby['state'])['needs_location']
    checks['fresh_origin_required_for_nearby_followup']=True
    food=ask('내 근처 고기국수 추천',PUBLIC_AIRPORT)
    assert food['intent']=='food_search' and food['location_used'] and food['cards']
    assert all(p['within_radius'] is True and p['latitude'] is not None for p in food['cards'])
    checks['food_request_excludes_unmapped']=True
    manual=ask('근처 관광지 추천',{**PUBLIC_AIRPORT,'source':'manual','label':'제주국제공항'})
    assert manual['location_source']=='manual' and '선택한 기준 장소' in manual['reply'] and '기기 위치' not in manual['reply']
    checks['manual_source_distinguished']=True
    decline=ask('북부 근처 해변 추천',declined=True)
    assert not decline['location_used'] and not decline['needs_location'] and decline['cards']
    assert all(p['region']=='north' and p['distance_km'] is None for p in decline['cards'])
    checks['decline_continues_region_search']=True
    outside=ask('내 근처 맛집 추천',{'latitude':37.5665,'longitude':126.978})
    assert outside['location_status']=='outside_jeju' and not outside['location_used'] and not outside['cards']
    checks['outside_jeju_not_false_nearby']=True
    ask('관광지 추천',{'latitude':True,'longitude':126.5},status=400)
    ask('관광지 추천',{**PUBLIC_AIRPORT,'source':'unknown'},status=400)
    checks['invalid_origin_rejected']=True
    status=client.request('/api/chat/status')
    assert status['location_recommendation']['consent_required'] and not status['privacy']['precise_location_persisted']
    assert artifact_hashes(root)==before
    checks['models_and_prepared_answers_immutable']=True
    report={'pass':True,'base_url':base,'checks':checks,'http_requests':len(client.exchanges),'real_gps_used':False,'fixture':'public_airport_coordinate','models_and_databases_unchanged':True}
    Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8772')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    print(json.dumps(smoke(args.root,args.base_url,args.report or args.root/'docs/http_chat_nearby_v8.json'),ensure_ascii=True))
