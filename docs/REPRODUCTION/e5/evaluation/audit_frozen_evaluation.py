"""Read-only audit of frozen semantic fixtures; no model scores are loaded."""
import hashlib
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent
read=lambda name:json.loads((BASE/name).read_text(encoding='utf-8'))
receipt=read('freeze_receipt.json')
for name,expected in receipt['files_sha256'].items():
    actual=hashlib.sha256((BASE/name).read_bytes()).hexdigest()
    assert actual==expected,('frozen file changed',name)
parts=read('source_partitions.json')
rows=parts['rows'];by_id={r['id']:r for r in rows}
assert len(rows)==len(by_id)==62
assert [sum(r['partition']==p for r in rows) for p in ['train','dev','holdout']]==[40,10,12]
ids=set();counts={}
for split,supported,unsupported in [('dev',12,6),('holdout',24,12)]:
    data=read(split+'_queries.json');cases=data['cases']
    assert data['not_training_data'] and data['not_observed_user_queries']
    assert data['candidate_scores_viewed_before_freeze'] is False
    assert sum(c['kind']=='supported' for c in cases)==supported
    assert sum(c['kind']=='unsupported' for c in cases)==unsupported
    for case in cases:
        assert case['id'] not in ids;ids.add(case['id'])
        assert case['partition']==split and isinstance(case['query'],str) and 0<len(case['query'])<=160
        if case['kind']=='supported':
            assert by_id[case['anchor_id']]['partition']==split
            assert case['anchor_id'] in case['relevant_ids']
            assert all(i in by_id for i in case['relevant_ids'])
            assert case['anchor_name'].replace(' ','') not in case['query'].replace(' ','')
            for evidence in case['evidence']:
                source=by_id[evidence['id']]
                assert evidence['text'] in source['summary']
                assert evidence['source_url']==source['source_url']
        else:assert case['relevant_ids']==[] and case['evidence']==[]
    counts[split]={'supported':supported,'unsupported':unsupported}
print(json.dumps({'pass':True,'score_blind_fixture_audit':True,'cases':len(ids),
                  'counts':counts,'files_sha256':receipt['files_sha256']},ensure_ascii=True))
