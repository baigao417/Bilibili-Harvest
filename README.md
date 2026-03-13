# BilibiliHarvest

[English](README.en.md)

一个面向 `Windows + Chrome` 的 B 站内容采集与本地知识整理工具。  
它把桌面端收敛为后台本地服务，把浏览器扩展作为唯一主界面，适合“一键沉淀优质信息源以及一键上传到notebooklm与AI谈论”的日常工作流。

## 项目定位

BilibiliHarvest 主要解决三件事：

- 优先提取 B 站现成字幕轨道
- 在无字幕时自动回退到 Whisper ASR
- 把结果一键保存到本地知识库，或推送到 NotebookLM

如果你平时会把优质视频内容长期保存、整理、检索，那么这个项目就是为这种使用场景设计的。

## 为什么要保存到本地知识库

互联网上很多优质信息并不稳定：

- 视频可能下架
- 字幕可能被修改或消失
- 平台页面结构和可见内容可能变化
- 收藏夹、合集、列表也可能被删除或重组

所以把重要内容尽早保存到本地，会比完全依赖在线平台更安全，也更利于后续检索、归档和二次整理。

## 本地知识库 / Shape of Me 工作流

项目支持把处理结果保存到你自己的本地知识库。这个功能你可以理解为：

- 一个通用的“本地知识库”保存入口
- 也可以按照你自己的命名习惯，把它当作 `Shape of Me` 工作流

保存到本地知识库时，会为每个视频建立一个独立文件夹，并且这个文件夹默认使用视频标题命名。

在这个视频文件夹里，会保存三类内容：

- `video/`：默认优先保存 `1080P` 视频
- `audio/`：同步保存提取后的音频
- `text/`：保存字幕文本，格式可包含 `srt / txt / md`

目录结构如下：

- `<archive_root>/<视频标题>/video/*`
- `<archive_root>/<视频标题>/audio/*`
- `<archive_root>/<视频标题>/text/*.srt|*.txt|*.md`

## 名称可自定义

“保存到本地知识库”这个功能名称支持自定义。

你可以在扩展端配置里修改它的显示名称，例如：

- 本地知识库
- Shape of Me
- 视频资料库
- 素材库
- 私人知识库

这个名称会影响扩展界面里的按钮和提示文案，但不会影响底层处理能力。

## 功能亮点

- 优先抓取 B 站原生字幕轨道，减少不必要的时间等待
- 无轨道时自动降级到 Whisper ASR
- 支持单视频、分 P、收藏夹、合集、列表、主页投稿
- Chrome 扩展当前页一键发送
- 处理完成后可一键：
  - 保存到本地知识库
  - 推送到 NotebookLM

## 适合谁

- 想长期积累 B 站知识素材的人
- 想把视频内容快速转成可搜索文本的人
- 想把字幕继续送去 NotebookLM 做整理、归纳、引用的人

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
   - 设置本地知识库目录
   - 可选自定义知识库名称
   - 可选登录 NotebookLM

## 详细安装步骤（Windows）

如果你是第一次接触这个项目，建议按下面顺序操作：

1. 打开 PowerShell
   - 不要在 Python 交互环境里输入命令
   - 如果你看到命令行前面是 `>>>`，说明你在 Python 里，先输入 `exit()` 退出

2. 进入项目目录

```powershell
cd "你的项目目录"
```

3. 先检查 Python 是否正确

```powershell
py -3.12 -V
```

4. 再检查依赖环境

```powershell
py -3.12 scripts\launcher.py --doctor
```

如果这里看到 `doctor completed: no blocking issues`，说明环境基本正常。

5. 运行一键安装脚本

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

这个脚本会依次完成：

- 安装 Python 依赖
- 运行 doctor 检查
- 创建桌面快捷方式
- 安装开机自启
- 启动桌面端托盘服务

6. 检查是否安装成功

安装成功后，你应该能看到：

- 托盘区出现 `BilibiliHarvest` 图标
- 桌面上出现 `BilibiliHarvest` 快捷方式
- Chrome 扩展可以通过 dashboard 扫描到本地服务

7. 安装扩展

- 打开 Chrome
- 进入扩展管理页面
- 开启“开发者模式”
- 选择“加载已解压的扩展程序”
- 选择项目里的 `browser_extension/` 目录

8. 打开 dashboard 完成首次向导

向导会引导你完成：

- 自动扫描桌面端
- 自动配对
- 设置本地知识库目录
- 自定义本地知识库名称
- 可选登录 NotebookLM

## 如果安装时出错

- 如果 `py -3.12 -V` 失败：
  - 说明 Python 3.12 没装好，先安装 Python 3.12

- 如果 `doctor` 失败：
  - 先根据输出补齐 `ffmpeg / ffprobe / yt-dlp / you-get`

- 如果 `setup_windows.ps1` 直接报 PowerShell 语法错误：
  - 请先确认你拿到的是最新版本
  - 当前项目已经尽量避免 PowerShell 5.1 的中文编码解析问题

- 如果扩展连不上：
  - 确认托盘服务已经启动
  - 再打开 dashboard 重新扫描

## 推荐使用方式

1. 保持桌面端后台运行
2. 在 Chrome 中打开 B 站视频、合集或列表页
3. 在扩展 dashboard 中添加任务
4. 启动批处理
5. 处理完成后：
   - 保存到本地知识库
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
  - 保存到本地知识库
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
- 本地知识库默认目录：
  - `%USERPROFILE%\\Documents\\BilibiliHarvest Library`

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

因为现在的设计目标是“直接沉淀到本地知识库”，而不是在项目目录里堆积运行时导出文件。

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
