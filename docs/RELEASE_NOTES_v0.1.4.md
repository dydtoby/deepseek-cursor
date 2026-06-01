## DeepSeek Cursor Proxy v0.1.4

### 新功能

- **Cloudflare Tunnel** 作为默认公网隧道（更适合国内网络环境）
  - TryCloudflare 快速隧道
  - 命名隧道与 AI Gateway 配置
  - 构建时捆绑 `cloudflared`（下载失败时可运行时自动获取）
- 多隧道提供商架构：`ngrok`、`cloudflare`、`frp`
- GUI 向导与仪表盘按提供商显示对应配置项
- 中英文 i18n 更新

### 下载

| 文件 | 说明 |
|------|------|
| `DeepSeekCursorProxy-v0.1.4-Setup.exe` | Windows 安装程序 |
| `DeepSeekCursorProxy-v0.1.4-portable-windows-amd64.zip` | Windows 便携版 |
| `DeepSeekCursorProxy-v0.1.4-portable-linux-amd64.zip` | Linux 便携版（若 CI 构建成功） |
| `SHA256SUMS.txt` | 校验和 |

### 升级说明

- 已有 `config.yaml` 的用户可在 **高级设置** 中切换隧道提供商
- 默认提供商已改为 `cloudflare`；仍可使用 ngrok（需 authtoken）
