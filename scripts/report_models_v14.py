"""Build the v14 model comparison from saved observed-data evaluation artifacts."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
def reduction(old,new):return 100*(1-new/old)
def table(headers,rows):
    return ['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(str(v) for v in row)+' |' for row in rows]
def main():
    a=read('models_audience/audience_metrics.json');b=read('models_mobility/mobility_metrics.json')
    av,at=a['validation'],a['test'];bv,bt=b['validation'],b['test']
    source=read('docs/모델개선_v14/출처_최신파일확인.json');checks=read('docs/모델개선_v14/검증결과_v14.json')
    rows=[['소비 검증 MAE',f"{av['baseline']['mae_share']*100:.6f} pp",f"{av['model']['mae_share']*100:.6f} pp",f"{reduction(av['baseline']['mae_share'],av['model']['mae_share']):.4f}%"],
          ['소비 테스트 MAE',f"{at['baseline']['mae_share']*100:.6f} pp",f"{at['model']['mae_share']*100:.6f} pp",f"{reduction(at['baseline']['mae_share'],at['model']['mae_share']):.4f}%"],
          ['승차 검증 MAE',f"{bv['baseline']['mae_per_hour']:.4f} 명/시간",f"{bv['model']['mae_per_hour']:.4f} 명/시간",f"{reduction(bv['baseline']['mae_per_hour'],bv['model']['mae_per_hour']):.4f}%"],
          ['승차 테스트 MAE',f"{bt['baseline']['mae_per_hour']:.4f} 명/시간",f"{bt['model']['mae_per_hour']:.4f} 명/시간",f"{reduction(bt['baseline']['mae_per_hour'],bt['model']['mae_per_hour']):.4f}%"],
          ['승차 테스트 구간 WAPE',f"{bt['baseline']['wape_bucket_counts']*100:.4f}%",f"{bt['model']['wape_bucket_counts']*100:.4f}%",'절대오차 비율'],
          ['승차 테스트 RMSE',f"{bt['baseline']['rmse_per_hour']:.4f} 명/시간",f"{bt['model']['rmse_per_hour']:.4f} 명/시간",'큰 오차를 더 크게 반영']]
    summary={'version':14,'checked_date_kst':'2026-11-01','service_real_sources_only':True,
       'audience':{'selected':a['selection']['selected'],'config':a['selection']['config'],'source':a['source'],'period':a['observation_period'],'split':a['split'],'test':at,'mae_reduction_percent':reduction(at['baseline']['mae_share'],at['model']['mae_share'])},
       'mobility':{'selected':b['serving_selection']['selected_serving_model'],'source_sha256':b['source_sha256'],'period':b['observation_period'],'split':b['split'],'test':bt,'mae_reduction_percent':reduction(bt['baseline']['mae_per_hour'],bt['model']['mae_per_hour'])},'verification':checks,'sources':source,
       'evaluation_note':'Configuration was selected using validation only. The test periods were already reported in v13; results are retrospective, not a new external holdout. All compared models within a task use the same fitting scope.'}
    lines=['# 제주 길벗 v14 실제 데이터 모델 개선 결과','', '기준일 2026년 11월 1일. 저장된 모델 평가 JSON을 읽어 생성한 보고서입니다. 가상 장소·합성 관측치를 서비스와 실자료 성능에 사용하지 않습니다.','',
       '## 실제 서비스 변경','',
       '- 합성 코스 선택과 체험용 모델카드를 제거했습니다. POST /api/recommend는 410으로 차단합니다.',
       '- 서버 시작 시 합성 CSV 검사·자동 학습·가상 예제 요청을 읽지 않습니다.',
       '- 소비 모델은 먹거리의 집단별 8업종 구성비·업종 예시에, 승차 모델은 내 여행의 과거 시간대 비교에 실제 연결됩니다.',
       '- 실제 장소 일정은 선택한 장소의 시간·추정 이동비 조건 탐색입니다. 소비·승차 모형을 관광객 인기 또는 방문순서 정답으로 사용하지 않습니다.',
       '- 이전 실험 파일은 개발 이력으로 보존하며 서버의 서비스 모델·성능 목록에서 제외합니다.','',
       '## 데이터 출처와 최신 파일 확인','',
       '[대회 공식 공고](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge)의 허브·센터 데이터 활용 및 센터 CPU 실행 조건을 확인했습니다. 제공처는 제주빅데이터센터, 배포 플랫폼은 제주데이터허브입니다. 2026-11-01 현재 공개 CSV를 다시 읽어 기존 원본과 SHA256이 같음을 확인했으며 새 자료로 가장하지 않습니다.','']
    for item in source['datasets']:
        lines.extend([f"- [{item['title']}]({item['page_url']}) · 원본 `{item['local_path']}` · SHA256 `{item['local_sha256']}`"])
    lines.extend(['',f"소비: {a['observation_period']['start']}~{a['observation_period']['end']}의 90개월, 2집단×8업종=1,440개 구성비 셀. 원문 28,255행 중 3,466행을 성별 합산하고 월·집단의 8업종 내 이용건수로 정규화합니다.",f"승차: {b['observation_period']['start']}~{b['observation_period']['end']}의 672일, 일반 승차권 유형 4,704개 일자·시간구간 셀. 이용자 유형 일반은 도민·관광객 구분이 아닙니다.",
       '','512의 메타데이터 표시기간과 실제 CSV 기간이 달라 모델에는 CSV에서 확인한 기간을 기록했습니다. 두 자료는 과거 집계이며 실시간 혼잡·현재 소비를 검증한 자료가 아닙니다.','',
       '## 모델과 비교 절차','',
       f"소비: 최근 12개월, 반감기 6개월 가중, 월 Fourier 2차와 Ridge alpha 10의 다중출력 구성비 회귀입니다. 고정한 {a['selection']['candidate_count']}개 구성을 검증 MAE로 비교하고 설정을 고정했습니다. 음수 구성비를 방지하고 8업종 합을 1로 정규화합니다.",
       '소비 검증은 2018-01~2022-06(54개월) 적합 후 2022-07~2023-12(18개월) 평가입니다. 테스트는 선택을 고정한 뒤 신규·평균·계절·최근가중평균 모두 2018-01~2023-12(72개월)에 적합하고 2024-01~2025-06(18개월)을 평가합니다. 기존 v13 소비 코드도 테스트는 72개월 적합이었습니다.',
       '승차: 시간대별 요일 상호작용, 연중 sin/cos와 주말 계절 상호작용에 반감기 90일 가중·Huber 손실·Ridge 규제100을 적용합니다. 검증만으로 104개 구성을 비교했습니다.',
       '승차의 신규·기준·기존 Ridge 모두 최초 430일(2023-12-25~2025-02-26)에 적합해 검증 2025-02-27~06-27과 테스트 2025-06-28~10-26을 평가합니다. 각 평가구간은 121일·847개 관측입니다.',
       '선택이 끝난 운영 모델은 소비 전체90개월, 승차 전체672일로 각각 다시 적합해 저장했습니다. 런타임과 재학습 모두 Python 표준 라이브러리만 사용합니다.',
       '**테스트 기간은 v13에서도 공개 평가한 과거 구간입니다. 이번 구성 선택에는 쓰지 않았고 결과 확인 후 재튜닝하지 않았습니다. 새 외부 검증 데이터에서 확인한 성과로 표현하지 않습니다.**','',
       '## 오차 비교',''])
    lines.extend(table(['평가 항목','평균 기준','개선 모델','해석 또는 MAE 감소'],rows))
    lines.extend(['','MAE는 평균 절대오차입니다. 소비 0.426111pp는 업종 비중을 평균 약0.426퍼센트포인트 틀렸다는 뜻입니다. 99.57% 정확도라는 뜻이 아닙니다. WAPE는 관측 구간 인원 합 대비 절대오차 합의 비율이고 RMSE는 큰 오차에 더 민감합니다.',
       f"승차 구간 인원 MAE는 {bt['baseline']['mae_bucket_count']:.4f}→{bt['model']['mae_bucket_count']:.4f}명입니다. 검증 RMSE는 {bv['baseline']['rmse_per_hour']:.4f}→{bv['model']['rmse_per_hour']:.4f}로 소폭 증가했습니다. 따라서 모든 지표가 개선됐다고 주장하지 않습니다.",
       '', '## 최근 자료 반영 효과와 계절성 효과','',
       f"소비의 같은 최근 가중 평균 비교는 테스트 MAE {at['recent_weighted_mean_ablation']['mae_share']*100:.6f}pp, 계절 Ridge는 {at['model']['mae_share']*100:.6f}pp입니다. 계절 성분의 추가 감소는 {reduction(at['recent_weighted_mean_ablation']['mae_share'],at['model']['mae_share']):.4f}%입니다. 전체 {reduction(at['baseline']['mae_share'],at['model']['mae_share']):.4f}% 개선의 대부분은 오래된 전체평균 대신 최근 분포를 반영한 효과입니다.",
       '', '## 소비 집단·업종별 테스트 오차',''])
    lines.extend(table(['집단','기준 MAE(pp)','개선 MAE(pp)'],[[label,f"{at['baseline']['by_audience'][key]['mae_share']*100:.6f}",f"{at['model']['by_audience'][key]['mae_share']*100:.6f}"] for key,label in [('resident','제주도민'),('tourist','내국인 참고 집단')]]))
    lines.append('')
    lines.extend(table(['업종','기준 MAE(pp)','개선 MAE(pp)'],[[key,f"{at['baseline']['by_category'][key]['mae_share']*100:.6f}",f"{value['mae_share']*100:.6f}"] for key,value in at['model']['by_category'].items()]))
    lines.extend(['',f"소비 셀 절대오차의 경험적90백분위는 {at['model']['p90_absolute_error_percentage_points']:.6f}pp, 최대는 {at['model']['max_absolute_error_percentage_points']:.6f}pp입니다. 이는 예측구간·신뢰구간이 아닙니다.",
       '', '승차 시간구간·요일별 상세는 `models_mobility/mobility_metrics.json`의 `test.by_bucket`, `test.by_weekday`에 모두 보존합니다. 평균 개선과 개별 구간의 개선 여부를 구분해 확인할 수 있습니다.',
       '', '## 검증과 남은 범위','',
       f"Python {checks['python_tests']}개, UI {checks['ui_test_files']}개 파일, JavaScript 문법 {checks['javascript_syntax_files']}개, 로컬 API {checks['local_api_requests']}요청 및 페이지 {len(checks['pages'])}개 검사를 통과했습니다. API 호출 전후 모델·DB 해시는 같았습니다. 실제 사용자 GPS는 요청하지 않았습니다.",
       '브라우저 시각 검토는 Computer Use가 현재 URL을 신뢰할 수준으로 확인하지 못해 중단했습니다. API 및 실제 성능 JSON을 넣은 모의 DOM 표시는 검증했으며 실제 브라우저 시각 검토 완료로 보고하지 않습니다.',
       '최신 관측 이후의 예측 정확도, 점포 인기·현재 영업, 관광 코스 만족도, 센터 최소사양 실측은 이번 검증에 포함되지 않습니다. GPS·수동 위치의 실제 일정 출발점 연결과 실제 장소 자동 선택은 별도 남은 개발입니다.',
       '', '## 재현과 원본 보존','',
       '기본 실행: `run_center.cmd`. 검사: `runtime/python.exe dev.py check`, `runtime/python.exe dev.py test`. 학습을 의도적으로 다시 할 때 `runtime/python.exe scripts/train_audience.py`, `runtime/python.exe scripts/train_mobility.py`를 사용합니다. 이 명령은 운영 모델을 갱신합니다. 보고서만 다시 생성하려면 `runtime/python.exe scripts/report_models_v14.py`를 사용합니다.',
       'v13 모델·오차·선택 고정 기록은 `development_support/model_v14/`, 원래 코드 보존본은 `development_support/change_v14/source_v13_unchanged.zip`입니다. 원래 `TRANSFER_MANIFEST.json`은 v13 이전본 증거로 유지하고 현재 변경본 검사는 `SERVICE_MANIFEST_v14.json`을 사용합니다. 원래 이전본 비교는 `dev.py check --original-transfer`로 하며 승인된 변경은 차이로 표시됩니다.',''])
    out=ROOT/'docs/모델개선_v14';out.mkdir(exist_ok=True)
    (out/'성능요약_v14.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'모델성능_결과보고.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'report':'docs/모델개선_v14/모델성능_결과보고.md','audience_mae_pp':at['model']['mae_share']*100,'audience_reduction':summary['audience']['mae_reduction_percent'],'mobility_mae':bt['model']['mae_per_hour'],'mobility_reduction':summary['mobility']['mae_reduction_percent']},ensure_ascii=False))
if __name__=='__main__':main()
