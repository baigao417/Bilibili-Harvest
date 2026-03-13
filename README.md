# BilibiliHarvest

[English](README.en.md)

一个面向 `Windows + Chrome` 的 B 站字幕采集与知识整理工具。  
它将桌面端收敛为后台本地服务，把浏览器扩展作为唯一主界面，适合“看到视频就顺手沉淀成可检索文本”的使用方式。

## 项目简介

BilibiliHarvest 主要解决三件事：

- 从 B 站视频中优先提取现成字幕轨道
- 在无字幕时自动回退到 Whisper ASR
- 将结果一键沉淀到本地资料库，或推送到 NotebookLM

项目当前主打的是一个轻量但完整的工作流：

- 桌面端：后台 API 服务 + 系统托盘
- 浏览器扩展：唯一用户界面
- 本地资料库：字幕文本统一写入 `archive_root/<标题>_<BV>/text/`

## 适合谁

- 想长期积累 B 站知识素材的人
- 想把视频内容快速转成可搜索文本的人
- 想把字幕继续送去 NotebookLM 做整理、归纳、引用的人
- 希望日常操作尽量都在浏览器里完成的人

## 功能亮点

- 优先抓取 B 站原生字幕轨道，减少不必要的 ASR 成本
- 无轨道时自动降级到 Whisper ASR
- 支持单视频、分 P、收藏夹、合集、列表、主页投稿
- Chrome 扩展当前页一键发送
- 处理完成后可一键：
  - 保存到本地资料库
  - 推送到 NotebookLM
- 项目目录不再生成 `outputs/`，批次状态与临时数据统一写入 `config/`

## 快速开始

1. 安装 Python `3.12`
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

## 推荐使用方式

日常使用建议按下面的流程走：

1. 保持桌面端后台运行
2. 在 Chrome 中打开 B 站视频、合集或列表页
3. 在扩展 dashboard 中添加任务
4. 启动批处理
5. 处理完成后：
   - 保存到本地资料库
   - 或推送到 NotebookLM

## 项目结构

- 桌面端默认以托盘模式启动，不主动弹主窗口
- 托盘菜单可：
  - 打开扩展控制台
  - 显示诊断窗口
  - 退出程序
- 扩展 `dashboard` 负责：
  - 添加任务
  - 启动批处理
  - 保存到本地资料库
  - 推送到 NotebookLM

## 存储路径

项目目录中不再生成运行时 `outputs/` 文件夹。

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

## 本地 API

扩展通过本地 HTTP 服务访问桌面端。

主要工作流接口：

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

## 借鉴与依赖的开源项目

本项目在功能实现、工作流设计或运行时能力上，借鉴或依赖了以下开源项目：

- [`Lanbin07/bili2text`](https://github.com/Lanbin07/bili2text)：本项目的早期能力和基础方向来自该项目，许可证见仓库中的 `LICENSE`
- [`openai/whisper`](https://github.com/openai/whisper)：ASR 转写能力
- [`yt-dlp/yt-dlp`](https://github.com/yt-dlp/yt-dlp)：字幕轨道发现、下载和媒体兜底能力
- [`soimort/you-get`](https://github.com/soimort/you-get)：部分下载链路兼容兜底
- [`fastapi/fastapi`](https://github.com/fastapi/fastapi)：本地 HTTP API 服务
- [`PyQt5`](https://pypi.org/project/PyQt5/)：桌面端 UI 与托盘能力
- [`QDarkStyleSheet`](https://github.com/ColinDuquesnoy/QDarkStyleSheet)：桌面端样式
- [`notebooklm-py`](https://pypi.org/project/notebooklm-py/)：NotebookLM 集成能力

如果你认为这里遗漏了应该注明的来源，欢迎提 Issue 或 PR。

## 常见问题

### 1. 为什么项目里没有 `outputs/`？

因为现在的设计目标是“直接沉淀到本地资料库”，而不是在项目目录里堆积导出文件。

### 2. 可以只用扩展，不开桌面端吗？

不可以。扩展是主界面，但实际处理仍由本地桌面服务完成。

### 3. 是否支持跨平台？

当前以 `Windows + Chrome + Python 3.12` 为正式支持环境。

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

## 许可证

MIT
