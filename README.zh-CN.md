# BilibiliHarvest

一个面向 Windows + Chrome 的 B 站字幕采集工作流工具：

- 桌面端：后台本地 API 服务 + 系统托盘
- 浏览器扩展：唯一主界面，负责首次向导、批量操作、NotebookLM 推送
- 本地资料库：字幕统一写入 `archive_root/<标题>_<BV>/text/`

## 快速开始

1. 安装 Python 3.12
2. 在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

3. 在 Chrome 中加载 `browser_extension/`
4. 打开扩展 `dashboard.html`
5. 按向导完成：
   - 扫描桌面端
   - 自动配对
   - 设置本地资料库目录
   - 可选登录 NotebookLM

## 架构

- 桌面端默认以托盘模式启动，不主动弹主窗口
- 点击托盘菜单可：
  - 打开扩展控制台
  - 显示诊断窗口
  - 退出程序
- 扩展 `dashboard` 负责：
  - 添加任务
  - 启动批处理
  - 保存到本地资料库
  - 推送到 NotebookLM

## 存储路径

项目目录中不再生成 `outputs/`。

- 运行配置：
  - `config/runtime.json`
- 批次快照：
  - `config/batches/<batch_id>/state.json`
- 失败诊断：
  - `config/batches/<batch_id>/failed.json`
- 临时字幕缓存：
  - `config/tmp/<batch_id>/`
- 本地资料库默认目录：
  - `%USERPROFILE%\\Documents\\BilibiliHarvest Library`

本地资料库结构：

- `<archive_root>/<safe_title>_<BV>/text/*.srt|*.txt|*.md`

## 主要能力

- 优先抓取 B 站现成字幕轨道
- 无轨道时自动降级到 Whisper ASR
- 支持单视频、分P、收藏夹、合集、列表、主页投稿
- Chrome 扩展当前页一键发送
- 处理完成后一键：
  - 保存到本地资料库
  - 推送到 NotebookLM

## 本地 API

扩展通过本地 HTTP 服务访问桌面端。

公开工作流相关接口：

- `GET /v1/pairing/info`
- `POST /v1/pairing/claim`
- `GET /v1/config`
- `PATCH /v1/config`
- `POST /v1/window/show`
- `GET /v1/health`
- `POST /v1/tasks/add`
- `POST /v1/tasks/add_prefetched`
- `POST /v1/tasks/bulk_add`
- `GET /v1/tasks`
- `GET /v1/batch/status`
- `POST /v1/batch/start`
- `POST /v1/batch/stop`

## 安全说明

- 不要提交 `config/runtime.json`
- 不要提交 `cookies.txt`
- 不要提交 `config/batches/` 和 `config/tmp/`
- 本地 API token 会在首次启动时自动生成随机值

## 诊断

```powershell
py -3.12 scripts\launcher.py --doctor
```

如需显示桌面诊断窗口：

```powershell
py -3.12 scripts\launcher.py --show-window
```

## 导出为公开仓库快照

如果你要避开当前私有仓库历史，建议导出一个干净快照再推到公开仓库：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_public_repo.ps1
```

## 许可证

MIT
