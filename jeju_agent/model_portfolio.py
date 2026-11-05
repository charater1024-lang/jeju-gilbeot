"""Read the signed, source-backed evaluation ledger without loading training libraries."""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

RELATIVE='data_reference/model_portfolio_v20.json'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=4)
def _read(path,mtime,size):
    data=json.loads(Path(path).read_text('utf-8'))
    receipt=data.pop('snapshot_sha256',None)
    if not isinstance(receipt,str) or digest(data)!=receipt:
        raise ValueError('모델 평가 명세의 해시를 확인해야 합니다.')
    if data.get('schema_version')!=1 or data.get('service_version')!=20:
        raise ValueError('모델 평가 명세의 버전을 확인해야 합니다.')
    rows=data.get('models')
    if not isinstance(rows,list) or len(rows)!=9 or len({row.get('id') for row in rows})!=9:
        raise ValueError('모델 평가 범위가 올바르지 않습니다.')
    thresholds={'1048':1.0,'1047':.25,'512':20.,'561':20.}
    for row in rows:
        metric=row.get('metric')
        if metric:
            count,denominator,percent=metric.get('hits'),metric.get('total'),metric.get('percent')
            if type(count) is not int or type(denominator) is not int or not 0<=count<=denominator or denominator<1:
                raise ValueError('모델 평가의 정답 수와 분모가 올바르지 않습니다.')
            if isinstance(percent,bool) or not isinstance(percent,(int,float)) or not math.isfinite(percent) or abs(percent-100*count/denominator)>1e-4:
                raise ValueError('모델 평가 비율과 분모가 일치하지 않습니다.')
        ident=row.get('source_id')
        if row.get('type')=='regression' and (ident not in thresholds or row.get('fixed_tolerance')!=thresholds[ident]):
            raise ValueError('고정한 회귀 평가 기준이 바뀌었습니다.')
        if row.get('field_accuracy_proven') is not False:
            raise ValueError('새 현장 평가가 없는 모델의 정확도를 확정할 수 없습니다.')
    if data.get('all_service_models_93_proven') is not False:
        raise ValueError('모든 모델93%를 입증하는 독립 평가가 없습니다.')
    data['snapshot_sha256']=receipt
    return data


def get_model_evaluation(root):
    path=Path(root)/RELATIVE
    info=path.stat()
    return _read(str(path.resolve()),info.st_mtime_ns,info.st_size)
