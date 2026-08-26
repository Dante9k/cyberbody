# Contributing to cyberbody

感谢你愿意改进 cyberbody。桌面操作智能体会直接产生鼠标和键盘事件，因此本项目把安全边界、可复现测试和清晰文档视为功能的一部分。

## 开始之前

- 小改动可以直接提交 Pull Request；较大的行为变更请先创建 Discussion 或 Feature Request。
- 安全漏洞不要提交公开 Issue，请遵循 [SECURITY.md](SECURITY.md)。
- 参与项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 本地环境

开发环境需要 Windows 10 22H2/Windows 11 x64 和 Python 3.12。

```powershell
git clone <your-fork-url>
cd cyberbody
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

不要把 API 密钥写入源码、测试、截图或 Issue。大部分开发和全部单元测试都不需要 API 密钥。

## 开发流程

1. 从最新主分支创建短生命周期分支，例如 `fix/window-boundary`。
2. 为行为变更补充测试；安全策略变更必须包含“允许”和“拒绝”两侧测试。
3. 运行质量门禁：

   ```powershell
   .\scripts\quality.ps1
   ```

4. 如果改动涉及界面操作，再运行确定性测试窗口：

   ```powershell
   .\.venv\Scripts\cyberbody-test-window.exe
   .\.venv\Scripts\cyberbody.exe start
   ```

5. 更新 README、架构文档或 CHANGELOG 中与改动相关的内容。

## 代码规范

- 使用 Python 3.12 类型语法和 `from __future__ import annotations`。
- Ruff 是唯一格式化与 lint 工具；不要手工调整与 Ruff 冲突的格式。
- 公共函数、跨线程回调和安全相关数据结构必须有类型标注。
- 不记录隐藏推理、API 密钥、认证头或未经脱敏的异常载荷。
- Win32 句柄和指针必须声明 `ctypes` 的 `argtypes`/`restype`，避免 x64 截断。
- 不使用 UI Automation 控件树；识别输入只能来自目标窗口可见像素。
- 动作执行前必须重新验证前台窗口、授权关系、截图几何和坐标边界。
- 新的高影响动作默认选择更保守的 `confirm`、`handoff` 或 `deny`。

## 测试要求

Pull Request 至少应保持以下检查通过：

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests scripts cyberbody_entry.py
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts cyberbody_entry.py
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m bandit -q -r src -c pyproject.toml
.\.venv\Scripts\python.exe -m pytest --cov=cyberbody
.\.venv\Scripts\python.exe scripts\privacy_audit.py
```

真实桌面在线测试必须绑定本项目的本地验收窗口或隔离虚拟机。不得在贡献测试中控制个人邮箱、生产账号、真实支付页面或管理员/UAC 窗口。

## Pull Request 清单

- PR 只解决一个清晰问题，标题描述用户可见结果。
- 说明风险、测试方式和截图（如果界面发生变化）。
- 不提交 `.venv`、`dist`、`build`、会话截图、日志或凭据。
- CI 全部通过且没有新增静态检查豁免。
- 任何安全豁免都需要在代码旁解释原因，并由维护者审核。

## 提交信息

推荐使用简洁的命令式提交信息，例如：

```text
fix: reject stale coordinates after window resize
test: cover 150 percent DPI coordinate mapping
docs: document screenshot retention and export
```

## 许可证

提交贡献即表示你同意按照项目的 [MIT License](LICENSE) 发布该贡献。
