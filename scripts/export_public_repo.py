#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "RELEASING.md",
    "SECURITY.md",
    "pyproject.toml",
    "uv.lock",
}
PUBLIC_DIRECTORIES = {".github", "docs", "examples", "scripts", "src", "tests"}


def source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    files = []
    for item in result.stdout.splitlines():
        relative = Path(item)
        is_root_file = relative.name in ROOT_FILES and len(relative.parts) == 1
        is_public_directory = (
            bool(relative.parts) and relative.parts[0] in PUBLIC_DIRECTORIES
        )
        if is_root_file or is_public_directory:
            files.append(relative)
        else:
            raise RuntimeError(f"文件未列入公开清单：{relative}")
    return sorted(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出不含原仓库历史的公开源码目录")
    parser.add_argument("destination", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    destination = args.destination.resolve()
    if destination.exists():
        raise RuntimeError("目标目录已存在")
    if destination.is_relative_to(ROOT):
        raise RuntimeError("目标目录不能位于项目内部")

    files = source_files()
    destination.mkdir(parents=True)
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)

    print(f"公开源码已导出：{destination}")
    print(f"文件数量：{len(files)}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"公开源码导出失败：{error}", file=sys.stderr)
        raise SystemExit(1) from error
