# Privacy and Data Handling

cyberbody 不包含遥测、广告 SDK 或自建分析服务，但它必须处理桌面截图和任务文本才能工作。使用前请理解以下数据流。

## 数据清单

| Data | Where it goes | Retention |
| --- | --- | --- |
| 自然语言任务 | 原生模式发送到 Computer API；双模型模式发送到视觉与操作 API；本地会话日志 | 本地默认 7 天；API 侧取决于所选服务商 |
| 目标窗口截图 | 原生模式发送到 Computer API；双模型模式仅发送到视觉 API；本地会话目录 | 本地默认 7 天 |
| 结构化界面描述 | 操作 API；仅保留摘要到最近内存历史 | 任务结束时释放 |
| 动作、风险分类和状态 | 本地 JSONL；视觉风险预检接收必要动作信息和标注截图 | 本地默认 7 天 |
| API 密钥 | 角色专用环境变量或 Windows Credential Manager | 直到环境结束或用户删除凭据 |
| 窗口标题、PID、尺寸和 DPI | 本地会话元数据；必要的截图上下文 | 本地默认 7 天 |

## 不会收集的内容

- 不上传整个桌面，只捕获当前授权窗口的可见客户区或同进程授权对话框。
- 不使用 UI Automation 控件树、浏览器 DOM、剪贴板历史或文件系统内容识别界面。
- 不记录模型隐藏推理。
- 不把 API 密钥写入项目配置、会话日志或命令行参数。
- 不包含项目自建遥测、崩溃上报或用户分析服务。

## 本地存储

默认位置：

```text
%LOCALAPPDATA%\cyberbody\config.json
%LOCALAPPDATA%\cyberbody\sessions\<session-id>
```

会话包含原始截图，因此可能含有姓名、邮件、账号信息或其他敏感内容。文件仅依赖当前 Windows 用户目录权限，没有额外应用层加密。不要在共享账号、同步盘或不可信设备上保留会话。

cyberbody 在启动时和每 24 小时清理超过保留期的会话。默认保留 7 天，可以在配置文件允许范围内调整。界面支持清除全部会话和导出当前会话 ZIP；导出的 ZIP 不加密，需由用户安全保管。

## API 密钥

Computer、视觉与操作密钥相互独立，读取优先级：

1. 当前进程的 `CYBERBODY_COMPUTER_API_KEY` / `CYBERBODY_VISION_API_KEY` / `CYBERBODY_ACTION_API_KEY`；
2. OpenAI 默认地址可回退到 `OPENAI_API_KEY`；
3. Windows Credential Manager 中按角色和 API 地址摘要隔离的 `cyberbody/ComputerAPI/<摘要>` / `cyberbody/VisionAPI/<摘要>` / `cyberbody/ActionAPI/<摘要>`；
4. OpenAI 默认地址可回退到旧版 `cyberbody/OpenAI` 条目。

第三方凭据不会自动从一个接口角色或 API 地址复用到另一个；修改地址后必须重新录入，避免把某个服务商的密钥发送给不同端点。`OPENAI_API_KEY` 和旧版凭据只在 OpenAI 默认地址回退使用。不要把真实密钥写进 `.env` 并提交。仓库的 `.env.example` 只包含空占位符。日志脱敏会替换常见 API 密钥、Bearer 令牌和敏感字段，但不应把脱敏当作提交真实秘密的许可。

## 第三方处理

原生模式把目标窗口截图、任务、动作结果和标注风险预览发送到 Computer 接口，并使用 Responses 会话标识保持上下文。双模型模式把截图和标注预览发送到视觉接口；操作接口只接收用户任务、界面文字与坐标 JSON 和最近动作历史。接口可以属于不同服务商，其数据处理、保留和区域能力取决于账户、组织设置和适用条款。发布者无法替你配置这些控制，也不会承诺第三方未明确保证的保留行为。

使用项目前请查看：

- [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)
- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses)
- [OpenAI Computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)
- [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/)

## 降低暴露的建议

- 先使用项目自带测试窗口，不要直接绑定邮箱、网银或生产后台。
- 关闭无关通知和可能覆盖目标窗口的弹窗。
- 任务中不要粘贴密码、Cookie、一次性验证码或完整 API 密钥。
- 结束后在面板中清除会话，并单独删除已导出的 ZIP。
- 高风险环境使用隔离虚拟机和专用测试账号。
- 提交 Issue 前仅复制最小错误信息，不上传原始会话包。

## 仓库发布前扫描

维护者可运行：

```powershell
.\.venv\Scripts\python.exe scripts\privacy_audit.py
```

该扫描检查高置信度 API 密钥、GitHub/AWS 令牌、私钥头和个人主目录路径。它不能证明仓库绝对没有隐私信息，发布前仍应人工检查 Git 历史、图片、ZIP 和 Release 附件。
