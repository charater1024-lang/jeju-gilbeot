"""Fetch public operating data from the providers' pinned attachments."""

import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


_HOSTS = {"www.jejudatahub.net", "jejudatahub.net", "www.data.go.kr", "data.go.kr"}
_CHUNK_BYTES = 1024 * 1024


def _check_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in _HOSTS
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443)):
        raise ValueError(f"허용된 공식 HTTPS 다운로드 주소가 아닙니다. {url}")


class _OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _source_path(root, source):
    relative = PurePosixPath(source["local_path"])
    if (len(relative.parts) != 3 or relative.parts[0] != "data_raw"
            or relative.parts[1] not in {"hub", "hub_v18"}
            or relative.suffix != ".csv" or "\\" in relative.name or ":" in relative.name):
        raise ValueError(f"공개 자료의 저장 경로가 올바르지 않습니다. {relative}")
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"저장 경로가 작업 폴더 밖을 가리킵니다. {relative}")
    if (type(source["bytes"]) is not int or source["bytes"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])):
        raise ValueError(f"공개 자료의 파일 명세가 올바르지 않습니다. {relative}")
    _check_url(source["download_url"])
    return path


def _verify_source(path, source):
    if not path.is_file():
        raise ValueError(f"공식 원자료 파일을 찾을 수 없습니다. {source['local_path']}")
    if path.stat().st_size != source["bytes"]:
        raise ValueError(f"파일 크기가 고정 명세와 다릅니다. {source['local_path']}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_CHUNK_BYTES):
            digest.update(chunk)
    if digest.hexdigest() != source["sha256"]:
        raise ValueError(f"SHA-256이 고정 명세와 다릅니다. {source['local_path']}")


def _download_chunks(source, opener, timeout):
    request = Request(source["download_url"], headers={"User-Agent": "JejuGilbeot-Restore/1.0"})
    received = 0
    with opener.open(request, timeout=timeout) as response:
        _check_url(response.geturl())
        while chunk := response.read(_CHUNK_BYTES):
            received += len(chunk)
            if received > source["bytes"]:
                raise ValueError("다운로드 크기가 고정 명세를 초과했습니다.")
            yield chunk


def _install_new(destination, chunks, verify):
    """Verify a sibling temporary file before installing without replacing an existing file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            for chunk in chunks:
                stream.write(chunk)
        verify(temporary)
        try:
            if os.name == "nt":
                temporary.rename(destination)
            else:
                os.link(temporary, destination)
        except FileExistsError:
            verify(destination)
            return False
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _travel_receipt_path(root):
    path = root / "data_raw/hub_v18/SOURCE_MANIFEST.json"
    if not path.resolve().is_relative_to(root):
        raise ValueError("여행 참고 자료 명세의 저장 경로가 작업 폴더 밖을 가리킵니다.")
    return path


def _verify_receipt(candidate, receipt):
    if json.loads(candidate.read_text(encoding="utf-8")) != receipt:
        raise ValueError("기존 여행 참고 자료 명세가 GitHub 작업본의 명세와 다릅니다.")


def _restore_travel_receipt(root, receipt):
    path = _travel_receipt_path(root)
    if path.exists():
        _verify_receipt(path, receipt)
        return
    payload = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _install_new(path, [payload], lambda candidate: _verify_receipt(candidate, receipt))


def _load_config(root):
    config = json.loads((root / "config/restore_sources.json").read_text(encoding="utf-8"))
    if config.get("version") != 1:
        raise ValueError("지원하지 않는 공개 자료 복원 명세 버전입니다.")
    return config


def source_paths(root):
    """List project-relative paths produced by the source restore."""
    root = Path(root).resolve()
    config = _load_config(root)
    files = [_source_path(root, entry) for entry in config["sources"] + config["travel"]["sources"]]
    return tuple(path.relative_to(root).as_posix() for path in [*files, _travel_receipt_path(root)])


def source_problems(root):
    """Check local source bytes and provenance without requesting anything."""
    root = Path(root).resolve()
    config = _load_config(root)
    problems = []
    for source in config["sources"] + config["travel"]["sources"]:
        try:
            _verify_source(_source_path(root, source), source)
        except (OSError, ValueError) as error:
            problems.append(str(error))
    try:
        _verify_receipt(_travel_receipt_path(root), config["travel"])
    except (OSError, ValueError) as error:
        problems.append(f"여행 참고 자료 명세 확인 실패. {error}")
    return problems


def restore_sources(root, *, timeout=60):
    """Restore official raw inputs and return download and reuse counts."""
    root = Path(root).resolve()
    config = _load_config(root)
    travel = config["travel"]
    opener = build_opener(_OfficialRedirects())
    counts = {"downloaded": 0, "reused": 0}
    for source in config["sources"] + travel["sources"]:
        destination = _source_path(root, source)

        def verify(path):
            _verify_source(path, source)

        try:
            if destination.exists():
                verify(destination)
                counts["reused"] += 1
                continue
            downloaded = _install_new(destination, _download_chunks(source, opener, timeout), verify)
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise ValueError(f"{source['id']} 공식 공개 자료를 복원할 수 없습니다. {error}") from error
        counts["downloaded" if downloaded else "reused"] += 1
    _restore_travel_receipt(root, travel)
    return counts
