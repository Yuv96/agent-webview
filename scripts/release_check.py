#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "src" / "agent_webview" / "__init__.py"
BANNED_PARTS = {
    ".agent-webview-data",
    ".agent-webview-runtime.json",
    ".coverage",
    ".DS_Store",
    ".env",
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
}
BANNED_SUFFIXES = {".har", ".pem", ".pyc", ".p12", ".storage-state.json"}
REQUIRED_SDIST_FILES = {
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "scripts/release_check.py",
}
REQUIRED_WHEEL_FILES = {
    "agent_webview/__init__.py",
    "agent_webview/cli.py",
    "licenses/LICENSE",
}


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"执行：{' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def project_version() -> str:
    match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']',
        VERSION_FILE.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if not match:
        raise RuntimeError("无法读取项目版本")
    return match.group(1)


def check_git_clean() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise RuntimeError("发布目录存在未提交变更")


def check_tag(version: str) -> None:
    if os.getenv("GITHUB_REF_TYPE") != "tag":
        return
    expected = f"v{version}"
    actual = os.getenv("GITHUB_REF_NAME")
    if actual != expected:
        raise RuntimeError(f"发布标签应为 {expected}，实际为 {actual}")


def check_secrets() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    files = [item for item in listed.stdout.splitlines() if item]
    result = subprocess.run(
        [
            "uv",
            "run",
            "--extra",
            "dev",
            "detect-secrets",
            "scan",
            *files,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    findings = json.loads(result.stdout).get("results", {})
    if findings:
        summary = ", ".join(
            f"{name}({len(items)})" for name, items in sorted(findings.items())
        )
        raise RuntimeError(f"敏感信息扫描未通过：{summary}")


def archive_names(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    with tarfile.open(path, "r:gz") as archive:
        return archive.getnames()


def archive_contents(path: Path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    yield item.filename, archive.read(item)
        return
    with tarfile.open(path, "r:gz") as archive:
        for item in archive.getmembers():
            if item.isfile():
                stream = archive.extractfile(item)
                if stream is not None:
                    yield item.name, stream.read()


def check_artifacts(artifacts: list[Path], root_text: str) -> None:
    if len(artifacts) != 2:
        raise RuntimeError("构建结果必须同时包含一个 wheel 和一个 sdist")
    for artifact in artifacts:
        names = archive_names(artifact)
        required = (
            REQUIRED_WHEEL_FILES
            if artifact.suffix == ".whl"
            else REQUIRED_SDIST_FILES
        )
        missing = {
            expected
            for expected in required
            if not any(name.endswith(expected) for name in names)
        }
        if missing:
            raise RuntimeError(
                f"构建产物缺少必要文件：{', '.join(sorted(missing))}"
            )
        for name in names:
            path = Path(name)
            if BANNED_PARTS.intersection(path.parts):
                raise RuntimeError(f"构建产物包含敏感路径：{name}")
            if any(name.endswith(suffix) for suffix in BANNED_SUFFIXES):
                raise RuntimeError(f"构建产物包含敏感文件：{name}")

        for name, content in archive_contents(artifact):
            private_paths = (
                root_text.encode(),
                b"/" + b"Users" + b"/",
                b"/" + b"Volumes" + b"/",
            )
            if any(value in content for value in private_paths):
                raise RuntimeError(f"构建产物泄露本机路径：{name}")
            if re.search(rb"[A-Za-z]:\\Users\\", content):
                raise RuntimeError(f"构建产物泄露本机路径：{name}")


def clean_install_smoke(wheel: Path, temporary: Path, version: str) -> None:
    environment = temporary / "venv"
    run(["uv", "venv", str(environment), "--python", ">=3.10"])
    python = (
        environment / "Scripts" / "python.exe"
        if os.name == "nt"
        else environment / "bin" / "python"
    )
    run(["uv", "pip", "install", "--python", str(python), str(wheel)])
    run(
        [
            str(python),
            "-c",
            (
                "from agent_webview import __version__; "
                f"assert __version__ == {version!r}"
            ),
        ],
        cwd=temporary,
    )
    run([str(python), "-m", "agent_webview", "--help"], cwd=temporary)
    run(
        [str(python), "-m", "agent_webview", "--print-runtime-file"],
        cwd=temporary,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 agent-webview 发布候选版本")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="开发阶段允许存在未提交变更",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.allow_dirty:
        check_git_clean()

    version = project_version()
    check_tag(version)
    check_secrets()
    run(["uv", "run", "--extra", "dev", "ruff", "check", "src", "tests", "scripts"])
    run(["uv", "run", "--extra", "dev", "mypy"])
    run(
        [
            "uv",
            "run",
            "--extra",
            "dev",
            "pytest",
            "--cov=agent_webview",
            "--cov-report=term",
            "--cov-fail-under=70",
        ]
    )

    with tempfile.TemporaryDirectory(prefix="agent-webview-release-") as name:
        temporary = Path(name)
        distribution = temporary / "dist"
        requirements = temporary / "requirements.txt"
        run(
            [
                "uv",
                "export",
                "--quiet",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--no-hashes",
                "--format",
                "requirements-txt",
                "--output-file",
                str(requirements),
            ]
        )
        run(
            [
                "uv",
                "run",
                "--extra",
                "dev",
                "pip-audit",
                "--requirement",
                str(requirements),
            ]
        )
        run(["uv", "build", "--out-dir", str(distribution)])
        artifacts = sorted(
            path
            for path in distribution.iterdir()
            if path.suffix == ".whl" or path.name.endswith(".tar.gz")
        )
        run(["uv", "run", "--extra", "dev", "twine", "check", *map(str, artifacts)])
        check_artifacts(artifacts, str(ROOT))
        wheel = next(path for path in artifacts if path.suffix == ".whl")
        clean_install_smoke(wheel, temporary, version)

    print(f"发布检查通过：agent-webview {version}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"发布检查失败：{error}", file=sys.stderr)
        raise SystemExit(1) from error
