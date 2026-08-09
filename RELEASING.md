# 发布流程

正式发布只从 GitHub Actions 的 `publish.yml` 工作流执行，不在开发机保存 PyPI
长期 Token。

## 首次配置

1. 在 PyPI 注册并验证账号，启用双因素认证。
2. 从原工作区导出无历史、按清单控制的源码：
   `python scripts/export_public_repo.py /安全临时目录/agent-webview`。
3. 在独立公开仓库中启用 GitHub environment `pypi`，并限制为受保护标签。
4. 在 PyPI 的 Publishing 页面创建 Pending publisher：
   - PyPI project name：`agent-webview`
   - GitHub repository owner：公开仓库所属账号或组织
   - GitHub repository name：`agent-webview`
   - Workflow name：`publish.yml`
   - Environment name：`pypi`
5. 首次发布前，先确认默认分支的 CI 全部通过，再创建版本标签和 GitHub
   Release。首次上传由 Pending Publisher 自动创建 PyPI 项目。

## 每次发布

1. 更新 `src/agent_webview/__init__.py` 中的版本和 `CHANGELOG.md`。
2. 执行 `python scripts/release_check.py`。
3. 提交变更并创建与版本一致的标签，例如 `v0.1.0`。
4. 在 GitHub 创建 Release。发布工作流会重新检查、构建并上传 PyPI。
5. 在全新环境执行 `pip install agent-webview==0.1.0` 和启动冒烟测试。

PyPI 上的版本不可覆盖。发布失败时修复问题并提升版本号，不能复用已上传版本。
