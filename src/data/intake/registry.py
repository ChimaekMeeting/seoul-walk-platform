"""
src/data/intake/registry.py
src/data/registry.yaml(데이터 적재 계약)을 읽고 조회하는 유틸리티.

registry.yaml은 "팀이 이 데이터는 이렇게 쓰기로 승인했다"는 계약 파일이며,
intake inspector는 이 파일의 내용을 그대로 보여줄 뿐 layer/score/profile을
스스로 확정하지 않는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

DEFAULT_REGISTRY_PATH = Path("src/data/registry.yaml")


class RegistryUnavailableError(Exception):
    """PyYAML이 설치되어 있지 않아 registry.yaml을 읽을 수 없을 때 발생합니다."""


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    """
    registry.yaml을 읽어 dict로 반환합니다.

    파일이 없으면 빈 datasets로 취급합니다. PyYAML이 설치되어 있지 않으면
    RegistryUnavailableError를 발생시킵니다(호출부에서 친절한 메시지로 안내).
    """
    try:
        import yaml
    except ImportError as exc:
        raise RegistryUnavailableError(
            "PyYAML이 설치되어 있지 않습니다. `poetry add pyyaml` 후 다시 실행하세요."
        ) from exc

    if not path.exists():
        return {"datasets": {}}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("datasets", {})
    return data


def _read_header_comment(path: Path) -> str:
    """
    registry.yaml 맨 앞의 주석/공백 블록(approved, score_effect 의미 설명 등)을 그대로 보존하기 위해 읽어둡니다.
    """
    if not path.exists():
        return ""

    header_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.strip() == "" or line.lstrip().startswith("#"):
            header_lines.append(line)
        else:
            break
    return "".join(header_lines)


def save_registry(registry: dict[str, Any], path: Path = DEFAULT_REGISTRY_PATH) -> None:
    """
    registry dict를 path에 YAML로 저장합니다.

    파일 맨 앞에 있던 주석 블록(데이터 계약서 설명)은 그대로 유지한 채 datasets만 다시 씁니다.
    PyYAML이 설치되어 있지 않으면 RegistryUnavailableError를 발생시킵니다.
    """
    try:
        import yaml
    except ImportError as exc:
        raise RegistryUnavailableError(
            "PyYAML이 설치되어 있지 않습니다. `poetry add pyyaml` 후 다시 실행하세요."
        ) from exc

    header = _read_header_comment(path)
    body = yaml.safe_dump(registry, allow_unicode=True, sort_keys=False)
    path.write_text(header + body, encoding="utf-8")


def find_dataset_by_file(registry: dict[str, Any], filename: str) -> tuple[Optional[str], Optional[dict]]:
    """
    registry["datasets"] 중 file명이 filename과 일치하는 항목을 찾습니다.

    일치하는 항목이 없으면 (None, None)을 반환합니다.
    """
    for key, dataset in (registry.get("datasets") or {}).items():
        if dataset.get("file") == filename:
            return key, dataset
    return None, None
