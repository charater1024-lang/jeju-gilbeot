"""Source-pinned, calendar-only historical temperature guidance on offline CPU."""
from functools import lru_cache
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re

CONFIG_PATH = 'models_climate/config.json'
CONFIG_SHA256 = '910c2e902756989cc4125a85eb7605152489b356689ab007c8deef62597db4ab'
LIMITATIONS = [
    '2000-01-01~2021-10-31 관측 자료로 검증한 과거 계절 참고입니다. 현재·미래 날짜의 날씨 예보가 아닙니다.',
    '범위는 과거 일평균기온 분포의 10~90백분위 추정입니다. 하루 최저·최고기온이나 평균의 신뢰구간이 아닙니다.',
    '제주·고산·성산·서귀포 관측지점의 값입니다. 모든 관광지의 국지 기온을 뜻하지 않습니다.',
    '2021년 1~10월 시험에서 범위의 실제 관측 포함률은 68.8%였고 기온을 평균 1.18℃ 낮게 추정했습니다. 최근 기후로 보정한 결과가 아닙니다.',
    '강수량은 원본에 없어 비·야외 안전·운항 여부를 판단하지 않습니다. 여행 직전 최신 예보를 별도로 확인하세요.',
]


class ClimateDataError(RuntimeError):
    """A source or adopted model is missing or changed; never invent a result."""


def _verified(root, relative, digest, maximum=20_000_000):
    base = Path(root).resolve()
    path = (base / relative).resolve()
    try:
        if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size > maximum:
            raise ClimateDataError('기후 자료 파일을 확인할 수 없습니다.')
        content = path.read_bytes()
    except OSError as exc:
        raise ClimateDataError('기후 자료 파일을 읽을 수 없습니다.') from exc
    if not re.fullmatch(r'[0-9a-f]{64}', digest or '') or hashlib.sha256(content).hexdigest() != digest:
        raise ClimateDataError('기후 자료의 SHA-256이 검증된 원본과 다릅니다.')
    return content


def _json(content):
    def bad_constant(_):
        raise ValueError('non-finite JSON')
    return json.loads(content.decode('utf-8'), parse_constant=bad_constant)


@lru_cache(maxsize=2)
def _parsed(config_content, model_content):
    from .climate_features import load_model_value
    config = _json(config_content)
    model = load_model_value(_json(model_content))
    if config.get('deployment_allowed') is not True or model.get('deployment_status') != 'adoptable':
        raise ClimateDataError('기후 모델이 사전 채택 기준을 통과하지 않았습니다.')
    return config, model


def _assets(root):
    try:
        config_content = _verified(root, CONFIG_PATH, CONFIG_SHA256, 100_000)
        config = _json(config_content)
        model_spec = config['assets']['model']
        model_content = _verified(root, model_spec['path'], model_spec['sha256'])
        for spec in [config['assets']['evaluation'], config['assets']['source_manifest'], config['assets']['runtime'], *config['source_files']]:
            _verified(root, spec['path'], spec['sha256'])
        return _parsed(config_content, model_content)
    except ClimateDataError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError, ImportError) as exc:
        raise ClimateDataError('검증된 기후 모델·출처 자료를 확인해 주세요.') from exc


def _public(config):
    return {
        'schema_version': 1, 'available': True, 'ml_applied': True,
        'stations': config['stations'], 'reference_period': config['reference_period'],
        'source': config['source'], 'model': config['public_model'],
        'default_request': {'month': 4, 'day': 15, 'station': 'jeju'},
        'limitations': list(LIMITATIONS), 'current_forecast': False,
        'rainfall_available': False, 'llm_used': False, 'runtime': 'offline_stdlib_cpu',
    }


def climate_status(root):
    config, _ = _assets(root)
    return _public(config)


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(label + '은 정수로 선택해 주세요.')
    if isinstance(value, str) and not re.fullmatch(r'[0-9]{1,2}', value):
        raise ValueError(label + '은 정수로 선택해 주세요.')
    return int(value)


def climate_reference(root, month, day, station='jeju'):
    month, day = _integer(month, '월'), _integer(day, '일')
    try:
        date(2000, month, day)
    except (ValueError, TypeError) as exc:
        raise ValueError('달력에 있는 월·일을 선택해 주세요. 2월 29일도 선택할 수 있습니다.') from exc
    config, model = _assets(root)
    from .climate_features import predict
    if station not in [s['id'] for s in config['stations']]:
        raise ValueError('제주·고산·성산·서귀포 중 관측지점을 선택해 주세요.')
    estimates = [predict(model, s['id'], month, day) for s in config['stations']]
    seasonality = [predict(model, station, m, 15) for m in range(1, 13)]
    for result in estimates + seasonality:
        if result.get('available') is not True or not all(
            isinstance(result[k], (float, int)) and not isinstance(result[k], bool) and math.isfinite(result[k])
            for k in ('point_c', 'lower_c', 'upper_c')
        ) or result['lower_c'] > result['upper_c']:
            raise ClimateDataError('기후 추정값을 확인할 수 없습니다.')
    return dict(_public(config), requested={'month': month, 'day': day, 'station': station},
                selected=next(r for r in estimates if r['station'] == station),
                estimates=estimates, seasonality=seasonality)
