# GitHub Launch Checklist

这份清单用于第一次公开仓库和 Release。它不会替代代码质量；目标是让访客在几十秒内理解“它是什么、为什么安全、如何验证”。

## 1. 确认名称与账号

项目统一使用全小写品牌名 `cyberbody`：仓库名、Python 包、命令、EXE、本地数据目录和凭据服务保持一致。首次公开前仍需做最后一次实时检查：

- GitHub 仓库名在目标账号或组织下可创建；
- PyPI 名称可用（仅在计划发布 Python 包时需要）；
- 目标市场不存在会造成混淆的商标或同类产品；
- README、Release、截图和社交账号统一使用 **cyberbody for Windows**。

`cyberbody` 也作为通用词出现在论文、音乐和非同类应用中，因此搜索无明显同类项目不代表已完成商标审查。商业发布前应在目标国家或地区做正式检索。项目积累用户后不要频繁改名。

## 2. 仓库 About 设置

推荐描述：

> A supervised, vision-first Windows automation agent powered by OpenAI Computer use — one bound window, visible previews, and human approval for risky actions.

推荐 Topics：

```text
ai-agent
computer-use
desktop-automation
human-in-the-loop
openai-api
pyside6
win32
windows-automation
```

启用 Issues、Discussions 和 **Private vulnerability reporting**。设置 MIT License，并把主分支命名为 `main`。

## 3. 首次推送

本工作区已经初始化为本地 `main` 分支，但没有提交、远程或用户身份配置。用你自己的 GitHub 账号执行：

```powershell
git status
git add .
git commit -m "feat: publish cyberbody 0.1.0"
git remote add origin https://github.com/<owner>/<repository>.git
git push -u origin main
```

提交前再次确认 `git status` 中没有 `.venv`、`build`、`dist`、`.egg-info`、会话截图或 ZIP。

## 4. 分支保护

为 `main` 创建规则：

- Require a pull request before merging；
- Require status checks：`Windows quality gate`、`CodeQL`、`Dependency audit`；
- Require conversation resolution；
- Block force pushes and deletion；
- 维护者也遵守规则。

如果 CodeQL 或 Dependency audit 的定时任务在首次推送前还没有检查名称，先让工作流至少运行一次再配置必需检查。

## 5. 演示素材

高质量演示比功能清单更容易建立信任。录制 30–60 秒 GIF/MP4：

1. 启动项目自带测试窗口；
2. 用十字准星绑定；
3. 输入示例任务；
4. 清楚展示动作高亮、风险确认和紧急停止；
5. 结尾展示验收通过和会话日志。

录制前使用全新的 Windows 测试账号，关闭通知，隐藏任务栏个人信息，确认没有 API 密钥、用户名、文件路径、浏览器标签或真实数据。不要用模拟演示冒充真实运行。

把压缩后的素材放到 `docs/assets/`，并在 README 开头功能介绍后展示。大视频建议使用 GitHub Release 或外部公开视频平台，避免仓库体积膨胀。

## 6. 首个 Release

完成 [releasing.md](releasing.md) 的干净环境验收后：

```powershell
git tag -a v0.1.0 -m "cyberbody v0.1.0"
git push origin v0.1.0
```

标签会触发 Windows Release 工作流。检查 Release 只包含：

- `cyberbody-Windows-x64.zip`；
- `cyberbody-Windows-x64.zip.sha256`；
- 与 `CHANGELOG.md` 一致的发行说明。

Release 标题应明确 Alpha、Windows x64、未签名和不支持管理员/UAC 窗口。

## 7. 发布后的维护节奏

- 用 `good first issue` 标记范围清晰、有测试边界的贡献任务；
- 对重复问题更新 FAQ，而不是只在 Issue 中回答；
- 每个版本维护 CHANGELOG 和可验证哈希；
- 公开展示已知限制和失败案例；
- 不购买 Star、不使用互刷服务，也不夸大安全保证。

长期获得 Star 的核心是可信演示、快速上手、稳定 Release、认真处理 Issue，以及对桌面智能体风险保持诚实。
