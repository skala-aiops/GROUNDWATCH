"""최초 Docker 볼륨에 제공된 학습 결과를 복원합니다. 재학습은 하지 않습니다."""
from pathlib import Path
import hashlib
import json
import tempfile
import zipfile


def ensure_bundle(root=Path('serving_app/models/groundwater'), seed=Path('data/groundwater/bundle.zip')):
    root, seed = Path(root), Path(seed)
    if (root/'trained/manifest.json').is_file() or not seed.is_file():
        return
    expected = json.loads(seed.with_suffix('.json').read_text())['sha256']
    if hashlib.sha256(seed.read_bytes()).hexdigest() != expected:
        raise RuntimeError('지하수 모델 묶음의 체크섬이 다릅니다. bundle.zip을 다시 확인하세요.')
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(seed) as archive:
            for member in archive.infolist():
                target = (stage/member.filename).resolve()
                if not target.is_relative_to(stage.resolve()):
                    raise ValueError('모델 묶음에 허용되지 않은 경로가 있습니다.')
            archive.extractall(stage)
        manifest = json.loads((stage/'trained/manifest.json').read_text())
        if len(manifest['stations']) != 25:
            raise ValueError('25개 구의 모델 묶음이 필요합니다.')
        for folder in ('prepared', 'trained'):
            if (root/folder).exists():
                raise RuntimeError(f'{root/folder}에 불완전한 파일이 있습니다. 별도 보존 후 재실행하세요.')
        for folder in ('prepared', 'trained'):
            (stage/folder).rename(root/folder)
