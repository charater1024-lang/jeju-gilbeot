"""Download fixed public safetensors encoder assets with resumable transfers."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.request import Request,urlopen

BASE=Path(__file__).resolve().parent/'semantic'
NAMES=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json',
       'special_tokens_map.json','sentencepiece.bpe.model','README.md']

def revision(repo):
    for attempt in range(6):
        try:
            with urlopen('https://huggingface.co/api/models/'+repo+'?expand[]=sha',timeout=90) as response:
                raw=response.read(8192)
            found=re.search(rb'"sha"\s*:\s*"([a-f0-9]{40})"',raw)
            if not found:raise ValueError('official revision missing')
            return found.group(1).decode()
        except Exception:
            if attempt==5:raise
            time.sleep(1)

def fetch(repo,rev,name,folder):
    dest=folder/name
    if dest.is_file() and dest.stat().st_size:
        return name,hashlib.sha256(dest.read_bytes()).hexdigest(),dest.stat().st_size
    part=dest.with_suffix(dest.suffix+'.part')
    for attempt in range(10):
        offset=part.stat().st_size if part.exists() else 0
        headers={'User-Agent':'JejuGilbeot-Local-Research/1.0'}
        if offset:headers['Range']=f'bytes={offset}-'
        try:
            with urlopen(Request(f'https://huggingface.co/{repo}/resolve/{rev}/{name}',headers=headers),timeout=120) as response:
                resumed=response.status==206
                if resumed:
                    assert response.headers.get('Content-Range','').startswith(f'bytes {offset}-')
                else:offset=0
                expected=int(response.headers.get('Content-Length','0'))
                count=0
                with part.open('ab' if resumed else 'wb') as target:
                    while block:=response.read(1024*1024):target.write(block);count+=len(block)
                if expected and count!=expected:raise IOError('incomplete transfer')
            part.replace(dest)
            result=(name,hashlib.sha256(dest.read_bytes()).hexdigest(),dest.stat().st_size)
            print(json.dumps({'repo':repo,'file':name,'bytes':result[2]},ensure_ascii=True),flush=True)
            return result
        except Exception as exc:
            print(f'Retrying {repo}/{name}: {type(exc).__name__}',flush=True)
            if attempt==9:raise
            time.sleep(1)

def main():
    for size in ['small','base']:
        repo='intfloat/multilingual-e5-'+size
        folder=BASE/'pretrained'/size;folder.mkdir(parents=True,exist_ok=True)
        receipt=BASE/(size+'_download.json')
        if receipt.exists():rev=json.loads(receipt.read_text(encoding='utf-8'))['revision']
        else:
            rev=revision(repo)
            receipt.write_text(json.dumps({'repo':repo,'revision':rev,'source':'https://huggingface.co/'+repo,'license':'MIT'},indent=2),encoding='utf-8')
        results={}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(fetch,repo,rev,name,folder) for name in NAMES]
            for future in as_completed(futures):
                name,digest,size_bytes=future.result();results[name]={'sha256':digest,'bytes':size_bytes}
        (BASE/(size+'_asset_hashes.json')).write_text(json.dumps(results,indent=2),encoding='utf-8')

if __name__=='__main__':main()
