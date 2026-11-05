"""Re-download official public file attachments. No credentials or demo keys."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent.parent
DATASETS={780:'jeju_food_registry_780.csv',1047:'hub_1047.csv',1048:'hub_1048.csv',512:'hub_512.csv',561:'hub_561.csv'}

def download(dataset_id,out,include_large=False):
    source=f'https://www.jejudatahub.net/api/data/view?id={dataset_id}'
    headers={'User-Agent':'JejuTravelDataResearch/2.0','Accept':'application/json'}
    with urlopen(Request(source,headers=headers),timeout=30) as response:
        meta=json.load(response)
    candidates=meta.get('dataFile',{}).get('fileInfos',[])
    candidates=[f for f in candidates if f.get('fileName','').lower().endswith('.csv')]
    if dataset_id==780:
        candidates=[f for f in candidates if '인허가일에따른' not in f.get('fileName','')]
    if not candidates:raise ValueError(f'{dataset_id}: 공식 메타데이터에 CSV 첨부가 없습니다.')
    result=[]
    for index,info in enumerate(candidates):
        if info.get('fileSize',0)>100_000_000 and not include_large:
            result.append({'dataset_id':dataset_id,'status':'skipped_large_file','bytes':info['fileSize']});continue
        url=f"https://www.jejudatahub.net/api/file?fileId={info['fileId']}&id={info['id']}"
        name=DATASETS[dataset_id] if index==0 else f'{dataset_id}_{info["id"]}.csv'
        dest=out/name;partial=dest.with_suffix('.part');digest=hashlib.sha256();size=0
        with urlopen(Request(url,headers={'User-Agent':headers['User-Agent']}),timeout=60) as response,partial.open('wb') as f:
            while True:
                chunk=response.read(1024*1024)
                if not chunk:break
                if size==0 and (b'<!doctype html' in chunk[:300].lower() or b'<html' in chunk[:300].lower()):
                    raise ValueError('CSV 대신 HTML 응답을 받았습니다. 로그인 또는 접근 상태를 확인하세요.')
                f.write(chunk);digest.update(chunk);size+=len(chunk)
        if not size or (info.get('fileSize') and size!=info['fileSize']):
            raise ValueError('공식 메타데이터와 파일 크기가 일치하지 않습니다. 부분 파일을 확인하세요.')
        partial.replace(dest)
        result.append({'dataset_id':dataset_id,'title':meta['title'],'path':str(dest),'source_url':url,'metadata_url':source,
                       'bytes':size,'sha256':digest.hexdigest(),'status':'downloaded'})
        snapshot={k:meta.get(k) for k in ['id','title','description','startDate','endDate','updateAt','dataFile']}
        (out/f'metadata_{dataset_id}.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser(description='공식 제주 파일 데이터 재취득')
    p.add_argument('--ids',nargs='+',type=int,default=[780,1047,1048,512],choices=list(DATASETS))
    p.add_argument('--output',type=Path,default=ROOT/'data_raw'/'hub'/'refresh')
    p.add_argument('--include-large',action='store_true')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);records=[]
    for ident in a.ids:
        try: records.extend(download(ident,a.output,a.include_large))
        except Exception as exc:records.append({'dataset_id':ident,'status':'failed','error':str(exc)})
    (a.output/'download_log.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
