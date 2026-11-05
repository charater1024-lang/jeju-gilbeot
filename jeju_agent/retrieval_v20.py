"""Portable lexical retrieval ensembles over original Jeju source records.

Scores are ranking values, never probabilities, popularity or current access.
This module has no machine-learning package dependency at service time.
"""
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata
import datetime as dt

DOMAINS = {'tourism', 'guide', 'food', 'travel'}
STOP = {'제주','제주도','관광지','여행지','명소','관광','여행','장소','곳','곳을','추천','추천해줘','추천해주세요','찾아줘','찾아주세요','찾아','검색','알려줘','알려주세요','보여줘','보여주세요','정보','소개','싶어','싶어요','있는','만한','주세요','좀','볼','수','보고','찾고','보는','이야기'}
UNSUPPORTED = ('실시간','지금영업','현재영업','영업중','영업시간','예약가능','주차가능','충전가능','수영가능','통행가능','혼잡','제외','빼고','말고','없는','아닌','가까운','근처','반경')

def compact(text):
    return ''.join(re.findall(r'[가-힣a-z0-9]+', unicodedata.normalize('NFKC',str(text or '')).casefold()))

def words(text):
    return re.findall(r'[가-힣a-z0-9]+', unicodedata.normalize('NFKC',str(text or '')).casefold())

def terms(text):
    result=[]
    for word in words(text):
        value=re.sub(r'(?:에서|으로|에게|들을|들은|들이|에는|에서의|은|는|을|를|에|의)$','',word)
        if value in STOP or word in STOP:continue
        if len(value)>1:result.append(value)
    return list(dict.fromkeys(result))

def tokens(text,mode='char'):
    pieces=words(text)
    if mode=='word':return pieces
    grams=['c:'+word[i:i+n] for word in pieces for n in (2,3) for i in range(len(word)-n+1)]
    return grams if mode=='char' else grams+['w:'+word for word in pieces]

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def load_documents(root,domain):
    root=Path(root)
    if domain not in DOMAINS:raise ValueError('지원하지 않는 검색 영역입니다.')
    if domain in {'tourism','guide'}:
        from .tourism_access import approved_places
        from .place_trust import place_trust
        result=[]
        for item in approved_places(root):
            guide=item.get('tourism_guide') or {}
            if domain=='guide' and not place_trust(root,item,purpose='automatic')['automatic_eligible']:continue
            hub=(item.get('cross_source') or {}).get('hub') or {}
            result.append({'id':item['id'],'name':item['name'],'category':item['category'],'address':hub.get('address') or item.get('address') or '',
              'text':guide.get('summary') or '', 'region':item.get('region'),'kind':'attraction','source_platform':'jeju_datahub',
              'source_url':hub.get('source_url'),'source_date':hub.get('source_date'),
              'guide_url':guide.get('source_url'),'guide_date':guide.get('retrieved_at'),'record':item})
        return result
    if domain=='food':
        path=root/'data_reference/discovery.sqlite'
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            return [dict(row,text=row['cuisine'] or '',kind='food') for row in db.execute('SELECT id,name,category,address,region,source_platform,source_url,source_date,cuisine FROM restaurants ORDER BY id')]
    data=json.loads((root/'data_reference/travel_context_v18.json').read_text('utf-8'))
    return [{'id':item['id'],'name':item['name'],'category':str(item.get('known',{}).get('시설유형') or item['kind']),
             'address':str(item.get('known',{}).get('주소') or ''),'text':item['search_text'],'kind':item['kind'],
             'source_platform':item['source_id'],'source_url':item['source_url'],'source_date':item['source_date'],'record':item} for item in data['items']]

