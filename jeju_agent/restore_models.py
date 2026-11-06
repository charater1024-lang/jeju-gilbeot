"""Rebuild the v27 production models locally from the frozen source CSVs."""

import hashlib
import json
import math
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from . import audience_model, dining_model
from .audience_v23 import PROFILE_DIR, SOURCE_FILE
from .model_portfolio import RELATIVE as EVALUATION_FILE
from .quality_v23 import operating_evaluation
from scripts.experiment_audience_v23 import selection_stage, test_stage


MODEL_FILES = {
    'models_audience': ('audience_model.json', 'audience_metrics.json'),
    'models_dining': ('dining_model.json', 'dining_metrics.json'),
    PROFILE_DIR: ('protocol.json', 'selection.json', 'result.json', 'serving_profile.json'),
}
SOURCES = (SOURCE_FILE, dining_model.SOURCE_RELATIVE)


def _validate_release(root):
    evaluated = operating_evaluation(root)
    approved = next(row for row in evaluated['models'] if row['id'] == 'dining_detail')
    metrics = dining_model.predict_dining(root, limit=1)['metrics']
    result = metrics['within_tolerance'][str(approved['fixed_tolerance'])]
    if (result['within'] != approved['metric']['hits']
            or result['total'] != approved['metric']['total']
            or not math.isclose(metrics['mae_percentage_points'], approved['error']['mae'], abs_tol=1e-6)):
        raise ValueError('복원한 1047 모델의 고정 평가가 v27 검증 결과와 다릅니다.')


def restore_models(root):
    """Validate source bytes, build missing model bundles, and keep valid existing bundles."""
    root = Path(root).resolve()
    manifest = json.loads((root / 'SERVICE_MANIFEST_v27.json').read_text(encoding='utf-8'))
    receipts = {entry['path']: entry for entry in manifest['files']}
    verified_sources = {}
    for relative in SOURCES:
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(f'모델 복원 원자료를 먼저 확보해 주세요. {relative}')
        contents = source.read_bytes()
        receipt = receipts[relative]
        if len(contents) != receipt['bytes'] or hashlib.sha256(contents).hexdigest() != receipt['sha256']:
            raise ValueError(f'v27 원자료의 체크섬이 다릅니다. {relative}')
        verified_sources[relative] = contents

    missing = [relative for relative in MODEL_FILES if not (root / relative).exists()]
    for relative, names in MODEL_FILES.items():
        if relative not in missing and any(not (root / relative / name).is_file() for name in names):
            raise ValueError(f'기존 모델 폴더에 일부 파일이 없습니다. 확인이 필요한 경로 {relative}')
    if not missing:
        _validate_release(root)
        return []

    scratch = root / '.test_tmp'
    scratch.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='restore-models-', dir=scratch) as folder:
        stage = Path(folder)
        for relative, contents in verified_sources.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        shared = [EVALUATION_FILE]
        shared.extend((Path(relative) / name).as_posix()
                      for relative, names in MODEL_FILES.items() if relative not in missing
                      for name in names)
        for relative in shared:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, target)

        if 'models_audience' in missing:
            audience_model.train_audience(stage / SOURCE_FILE, stage / 'models_audience')
        if 'models_dining' in missing:
            dining_model.train_dining(stage / dining_model.SOURCE_RELATIVE, stage / 'models_dining')
        if PROFILE_DIR in missing:
            output = stage / PROFILE_DIR
            output.mkdir(parents=True)
            panels, audit = audience_model.read_panels(stage / SOURCE_FILE)
            selection_stage(audience_model, panels, audit, output)
            test_stage(audience_model, panels, audit, output)
        _validate_release(stage)

        for relative in missing:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                (stage / relative).rename(destination)
            except OSError:
                # A concurrent restoration may have promoted this validated bundle first.
                if not all((destination / name).is_file() for name in MODEL_FILES[relative]):
                    raise
        _validate_release(root)
    return missing
