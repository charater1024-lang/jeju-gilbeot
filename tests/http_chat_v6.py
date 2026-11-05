"""Local HTTP chat integration. Public-place fixtures, no device GPS or external hosts."""
import argparse,json,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from http_smoke_v5 import Client,artifact_hashes

def smoke(root,base,report_path):
    root=Path(root).resolve();client=Client(base);before=artifact_hashes(root);checks={};samples=[]
    def ask(message,state=None,status=200):
        result=client.request('/api/chat',{'message':message,'state':state or {}},status=status)
        if status==200:
            assert result['offline'] is True and result['llm_used'] is False
            assert isinstance(result['reply'],str) and result['reply']
            assert result['answer_source'] in {'faq','prepared_text','model_search','clarification'}
            samples.append({'message':message,'intent':result['intent'],'reply':result['reply'],'card_ids':[p['id'] for p in result['cards']]})
        return result
    status=client.request('/api/chat/status')
    profile=json.loads((root/'data_reference/chatbot_profile.json').read_text(encoding='utf-8'))
    assert status['prepared_answers']==profile['prepared_answers']==sum(profile['data_counts'].values())
    assert status['faq_count']==profile['faq_count'] and status['llm_used'] is False
    checks['actual_prepared_answers_and_no_llm']=True
    home=ask('처음으로');assert home['quick_replies'] and home['answer_source']=='faq';checks['guided_menu']=True
    search=ask('북부 해변 추천해줘');assert search['cards'] and all(p['region']=='north' for p in search['cards'])
    assert search['answer_source']=='model_search' and search['state']['choice_ids']==[p['id'] for p in search['cards']]
    checks['tourism_model_and_state']=True
    selected=ask('두 번째 장소 알려줘',search['state']);assert selected['cards'][0]['id']==search['cards'][1]['id'];assert selected['answer_source']=='prepared_text'
    address=ask('주소 알려줘',selected['state']);assert address['cards'][0]['id']==selected['cards'][0]['id'];checks['ordinal_and_field_followup']=True
    named=ask('함덕해수욕장 주소');assert '525' in named['reply'] and named['cards'][0]['id']=='hamdeok';checks['source_grounded_named_address']=True
    unknown_place=ask('서울역 주소 알려줘',named['state']);assert not unknown_place['cards'] and '525' not in unknown_place['reply'];checks['new_unknown_place_not_previous_address']=True
    realtime=ask('함덕 지금 비 와?',named['state']);assert '확인' in realtime['reply'] and realtime['intent']!='place_details';checks['named_realtime_unavailable']=True
    data=ask('데이터 출처',named['state']);assert data['answer_source']=='faq' and '허브' in data['reply'];checks['service_faq_over_place_context']=True
    unknown=ask('서부 삼성전자 주가 알려줘',search['state']);assert not unknown['cards'] and unknown['state']['region']==search['state']['region'];checks['out_of_scope_keeps_search_state']=True
    negative=ask('해변 말고 박물관 추천',search['state']);assert negative['answer_source']=='clarification' or negative['state']['last_query']=='박물관';checks['negation_not_wrong_beach_recommendation']=True
    food=ask('고기국수 먹고 싶어');assert food['cards'] and food['answer_source']=='model_search';checks['food_model_search']=True
    ask('a'*301,status=400);ask({'text':'함덕'},status=400);checks['input_validation']=True
    after=artifact_hashes(root);assert before==after;checks['immutable_models_and_answer_db']=True
    report={'pass':True,'base_url':base,'checks':checks,'http_requests':len(client.exchanges),'exchanges':client.exchanges,'samples':samples,'artifacts_unchanged':True,'real_gps_used':False,'external_hosts_contacted':False,'prepared_answers':status['prepared_answers'],'faq_count':status['faq_count']}
    Path(report_path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8770');parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--report',type=Path)
    args=parser.parse_args();report=smoke(args.root,args.base_url,args.report or args.root/'docs/http_chat_v6.json');print(json.dumps({k:report[k] for k in ['pass','checks','http_requests','artifacts_unchanged','prepared_answers','faq_count']},ensure_ascii=True))