class LexicalIndex:
    def __init__(self,documents):
        self.documents=documents
        self.ids={doc['id']:index for index,doc in enumerate(documents)}
        self.fields=[]
        self.channels={}
        for mode in ('char','word','mixed'):
            postings=defaultdict(list);lengths=[];df=Counter()
            for index,doc in enumerate(documents):
                counter=Counter(tokens(' '.join(str(doc.get(key) or '') for key in ('name','category','address','text')),mode))
                lengths.append(sum(counter.values()));df.update(counter.keys())
                for term,count in counter.items():postings[term].append((index,count))
            n=len(documents)
            idf={term:math.log((1+n)/(1+count))+1 for term,count in df.items()}
            norms=[0.0]*n
            for term,entries in postings.items():
                for index,count in entries:norms[index]+=((1+math.log(count))*idf[term])**2
            self.channels[mode]={'postings':postings,'lengths':lengths,'df':df,'idf':idf,'norms':[math.sqrt(x) or 1 for x in norms],'average_length':sum(lengths)/max(1,n)}
        self.fields=[{key:compact(doc.get(key,'')) for key in ('name','category','address','text')} for doc in documents]

    def rank(self,query,config,*,kind=None,region=None,hub_only=False,limit=5):
        requested=compact(query)
        if not requested or any(marker in requested for marker in UNSUPPORTED):return []
        clean=terms(query)
        if not clean:return []
        eligible={i for i,doc in enumerate(self.documents) if (not kind or doc.get('kind')==kind) and (not region or region=='all' or doc.get('region')==region) and (not hub_only or doc.get('source_platform')=='jeju_datahub')}
        mode=config.get('mode','char'); channel=self.channels[mode]
        query_counts=Counter(tokens(' '.join(clean),mode));weights={t:(1+math.log(c))*channel['idf'][t] for t,c in query_counts.items() if t in channel['idf']}
        query_norm=math.sqrt(sum(w*w for w in weights.values())) or 1
        cosine=defaultdict(float);bm25=defaultdict(float)
        k1,b=config.get('k1',1.2),config.get('b',.75);n=len(self.documents)
        for token,weight in weights.items():
            idf_bm=math.log(1+(n-channel['df'][token]+.5)/(channel['df'][token]+.5))
            for index,count in channel['postings'][token]:
                if index not in eligible:continue
                cosine[index]+=(weight/query_norm)*(1+math.log(count))*channel['idf'][token]/channel['norms'][index]
                norm=count+k1*(1-b+b*channel['lengths'][index]/max(1,channel['average_length']))
                bm25[index]+=idf_bm*count*(k1+1)/norm
        scores={}
        method=config['family']
        if method=='tfidf':scores=dict(cosine)
        elif method=='bm25':scores=dict(bm25)
        else:
            rrf=config.get('rrf_k',30)
            for source in (cosine,bm25):
                for rank,(index,_) in enumerate(sorted(source.items(),key=lambda pair:(-pair[1],self.documents[pair[0]]['id'])),1):scores[index]=scores.get(index,0)+1/(rrf+rank)
        for index in list(scores):
            fields=self.fields[index]
            # Anchoring uses actual named/category/address fields, never invented attributes.
            coverage=sum(any(compact(term) in field for field in fields.values()) for term in clean)/len(clean)
            if config.get('coverage_gate',0) and coverage<config['coverage_gate']:
                del scores[index];continue
            strength=config.get('field_boost',0)
            if strength:
                matched=sum(compact(term) in fields['name'] for term in clean)/len(clean)
                category=sum(compact(term) in fields['category'] for term in clean)/len(clean)
                exact=compact(' '.join(clean))==fields['name']
                scores[index]+=strength*(matched+.35*category+float(exact))
        ordered=sorted(scores.items(),key=lambda pair:(-pair[1],self.documents[pair[0]]['name'],self.documents[pair[0]]['id']))
        return [{'id':self.documents[i]['id'],'score':float(score),'name':self.documents[i]['name'],'document_index':i} for i,score in ordered[:limit] if score>0]

def candidate_configs():
    result=[]
    for mode in ('char','word','mixed'):
        result.append({'family':'tfidf','mode':mode})
        for k1,b in ((.8,.3),(1.2,.75),(1.8,.6)):
            result.append({'family':'bm25','mode':mode,'k1':k1,'b':b})
        for boost in (0,.025,.1,.4):
            for gate in (0,.5,1):
                result.append({'family':'rrf','mode':mode,'rrf_k':30,'field_boost':boost,'coverage_gate':gate})
    return result

def _source_stamp(root,domain):
    names={'tourism':['data_reference/tourism.sqlite','data_reference/tourism_guides_v12.json','config/place_trust_policy_v15.json'],
           'guide':['data_reference/tourism.sqlite','data_reference/tourism_guides_v12.json','config/place_trust_policy_v15.json'],
           'food':['data_reference/discovery.sqlite','models_discovery/tfidf_model.json'],
           'travel':['data_reference/travel_context_v18.json','data_raw/hub_v18/BUILD_RECEIPT.json']}[domain]
    return tuple((name,(root/name).stat().st_mtime_ns,(root/name).stat().st_size) for name in names)+(('as_of_kst',dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()),)

@lru_cache(maxsize=8)
def _cached_index(root,domain,receipt_mtime,source_stamp,expected_sha256):
    documents=load_documents(Path(root),domain)
    observed=digest([{k:v for k,v in row.items() if k!='record'} for row in documents])
    if observed!=expected_sha256:raise ValueError('검색모델과 원자료의 동결된 출처 지문이 일치하지 않습니다.')
    return LexicalIndex(documents)

def _selection(root):
    path=root/'models_candidates_v20/retrieval/selection.json'
    artifact=json.loads(path.read_text('utf-8'))
    if artifact.get('selection_sha256')!=digest({k:v for k,v in artifact.items() if k!='selection_sha256'}):raise ValueError('검색모델선정무결성을확인하세요.')
    freeze=json.loads((root/'development_support/retrieval_v20/benchmark_freeze.json').read_text('utf-8'))
    if artifact.get('benchmark_sha256')!=freeze.get('benchmark_sha256'):raise ValueError('검색평가 동결 명세가 일치하지 않습니다.')
    for group in ('domains','production_domains'):
        if set(artifact.get(group,{}))!=DOMAINS:raise ValueError('검색영역 명세를 확인하세요.')
        if any(row.get('selected_config') not in candidate_configs() for row in artifact[group].values()):raise ValueError('검색후보 설정을 확인하세요.')
    return path,artifact

