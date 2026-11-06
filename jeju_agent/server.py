"""Loopback-only local UI with no external APIs or third party dependencies."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import math
import mimetypes
import time
from urllib.parse import urlsplit, parse_qs, unquote
from threading import BoundedSemaphore
from .reference import catalogue, restaurants, plan_destinations, read_json
from .catalog_store import parking
from .tourism_access import approved_places, place_search
from .insights import food_insight, insight_status
from .discovery import discovery_recommend
from .tourism import search_tourism
from .quality_v23 import operating_evaluation as get_model_evaluation, operating_model_info as get_model_info
from .audience_v23 import audience_status_v23, predict_audience_v23
from .assistant_search import search_assistant
from .roads import route_geometry
from .place_details import place_details
from .chatbot import chat_reply, chat_status
from .orchestrator import run_agent
from .extensions import data_guide
from .place_trust import TrustPolicyError, place_trust

ROOT=Path(__file__).resolve().parent.parent


def _finite_json_number(token):
    number = float(token)
    if not math.isfinite(number):
        raise ValueError('JSON 숫자는 유한한 값이어야 합니다.')
    return number


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
    return {'service_version':23,'model_evaluation_endpoint':'/api/model-evaluation','data':{'data_mode':'real_sources',
            'tourism_candidates':tourism.get('training_rows',0),
            'food_source_records':food.get('training_documents',0)},
            'models':cards,'ready':all(card.get('available') for card in cards),
            'synthetic_service_enabled':False,'runtime':'offline_cpu',
            'assistant':{'endpoint':'/api/guide-search','routing':'explicit_official_guide_search',
                         'llm_used':False,'source_preference':'jeju_data_hub'},
            'agent':{'mode':'central_tool_orchestrator','endpoint':'/api/agent/plan','stages':['request_validation','retrieval','source_trust','place_selection','constraint_validation','route_reference','explanation'],'llm_used':False,'autonomous_tool_selection':False,'input_interpretation':'structured_fields_and_limited_query_rules'},
            'note':'공식 자료 조회와 고정 평가를 통과한 소비 구성비·공식 소개 모델을 제공합니다.'}


def operational_check(root):
    from .dining_model import predict_dining

    root = Path(root)
    status = service_status(root)
    unavailable_models = []
    try:
        predict_dining(root, limit=1)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
        unavailable_models.append('1047')
    checks = [place_trust(root, item) for item in approved_places(root)]
    guide_checks = [item['checks']['official_guide'] for item in checks]
    current = [item for item in guide_checks if item['status'] == 'official_source_record_verified']
    return {
        'models_ready': status['ready'] and not unavailable_models,
        'unavailable_models': unavailable_models,
        'model_count': len(status['models']),
        'automatic_places': sum(item['automatic_eligible'] for item in checks),
        'guides_current': len(current),
        'guides_due_within_30_days': sum(item['max_review_age_days'] - item['age_days'] <= 30 for item in current),
        'guides_overdue': sum(item['status'] == 'review_overdue' for item in guide_checks),
        'road_file_present': (root/'data_reference/roads.sqlite').is_file(),
    }


def serve(data_dir=None,model_dir=None,port=8765):
    # Legacy positional arguments are kept for launchers. Demo files are unused.
    status_snapshot=service_status(ROOT)

    class Handler(BaseHTTPRequestHandler):
        holding_work_slot = False

        def run_work(self, action, *args):
            self.server.work_slots.acquire()
            self.holding_work_slot = True
            try:
                return action(*args)
            finally:
                self.release_work_slot()

        def release_work_slot(self):
            if self.holding_work_slot:
                self.holding_work_slot = False
                self.server.work_slots.release()

        def json_response(self,obj,status=200):
            payload=json.dumps(obj,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.release_work_slot()
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(payload))); self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(payload)

        def do_GET(self):
            try:
                self.run_work(self.serve_get)
            except (ConnectionError, TimeoutError):
                pass

        def serve_get(self):
            url=urlsplit(self.path)
            path=unquote(url.path)
            query=parse_qs(url.query)
            if path=='/api/operational-check':
                try:
                    return self.json_response(operational_check(ROOT))
                except (OSError, ValueError, KeyError, TypeError, TrustPolicyError):
                    return self.json_response({'error':'운영 모델 또는 장소 검증 자료를 확인해 주세요.'},503)
            if path=='/api/observed-reference':
                try:
                    profile = predict_audience_v23(ROOT, query.get('audience',[''])[0], query.get('month',[''])[0])
                    return self.json_response({key: profile[key] for key in ('source_id','observation_period','categories')})
                except ValueError as exc:
                    return self.json_response({'error':str(exc)},400)
                except (OSError, KeyError, TypeError):
                    return self.json_response({'error':'1048 모델 자료를 확인해 주세요.'},503)
            if path=='/api/model-evaluation':
                try:
                    return self.json_response(get_model_evaluation(ROOT))
                except (OSError, ValueError, TypeError, KeyError, AttributeError):
                    return self.json_response({'error':'모델 평가 명세를 확인해 주세요.'},503)
            if path=='/api/insights/mobility' or (path=='/api/data-guide' and query.get('kind', [''])[0]=='route'):
                return self.json_response({'error':'승차 추정은 운영 평가 기준 미달로 제공을 중단했습니다.', 'code':'ridership_model_retired'},410)
            if path=='/api/data-guide':
                try:
                    params={key:values[0] for key,values in query.items()}
                    params.setdefault('kind','dining')
                    if params['kind']=='dining': get_model_evaluation(ROOT)
                    return self.json_response(data_guide(ROOT, params, learned_search=False))
                except (ValueError,TypeError,KeyError) as exc:
                    return self.json_response({'error':str(exc)},400)
                except FileNotFoundError:
                    return self.json_response({'error':'이 자료의 모델 또는 검증된 원본이 아직 준비되지 않았습니다.'},503)
            if path=='/api/chat/status':
                try:return self.json_response(chat_status(ROOT,learned_search=False))
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
            if path in {'/api/insights/food','/api/insights/status','/api/places','/api/amenities'}:
                try:
                    if path=='/api/insights/status':
                        result=insight_status(ROOT)
                        result.update(food=audience_status_v23(ROOT),mobility={'available':False},note='검증된 소비 구성비와 실제 명부를 제공합니다.')
                    elif path=='/api/insights/food':
                        get_model_evaluation(ROOT)
                        result=food_insight(ROOT,query.get('audience',['resident'])[0],query.get('month',[None])[0],query.get('region',['all'])[0],quality_v23=True)
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
            self.release_work_slot()
            self.send_response(200); self.send_header('Content-Type',content_type)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)

        def read_post_body(self, length):
            deadline = time.monotonic() + 5
            payload = bytearray()
            while len(payload) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(length - len(payload))
                if not chunk:
                    raise ValueError('요청 본문이 전송 도중 끊겼습니다.')
                payload.extend(chunk)
            self.connection.settimeout(15)
            return payload

        def do_POST(self):
            try:
                if self.headers.get('Origin') not in {None,f'http://127.0.0.1:{port}',f'http://localhost:{port}'}:
                    return self.json_response({'error':'로컬 UI 요청만 허용합니다.'},403)
                if self.path=='/api/assistant':
                    return self.json_response({'error':'자동 문장 분류는 운영 평가 기준 미달로 제공을 중단했습니다. 일정 조건을 직접 선택해 주세요.', 'code':'assistant_intent_retired', 'planner':'/planner#planner-form'},410)
                if self.path=='/api/recommend':
                    return self.json_response({'error':'가상 장소·합성 데이터 추천은 서비스에서 제공하지 않습니다. 실제 장소를 선택해 일정을 만들어 주세요.','code':'synthetic_service_removed'},410)
                n=int(self.headers.get('Content-Length','0'))
                if n<=0 or n>32768: raise ValueError('요청 크기를 확인하세요.')
                try:
                    raw_body = self.read_post_body(n)
                except TimeoutError:
                    self.connection.settimeout(1)
                    return self.json_response({'error':'요청 본문 전송 시간이 초과되었습니다.'},408)
                body=json.loads(raw_body,parse_float=_finite_json_number,parse_constant=_finite_json_number)
                if self.path not in {'/api/guide-search','/api/agent/plan','/api/plan-destinations','/api/discover','/api/tourism','/api/route-geometry','/api/chat'}: return self.json_response({'error':'지원하지 않는 경로'},404)
                if not isinstance(body,dict): raise ValueError('JSON 객체가 필요합니다.')
                return self.run_work(self.serve_post, body)
            except (ConnectionError, TimeoutError):
                return
            except RecursionError:
                return self.json_response({'error':'요청의 JSON 중첩이 너무 깊습니다.'},400)
            except TrustPolicyError:
                return self.json_response({'error':'장소의 출처를 확인할 수 없어 코스 추천을 중단했습니다. 운영자가 출처 자료와 확인 기준을 검토한 뒤 다시 시도해 주세요.','code':'trust_policy_unavailable'},503)
            except (ValueError,KeyError,TypeError) as exc:
                return self.json_response({'error':str(exc)},400)
            except Exception:
                return self.json_response({'error':'실행 실패. 데이터와 모델 경로를 점검하세요.'},500)

        def serve_post(self, body):
            if self.path=='/api/agent/plan':return self.json_response(run_agent(ROOT,body,learned_search=False))
            if self.path=='/api/guide-search':
                if set(body)-{'query','region'} or body.get('region','all')!='all':
                    raise ValueError('제주 전체의 공식 관광지 소개 검색어를 입력해 주세요.')
                get_model_evaluation(ROOT)
                return self.json_response(search_assistant(ROOT,body.get('query',''),limit=5,include_route_restricted=True))
            if self.path=='/api/chat':return self.json_response(chat_reply(ROOT,body,learned_search=False))
            if self.path=='/api/tourism':return self.json_response(search_tourism(ROOT,body,learned=False))
            if self.path=='/api/route-geometry':return self.json_response(route_geometry(ROOT,body))
            if self.path=='/api/discover':
                return self.json_response(discovery_recommend(ROOT,body,learned=False))
            if self.path=='/api/plan-destinations':
                return self.json_response(plan_destinations(ROOT,body))
            return self.json_response({'error':'지원하지 않는 경로'},404)

        def log_message(self,fmt,*args):
            print(f'[local] {fmt % args}',flush=True)

    class CenterServer(ThreadingHTTPServer):
        daemon_threads=True
        request_queue_size=16
        def __init__(self,*args,**kwargs):
            self.work_slots = BoundedSemaphore(8)
            self.connections = BoundedSemaphore(48)
            super().__init__(*args, **kwargs)

        def process_request(self, request, client_address):
            if not self.connections.acquire(blocking=False):
                try:
                    request.settimeout(0.25)
                    request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                except OSError:
                    pass
                finally:
                    self.shutdown_request(request)
                return
            request.settimeout(15)
            try:
                super().process_request(request, client_address)
            except Exception:
                self.connections.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                self.connections.release()
    server=CenterServer(('127.0.0.1',port),Handler)
    print(f'Local UI: http://127.0.0.1:{port}  종료: Ctrl+C',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
