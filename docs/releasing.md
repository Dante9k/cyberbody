# Release Guide

本指南用于维护者发布 cyberbody Windows x64 便携版本。

## 1. 准备版本

1. 更新 `src/cyberbody/__init__.py` 中的版本号。
2. 把 `CHANGELOG.md` 的 `Unreleased` 内容移动到带日期的新版本标题。
3. 确认 README 中的支持范围、模型和已知限制仍然准确。
4. 确认仓库没有本地会话、截图、ZIP、证书或密钥。

## 2. 运行发布门禁

```powershell
.\scripts\quality.ps1
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m pip_audit
```

所有 lint、格式、类型、安全、测试、覆盖率和隐私检查必须通过。依赖审计结果需要人工确认可利用性，不应无说明地忽略漏洞。

## 3. 构建便携包

```powershell
.\scripts\build.ps1
```

先退出所有正在运行的 cyberbody 进程。Windows 会锁定已加载的 DLL/PYD，构建脚本会因此主动停止，而不会强制删除正在使用的成品目录。

输出：

```text
dist\cyberbody\cyberbody.exe
dist\cyberbody-Windows-x64.zip
dist\cyberbody-Windows-x64.zip.sha256
```

构建目录不得直接提交到 Git。Release 只上传 ZIP 和 SHA-256 文件。

## 4. 干净环境验收

至少在一个未安装 Python 的 Windows 10 22H2/Windows 11 x64 环境验证：

- 双击启动和 `start/status/stop` 命令；
- 普通权限测试窗口绑定；
- 100%、125%、150%、200% 缩放；
- 多显示器和负坐标；
- API 密钥录入、任务执行、确认、紧急停止；
- 会话留存、导出、清除和过期清理；
- SmartScreen/杀毒软件提示是否与发布说明一致。

不得用真实邮箱、支付账号或生产后台做发布验收。

## 5. 创建标签

```powershell
git tag -s v0.1.0 -m "cyberbody v0.1.0"
git push origin v0.1.0
```

推送 `v*` 标签会触发 GitHub Release 工作流，重新执行质量门禁、构建便携包并创建带自动发行说明的 Release。没有签名密钥时可以使用普通 annotated tag，但应在维护说明中记录。

## 6. 发布后

- 从 Release 下载 ZIP 并核对 SHA-256。
- 再次执行一次空闲启动、状态查询和停止。
- 检查 Release 页面没有内部路径、日志或工作流临时文件。
- 创建下一版本的 `Unreleased` 章节。

## 代码签名

0.1 版本不包含商业代码签名。不要声称“已验证发布者”。未来引入签名时，证书和密码必须存放在 GitHub Environments/Secrets 或受控签名服务中，绝不提交到仓库。
