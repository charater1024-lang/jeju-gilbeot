"""Fetch only the four already-used, SHA-pinned Hub877 CSVs into research storage.

This submission helper never collects a Hub dataset directory or user credentials.
It does not change original training code or the runtime source verification policy.
"""
import argparse,hashlib,json,shutil,urllib.request
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True,help='Unpacked JejuGilbeot project')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify-only',action='store_true')
    mode.add_argument('--download',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    source=json.loads((root/'models_climate/sources.json').read_text(encoding='utf-8'))['source']
    assert source['dataset_id']==877
    rows=source['files'];assert {r['attachment_id'] for r in rows}=={2596,2597,2598,2599}
    if args.verify_only:
        for r in rows:assert digest(root/'data_raw/hub_climate'/r['file'])==r['sha256'],r['file']
        print(json.dumps({'pass':True,'verified_public_csv_files':4,'network_calls':0}));return
    if args.output is None:parser.error('--download requires --output outside the project')
    out=args.output.resolve()
    if out==root or out.is_relative_to(root):parser.error('Use a separate research output outside the project')
    if out.exists() and any(out.iterdir()):parser.error('Use an empty research output, never overwrite archived results')
    out.mkdir(parents=True,exist_ok=True)
    receipts=[]
    for r in rows:
        parsed=urlsplit(r['url']);q=parse_qs(parsed.query)
        assert parsed.scheme=='https' and parsed.hostname=='www.jejudatahub.net' and parsed.path=='/api/file'
        assert q.get('fileId')==['2220'] and q.get('id')==[str(r['attachment_id'])]
        assert Path(r['file']).name==r['file']
        request=urllib.request.Request(r['url'],headers={'User-Agent':'JejuGilbeot selected-data research reproduction'})
        with urllib.request.urlopen(request,timeout=45) as response:raw=response.read(5000000)
        assert len(raw)==r['bytes'] and hashlib.sha256(raw).hexdigest()==r['sha256'],'Source has changed; do not substitute it into frozen results'
        (out/r['file']).write_bytes(raw)
        receipts.append({'file':r['file'],'source_url':r['url'],'bytes':len(raw),'sha256':r['sha256']})
    for name in ['metadata_877.json','weather_audit.json','physical_quality_audit.json']:
        shutil.copy2(root/'data_raw/hub_climate'/name,out/name)
    (out/'selected_download_receipt.json').write_text(json.dumps({'dataset_id':877,'files':receipts,'scope':'four previously-used source attachments, not a Hub dataset catalogue'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pass':True,'downloaded_public_csv_files':4,'model_or_source_project_modified':False}))
if __name__=='__main__':main()