def rank_retrieval(root,query,*,domain='guide',kind=None,region='all',hub_only=False,limit=5):
    """Return source-record identifiers for conservative application adapters."""
    if domain not in DOMAINS:raise ValueError('지원하지 않는 검색 영역입니다.')
    if not isinstance(query,str) or len(query)>160:raise ValueError('검색어는160자이내문자열이어야합니다.')
    if type(limit) is not int or not 1<=limit<=20:raise ValueError('표시개수를확인하세요.')
    root=Path(root)
    path,artifact=_selection(root)
    config=artifact['domains'][domain]['selected_config']
    index=_cached_index(str(root.resolve()),domain,path.stat().st_mtime_ns,_source_stamp(root,domain),artifact['domains'][domain]['corpus_sha256'])
    ranked=index.rank(query,config,kind=kind,region=region,hub_only=hub_only,limit=limit)
    return {'items':[dict(item,source_url=index.documents[item['document_index']].get('source_url'),source_date=index.documents[item['document_index']].get('source_date')) for item in ranked],
            'model':{'algorithm':'portable_lexical_ensemble','config':config,'runtime_llm':False,'quality_scope':'curated_source_grounded_proxy_not_field_accuracy'}}

def rerank_candidates(root,query,records,*,domain='guide',status=None):
    """Reorder the same first five records only, preserving every other record.

    Activation is allowed only by the saved independent promotion receipt.
    Food record groups/distance semantics have not passed this release gate.
    """
    if not isinstance(records,list):raise ValueError('기록 목록을 확인하세요.')
    def finish(items,reason,applied=False):
        if isinstance(status,dict):status.update({'applied':applied,'reason':reason,'domain':domain,'scope':'same_first_five_records_only','runtime_llm':False})
        return items
    if domain not in DOMAINS or not isinstance(query,str) or len(query)>160:
        return finish(records,'invalid_query_or_domain')
    root=Path(root)
    try:
        promotion=json.loads((root/'models_candidates_v20/retrieval/promotion.json').read_text('utf-8'))
        if promotion.get('sha256')!=digest({k:v for k,v in promotion.items() if k!='sha256'}):raise ValueError('promotion_digest')
        if not promotion['domains'].get(domain,{}).get('activate'):return finish(records,'domain_not_promoted')
        path,artifact=_selection(root)
        if promotion['selection_sha256']!=artifact['selection_sha256']:raise ValueError('selection_link')
        config=artifact['production_domains'][domain]['selected_config']
        index=_cached_index(str(root.resolve()),domain,path.stat().st_mtime_ns,_source_stamp(root,domain),artifact['domains'][domain]['corpus_sha256'])
        ranked=index.rank(query,config,limit=len(index.documents))
        if not ranked:return finish(records,'unsupported_or_no_lexical_match')
        positions={row['id']:i for i,row in enumerate(ranked)}
        head=sorted(records[:5],key=lambda row:positions.get(row.get('id'),len(positions)))
        return finish(head+records[5:],'verified_candidate_rerank',head!=records[:5])
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        # Missing, stale or inconsistent artifacts must not interrupt the existing service.
        return finish(records,'receipt_or_source_validation_failed')

def classify_intent(root,text,candidates=None):
    """Portable TF-IDF linear/NB classifier; caller keeps all existing safety gates."""
    if not isinstance(text,str) or not text.strip():return 'clarify'
    text=re.sub(r'\s\s+',' ',text)
    path=Path(root)/'models_candidates_v20/retrieval/intent_model.json'
    model=json.loads(path.read_text('utf-8'))
    receipt=model.pop('sha256',None)
    if receipt!=digest(model):raise ValueError('요청분류모델무결성을확인하세요.')
    vocab=model['vocabulary'];counts=Counter(text[i:i+n] for n in range(model['ngram_range'][0],model['ngram_range'][1]+1) for i in range(max(0,len(text)-n+1)))
    vector={vocab[token]:(1+math.log(count))*model['idf'][vocab[token]] for token,count in counts.items() if token in vocab}
    norm=math.sqrt(sum(value*value for value in vector.values())) or 1
    vector={i:value/norm for i,value in vector.items()}
    if not vector:return 'clarify'
    scores=[intercept+sum(row[i]*value for i,value in vector.items()) for intercept,row in zip(model['intercepts'],model['weights'])]
    allowed=[i for i,label in enumerate(model['classes']) if candidates is None or label in candidates]
    return model['classes'][max(allowed,key=lambda i:scores[i])] if allowed else 'clarify'
