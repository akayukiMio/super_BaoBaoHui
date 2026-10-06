# 视频批量压缩工具 (Video Batch Compressor)

基于 **FFmpeg + H.265/HEVC** 的视频批量压缩工具，用于把大量视频转码压缩以节省存储空间。
项目提供两种形态：**Tkinter 桌面版** 与 **本地网页版**（同一套核心逻辑）。

- 作者：akayukimio
- 版本：v1.2.0

## 功能概览
- CPU 编码 `libx265`、GPU 编码 `hevc_nvenc` / `av1_nvenc`（自动检测可用编码器）
- 质量(CRF/CQ)、编码速度预设、最大分辨率智能缩放、音频码率
- 输出到源目录子文件夹，或自定义输出目录（镜像源文件夹结构）
- 强制压缩高效编码源文件、覆盖已存在输出
- 扫描/多选文件、勾选/全选、进度与速度/ETA、暂停/恢复/停止
- 删除已压缩源文件（移入 Windows 回收站，可恢复）
- 结果/错误/删除会话日志（UTF-8 BOM），配置持久化，明暗主题

## 依赖
- Python 3.8+
- Node.js + npm（仅网页版构建前端时需要）
- FFmpeg（需在系统 PATH 中，GPU 编码需对应版本）

## 目录结构
```
video_compressor/
├── video_compressor.py         # 桌面版（Tkinter，单文件）
├── icon.ico
├── logs/                       # 运行期日志（已 gitignore）
├── .processing_history.json    # 处理历史（含本地绝对路径，已 gitignore，绝不入库）
└── web/
    ├── backend/                # FastAPI 本地后端
    │   ├── core/               # 复用核心逻辑：ffmpeg/worker/history/logger/recycle/fsbrowse/task_manager
    │   ├── main.py             # REST + WebSocket + 托管前端构建产物
    │   ├── requirements.txt
    │   └── .venv/              # 后端虚拟环境（已 gitignore）
    ├── frontend/               # React + TypeScript + Vite + Tailwind + shadcn 风格
    │   └── src/
    ├── run_web.py              # 生产模式启动（单进程、无控制台窗口）
    ├── stop_web.py             # 停止生产服务
    ├── run_dev.py              # 开发模式启动（后端 + vite，两个进程）
    ├── stop_dev.py             # 停止开发服务
    └── make_shortcut.py        # 生成桌面快捷方式（路径自动推导）
```

## 桌面版
```
python video_compressor.py
```

## 网页版（推荐：生产模式，无命令行窗口）
首次准备后端环境：
```
cd web/backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```
构建前端（改过前端代码后需重跑）：
```
cd web/frontend
npm install
npm run build
```
启动：双击桌面快捷方式，或
```
python web/run_web.py        # 后台隐藏启动 + 自动打开浏览器 http://127.0.0.1:8765
python web/stop_web.py       # 停止
```
生成/更新桌面快捷方式：
```
python web/make_shortcut.py
```

### 开发模式（热更新，会占用两个终端窗口）
```
python web/run_dev.py        # 后端 8765 + 前端 vite 5173（/api、/ws 由 vite 代理）
python web/stop_dev.py
```

## 安全说明
- 服务仅监听 `127.0.0.1`，不暴露到局域网。
- `.processing_history.json`、`logs/`、`.venv/`、`node_modules/`、`dist/`、`web/.run/` 均已 `.gitignore` 排除，不会入库。

## 版本与维护
- 语义化版本标签（如 `v1.2.0`）。
- 回退到桌面版基线：`git checkout desktop-baseline`。
- 日常同步：`git add -A && git commit -m "..." && git push`。
