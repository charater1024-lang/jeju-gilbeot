"""Offline editorial summaries based on identified official tourism guide pages."""
from functools import lru_cache
import json,re
from pathlib import Path
from urllib.parse import urlsplit
from .tourism_names import prefer_hub_name

OFFICIAL_HOSTS={'visitjeju.net','www.visitjeju.net','m.visitjeju.net','jejudatahub.net','www.jejudatahub.net','korean.visitkorea.or.kr','english.visitkorea.or.kr'}

@lru_cache(maxsize=4)
def _guides(path,mtime,size):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    rows=data.get('guides',data.get('items',[])) if isinstance(data,dict) else []
    index={}
    for item in rows:
        if not isinstance(item,dict):continue
        ident=item.get('id');summary=item.get('summary');url=item.get('source_url')
        if not isinstance(ident,str) or len(ident)>120 or not isinstance(summary,str) or not 30<=len(summary.strip())<=1600 or not isinstance(url,str):continue
        try:source=urlsplit(url)
        except ValueError:continue
        if source.scheme!='https' or source.hostname not in OFFICIAL_HOSTS or source.username or source.password:continue
        if re.search(r'<\s*(?:script|iframe|style)\b',summary,re.I):continue
        if ident in index:continue
        index[ident]={'id':ident,'summary':summary.strip(),'source_url':url[:2000],'source_name':str(item.get('source_name') or '제주관광공사 비짓제주')[:180],'source_content_id':str(item.get('source_content_id') or '')[:160],'source_title':str(item.get('source_title') or item.get('name') or '')[:180],'retrieved_at':str(item.get('retrieved_at') or data.get('retrieved_at') or '')[:80],'summary_method':str(item.get('summary_method') or 'source_based_editorial_paraphrase')[:100]}
    return index

def guide_for(root,item):
    if not item or item.get('source_overlap_verified') is not True:return None
    path=Path(root)/'data_reference/tourism_guides_v12.json'
    if not path.is_file():return None
    try:
        stat=path.stat();record=_guides(str(path.resolve()),stat.st_mtime_ns,stat.st_size).get(item.get('id'))
    except (ValueError,OSError):return None
    return dict(record) if record else None

def enrich_tourism(root,item):
    result=prefer_hub_name(item)
    if result.get('source_overlap_verified') is not True:return result
    guide=guide_for(root,result);result['tourism_guide_available']=guide is not None
    result['tourism_guide']=guide
    if guide:
        result['map_description']=result.get('map_description',result.get('description') or '')
        result['description']=guide['summary']
        result['description_provenance']='official_tourism_source_editorial_summary_not_training_input'
    return result
