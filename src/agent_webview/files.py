from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def ensure_private_directory(path: Path) -> Path:
    """创建仅当前用户可访问的目录。"""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private(path, 0o700)
    return path


def ensure_private_parent(path: Path) -> Path:
    """只在父目录缺失时创建私有目录。"""
    if path.is_dir():
        return path
    path.mkdir(parents=True, mode=0o700)
    _chmod_private(path, 0o700)
    return path


def write_private_text(path: Path, content: str) -> None:
    """原子写入仅当前用户可读写的文本文件。"""
    ensure_private_parent(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _chmod_private(temporary, 0o600)
        try:
            os.replace(temporary, path)
        except PermissionError:
            # 部分 Windows 策略禁止替换已存在文件。
            path.write_text(content, encoding="utf-8")
        _chmod_private(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    write_private_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2),
    )


def restrict_file_permissions(path: Path) -> None:
    _chmod_private(path, 0o600)


def _chmod_private(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        if os.name != "nt":
            raise
