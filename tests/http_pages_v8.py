"""Verify direct page URLs and local assets without browser/device permissions."""
import argparse,json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import build_opener,ProxyHandler

def smoke(base,report):
    opener=build_opener(ProxyHandler({}));pages={};count=0
    for path in ['/','/planner','/explore','/chat','/about','/chat/']:
        with opener.open(base+path,timeout=5) as response:
            page=response.read().decode('utf-8');assert response.status==200
        count+=1
        assert 'id="chat-page-host"' not in page
        assert 'data-page="/chat"' not in page
        assert 'href="/chat"' in page
        assert page.index('/page-router.js')<page.index('/app.js')
        assert page.index('/location-service.js')<page.index('/location-context.js')<page.index('/discovery.js')<page.index('/chatbot.js')
        pages[path]=True
    for path in ['/page-router.js','/pages.css','/location-context.js']:
        with opener.open(base+path,timeout=5) as response:assert response.status==200 and response.read()
        count+=1
    for path in ['/not-a-page','/api/not-a-page']:
        try:opener.open(base+path,timeout=5)
        except HTTPError as error:assert error.code==404
        else:raise AssertionError('Unknown paths must remain 404')
        count+=1
    result={'pass':True,'pages':pages,'http_requests':count,'direct_routes_and_assets':True,'unknown_paths_404':True,'real_device_location_requested':False}
    Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:8772');parser.add_argument('--report',default='docs/http_pages_v8.json')
    args=parser.parse_args();print(json.dumps(smoke(args.base_url,args.report)))
