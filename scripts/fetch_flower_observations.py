"""Retired entry point: API-key-dependent bloom prediction is out of scope."""
import json

def main(argv=None):
    print(json.dumps({'status':'excluded','code':'bloom_prediction_excluded','network_called':False,
                      'message':'사용자 요청으로 인증키 기반 개화 예측과 수집 도구를 개발 범위에서 제외했습니다. 꽃·기온 비교와 7일 예보는 계속 사용할 수 있습니다.'},ensure_ascii=False))
    return 2

if __name__=='__main__':raise SystemExit(main())
