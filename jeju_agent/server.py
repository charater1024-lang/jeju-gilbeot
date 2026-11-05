"""Loopback-only local UI with no external APIs or third party dependencies."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
from urllib.parse import urlsplit, parse_qs, unquote
from threading import BoundedSemaphore
from .reference import catalogue, restaurants, plan_destinations, read_json
from .catalog_store import parking
from .tourism_access import place_search
from .insights import food_insight, mobility_insight, insight_status
from .discovery import discovery_recommend
from .tourism import get_model_info
from .model_runtime_v20 import active_tourism_search as search_tourism
from .model_portfolio import get_model_evaluation
from .roads import route_geometry
from .place_details import place_details
from .chatbot import chat_reply, chat_status
from .orchestrator import run_agent
from .assistant import run_assistant
from .extensions import data_guide
from .place_trust import TrustPolicyError

ROOT=Path(__file__).resolve().parent.parent

def hero_slides(root):
    """Use the approved display name without changing photo identity or source proof."""
    from .tourism_access import approved_places
    data=read_json(Path(root)/'config'/'hero_slides.json',{'slides':[]})
    approved={p['id']:p for p in approved_places(root)}
    slides=[]
    for raw in data.get('slides',[]):
        place=approved.get(raw.get('id'))
        if not place:continue
        name=place.get('name')
        if not isinstance(name,str) or not name.strip():continue
        name=name.strip();old=raw.get('name');slide=dict(raw,name=name)
        for field in ['caption','title']:
            value=raw.get(field)
            if isinstance(value,str) and isinstance(old,str) and old:
                slide[field]=value.replace(old,name)
        slides.append(slide)
    return dict(data,slides=slides)


def service_status(root):
    """Describe the real-data service without opening or training demo artifacts."""
    root=Path(root)
    models=get_model_info(root)
    cards=models['cards']
    tourism=read_json(root/'data_reference/tourism_profile.json',{})
    food=read_json(root/'data_reference/discovery_profile.json',{})
    return {'service_version':20,'model_evaluation_endpoint':'/api/model-evaluation','data':{'data_mode':'real_sources',
            'tourism_candidates':tourism.get('training_rows',0),
            'food_source_records':food.get('training_documents',0)},
            'models':cards,'ready':all(card.get('available') for card in cards),
            'synthetic_service_enabled':False,'runtime':'offline_cpu',
            'assistant':{'endpoint':'/api/assistant','routing':'char_ngram_multinomial_nb',
                         'llm_used':False,'source_preference':'jeju_data_hub'},
            'agent':{'mode':'central_tool_orchestrator','endpoint':'/api/agent/plan','stages':['request_validation','retrieval','source_trust','place_selection','constraint_validation','route_reference','explanation'],'llm_used':False,'autonomous_tool_selection':False,'input_interpretation':'structured_fields_and_limited_query_rules'},
            'note':'실제 출처의 관광·음식 기록과 과거 소비·승차 자료만 서비스에 사용합니다.'}


def serve(data_dir=None,model_dir=None,port=8765):
    # Legacy positional arguments are kept for launchers. Demo files are unused.
    status_snapshot=service_status(ROOT)

    class Handler(BaseHTTPRequestHandler):
        def json_response(self,obj,status=200):
            payload=json.dumps(obj,ensure_ascii=False).encode('utf-8')
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(payload))); self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(payload)

        def do_GET(self):
            url=urlsplit(self.path)
            path=unquote(url.path)
            query=parse_qs(url.query)
            if path=='/api/model-evaluation':
                try:
                    return self.json_response(get_model_evaluation(ROOT))
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    return self.json_response({'error':'모델 평가 명세를 확인해 주세요.'},503)
            if path=='/api/data-guide':
                try:
                    return self.json_response(data_guide(ROOT, {key:values[0] for key,values in query.items()}))
                except (ValueError,TypeError,KeyError) as exc:
                    return self.json_response({'error':str(exc)},400)
                except FileNotFoundError:
                    return self.json_response({'error':'이 자료의 모델 또는 검증된 원본이 아직 준비되지 않았습니다.'},503)
            if path=='/api/chat/status':
                try:return self.json_response(chat_status(ROOT))
                except FileNotFoundError:return self.json_response({'error':'상담 답변 자료가 준비되지 않았습니다.'},503)
            if path in {'/api/models-info','/api/offline-roads','/api/place-details'}:
                try:
                    if path=='/api/models-info':return self.json_response(get_model_info(ROOT))
                    if path=='/api/offline-roads':return self.json_response(read_json(ROOT/'data_reference/offline_roads.json',{'lines':[]}))
                    result=place_details(ROOT,query.get('id',[''])[0])
                    return self.json_response(result or {'error':'장소를 찾을 수 없습니다.'},200 if result else 404)
                except (ValueError,TypeError) as exc:return self.json_response({'error':str(exc)},400)
                except FileNotFoundError:return self.json_response({'error':'장소·모델 자료가 준비되지 않았습니다.'},503)
            if path=='/api/hero-slides':
                return self.json_response(hero_slides(ROOT))
            if path in {'/api/insights/food','/api/insights/mobility','/api/insights/status','/api/places','/api/amenities'}:
                try:
                    if path=='/api/insights/status': result=insight_status(ROOT)
                    elif path=='/api/insights/food': result=food_insight(ROOT,query.get('audience',['resident'])[0],query.get('month',[None])[0],query.get('region',['all'])[0])
                    elif path=='/api/insights/mobility': result=mobility_insight(ROOT,query.get('date',[''])[0],query.get('period',['daytime'])[0])
                    elif path=='/api/places': result=place_search(ROOT,query.get('query',[''])[0],query.get('region',['all'])[0],query.get('limit',['12'])[0])
                    else:
                        if query.get('type',['parking'])[0]!='parking':raise ValueError('지원하는 편의시설 유형은 parking입니다.')
                        result=parking(ROOT,query.get('region',['all'])[0])
                    return self.json_response(result)
                except (ValueError,KeyError,TypeError) as exc:return self.json_response({'error':str(exc)},400)
                except FileNotFoundError:return self.json_response({'error':'분석 자료 또는 모델이 준비되지 않았습니다.'},503)
            if path=='/api/destinations':
                return self.json_response(catalogue(ROOT))
            if path=='/api/data-status':
                return self.json_response(read_json(ROOT/'config'/'download_manifest.json',{'datasets':[],'downloaded_count':0,'note':'자료를 준비 중입니다.'}))
            if path=='/api/restaurants':
                try:
                    return self.json_response(restaurants(ROOT,query.get('query',[''])[0],query.get('region',['all'])[0],query.get('limit',['6'])[0]))
                except ValueError as exc: return self.json_response({'error':str(exc)},400)
            if path=='/api/status':
                return self.json_response(status_snapshot)
            if path=='/api/sources':
                p=ROOT/'config'/'sources.json'
                return self.json_response(json.loads(p.read_text(encoding='utf-8')))
            relative='index.html' if path.rstrip('/') in {'','/planner','/explore','/chat','/about'} else path.lstrip('/')
            static_root=(ROOT/'ui').resolve()
            file=(static_root/relative).resolve()
            if not file.is_relative_to(static_root) or not file.is_file() or file.suffix.lower() not in {'.html','.css','.js','.jpg','.jpeg','.png','.webp','.svg','.woff2'}:
                return self.json_response({'error':'경로를 찾을 수 없습니다.'},404)
            payload=file.read_bytes()
            content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
            if file.suffix in {'.html','.js','.css'}: content_type+='; charset=utf-8'
            self.send_response(200); self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)

        def do_POST(self):
            try:
                if self.headers.get('Origin') not in {None,f'http://127.0.0.1:{port}',f'http://localhost:{port}'}:
                    return self.json_response({'error':'로컬 UI 요청만 허용합니다.'},403)
                if self.path=='/api/recommend':
                    return self.json_response({'error':'가상 장소·합성 데이터 추천은 서비스에서 제공하지 않습니다. 실제 장소를 선택해 일정을 만들어 주세요.','code':'synthetic_service_removed'},410)
                n=int(self.headers.get('Content-Length','0'))
                if n<=0 or n>32768: raise ValueError('요청 크기를 확인하세요.')
                body=json.loads(self.rfile.read(n))
                if self.path not in {'/api/assistant','/api/agent/plan','/api/plan-destinations','/api/discover','/api/tourism','/api/route-geometry','/api/chat'}: return self.json_response({'error':'지원하지 않는 경로'},404)
                if not isinstance(body,dict): raise ValueError('JSON 객체가 필요합니다.')
                if self.path=='/api/agent/plan':return self.json_response(run_agent(ROOT,body))
                if self.path=='/api/assistant':return self.json_response(run_assistant(ROOT,body))
                if self.path=='/api/chat':return self.json_response(chat_reply(ROOT,body))
                if self.path=='/api/tourism':return self.json_response(search_tourism(ROOT,body))
                if self.path=='/api/route-geometry':return self.json_response(route_geometry(ROOT,body))
                if self.path=='/api/discover':
                    return self.json_response(discovery_recommend(ROOT,body))
                if self.path=='/api/plan-destinations':
                    return self.json_response(plan_destinations(ROOT,body))
                return self.json_response({'error':'지원하지 않는 경로'},404)
            except TrustPolicyError:
                return self.json_response({'error':'장소의 출처를 확인할 수 없어 코스 추천을 중단했습니다. 운영자가 출처 자료와 확인 기준을 검토한 뒤 다시 시도해 주세요.','code':'trust_policy_unavailable'},503)
            except (ValueError,KeyError,TypeError) as exc:
                return self.json_response({'error':str(exc)},400)
            except Exception:
                return self.json_response({'error':'실행 실패. 데이터와 모델 경로를 점검하세요.'},500)

        def log_message(self,fmt,*args):
            print(f'[local] {fmt % args}',flush=True)

    class CenterServer(ThreadingHTTPServer):
        daemon_threads=True
        request_queue_size=16
        def __init__(self,*args,**kwargs):
            self._workers=BoundedSemaphore(8)
            super().__init__(*args,**kwargs)
        def process_request(self,request,client_address):
            request.settimeout(15)
            self._workers.acquire()
            try: super().process_request(request,client_address)
            except Exception:
                self._workers.release();raise
        def process_request_thread(self,request,client_address):
            try:super().process_request_thread(request,client_address)
            finally:self._workers.release()
    server=CenterServer(('127.0.0.1',port),Handler)
    print(f'Local UI: http://127.0.0.1:{port}  종료: Ctrl+C',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
