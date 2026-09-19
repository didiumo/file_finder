# file_finder —— 局域网文件索引与整理工具

> 类 Everything 的局域网文件索引服务：多线程并发扫描网络共享目录，建立 SQLite 全文索引；
> Web 端（Vue 3）以虚拟滚动列表提供毫秒级搜索 / 浏览 / 预览，并支持「收藏 = 保留清单 →
> 整理收集到本地 → 清理其余内容」的完整整理流水线。
>
> GitHub：https://github.com/didiumo/file_finder

## 功能特性

- **多线程扫描**：8 工作线程并行 `scandir`+`stat` 遍历局域网共享路径（网络 IO 密集场景吞吐优先），
  异步消费者批量写库（db_v2 `execute_many`，每批 2000 条），增量模式对比 `size/mtime` 只更新变更项。
- **毫秒级搜索**：FTS5 trigram 全文索引（任意子串、大小写不敏感、≥3 字符生效），
  短词自动回退 `LIKE`；配合覆盖索引 + 游标分页，深翻页不重扫 `OFFSET`。
- **文件夹参与搜索 + 正则匹配**：目录与文件同样可被搜索（everything 风格）；`.*` 开关开启
  正则模式后，输入正则表达式匹配文件名 / 路径（Python `re` 层过滤 + 内存分页，无效正则友好报错）。
- **类型过滤（含文件夹）**：类型下拉支持「📁 文件夹」——只显示目录（`ext=__dirs__` → `is_dir=1`；
  收藏页同参，目录收藏快照 `ext=''`）；其余为扩展名多值过滤（图片/视频/音频/文本/JSON/日志/代码/配置/压缩包/数据库/程序库），搜索与收藏页通用。
- **目录范围搜索**：在「文件系统」中选中任一文件夹可一键进入「在此目录搜索」——
  搜索范围限定为该目录及其整个子树（`prefix` 参数），everything 的“进入文件夹搜索”体验。
- **四视图 Web 端**：小图 / 中图 / 大图缩略图 + 表格视图；虚拟滚动只渲染可视区 ± 缓冲页，
  滚动时按页游标加载、远离可视区自动释放页缓存（上限 16 页），107k 文件列表流畅滚动。
  表格视图带列标题（名称/类型/大小/修改时间/路径），**点击列头排序**（升/降，名称/类型/大小/时间/路径
  均可排），**列宽可拖拽**（localStorage 持久化），行与表头列宽严格对齐。
- **文件系统浏览（类资源管理器）**：独立「文件系统」页签，面包屑导航实时浏览扫描根内的目录
  结构（`os.scandir` 按需读盘，**不触发、不依赖全量索引扫描**），目录优先排序，双击进入子目录、
  双击文件下载；未索引的新文件标注「未索引」。
- **侧边预览**：文本（TXT/MD/JSON/日志/代码，BOM/UTF-8/GBK 探测，截断保护）、
  图片（Pillow 生成 WebP 缩略图缓存）、视频（HTTP Range 断点流）。压缩包 / DLL / 程序库不预览，仅提供下载。
  面板宽度可拖拽拉伸（280~720px），也可一键关闭。
- **收藏 = 保留清单**：收藏独立快照（磁盘文件丢失仍保留记录并标记「丢失」）；
  显式删除文件会同时取消收藏，防止误删保留内容。
- **整理收集流水线**：`plan`（只读统计：待复制体积 / 待删除体积 / 释放空间）→ 确认后 `run`。
  复制收藏到 `data/collected/`，删除收藏之外的全部内容（收藏目录子树整体豁免），自底向上移除空目录，
  完成后自动增量重扫受影响根。**安全护栏：没有任何收藏时拒绝执行清理**（收藏即保留清单）。
- **后台任务 + 实时进度**：task 插件任务状态机 + SSE 事件流，前端任务栏展示进度。
- **回收站（软删除）**：删除的文件/目录先移入根目录下 `.ff_trash/`（保留相对路径结构，
  同名冲突自动追加 `~<时间戳>`），数据库标记 `trashed` 并从普通搜索/收藏中隐藏；「回收站」
  页签可**恢复**（移回原位，目标已存在时报错并跳过该条）或**彻底删除 / 清空**（才真正从磁盘
  移除并从数据库删除）；增量扫描跳过回收站条目，原位置出现同名新文件时旧条目自动「复活」
  （取消 trashed 标记）。**确认策略：移入回收站不弹确认（高频操作），回收站内再次删除与
  清空必须二次确认（不可恢复）。**
- **多选 + 右键菜单**：表格/卡片视图支持 **Ctrl/Shift 多选** 与 **拉框多选**（空白处拖拽框选，
  与可视区已渲染元素求交，跨页选择在内存中累积）；选中后状态栏出现批量按钮（收藏 / 移入回收站；
  回收站页为恢复 / 彻底删除），支持 **Delete 键**快速删除；右键菜单提供预览 / 收藏 / 下载 /
  移入回收站（回收站页为恢复 / 彻底删除 / 清空），右键未选中的项会自动先单选该项。

## 快速开始

### 依赖

- Python ≥ 3.12（SQLite ≥ 3.42 以支持 FTS5 trigram）
- Node.js ≥ 18（仅构建前端需要）
- 运行于 py-lite-server 框架（子服务规范见仓库根 `AGENTS.md`）

### 启动

```powershell
# 1. 构建前端（进入 services/file_finder/client）
cd client
npm install
npm run build        # 产物输出到 services/file_finder/dist

# 2. 启动框架（在仓库根目录）
..\..\venv\Scripts\python.exe  ..\..\main.py
```

启动后访问 `http://localhost:<port>/ui/file_finder/`（端口取 `config/settings.yaml`，
默认 8000；如被占用可临时改为 8010 等）。

### 后端测试（E2E）

需先启动服务，且库中已有至少一个可扫描根目录（沙箱可用 `test/make_sandbox.py` 重建）：

```powershell
venv\Scripts\python.exe services\file_finder\test\make_sandbox.py
venv\Scripts\python.exe -m pytest services\file_finder\test\test_e2e.py
```

### 扫描根目录

扫描根在 `server/config.yaml` 的 `roots` 中配置（首次启动自动注册），也可在 Web 端
「设置 → 扫描根目录管理」中增删 / 启停 / 触发扫描：

```yaml
roots:
  - "\\\\Desktop-lt9c0uj\\d\\MJRelease\\SimulatorApp_Data\\mj"
```

## 目录结构

```
services/file_finder/
├── server/
│   ├── entry.py              # 子服务入口（start(ctx)）
│   ├── config.yaml           # 扫描根、并发数、预览/缩略图参数
│   ├── routers/api_router.py # REST API（/api/file_finder）
│   └── logic/
│       ├── indexer_logic.py  # 索引引擎：并发遍历 / 增量对比 / FTS 同步与自愈
│       ├── search_logic.py   # 搜索 / 排序 / 游标分页 / 删除
│       ├── favorite_logic.py # 收藏快照
│       ├── preview_logic.py  # 文本/图片/视频预览与缩略图
│       ├── collection_logic.py # 整理收集流水线
│       └── common.py         # 参数校验等公共逻辑
├── client/                   # Vue 3 + Vite 前端工程（npm run build → ../dist）
├── test/                     # E2E 测试与沙箱构建脚本
├── data/                     # SQLite 库 / 缩略图缓存 / 收集目录（gitignore）
└── docs/设计文档.md           # 详细设计说明
```

## API 概览

| 分组 | 端点 | 说明 |
|---|---|---|
| 根目录 | `GET/POST /roots`、`DELETE /roots/{id}`、`POST /roots/{id}/enable` | 增删查、启停 |
| 扫描 | `POST /roots/{id}/scan` | `mode=full\|incremental`，返回 task_id |
| 搜索 | `GET /search` | `q/root_id/ext/size/date/fav_only/sort/order/page/page_size/after_*`，返回 `next_cursor` |
| 文件 | `GET/DELETE /files/{id}`、`POST /files/batch-delete` | 详情、删除（移入回收站，同步取消收藏） |
| 回收站 | `GET /trash/list`、`POST /trash/restore`、`POST /trash/purge`、`POST /trash/empty` | 列表 / 恢复 / 彻底删除（二次确认）/ 清空（二次确认） |
| 收藏 | `GET /favorites`、`POST /favorites/toggle`、`DELETE /favorites/{id}`、`POST /favorites/prune-missing` | 列表 / 切换 / 移除 / 清理失效 |
| 预览 | `GET /files/{id}/preview\|thumb\|download\|preview-info` | 文本 / 图片 / 视频 / 下载 |
| 任务 | `GET /tasks`、`GET /tasks/{id}/events`(SSE)、`POST /tasks/{id}/cancel` | 后台任务与进度 |
| 统计 | `GET /stats` | 各根目录文件数 / 体积 / 收藏数 |
| 整理 | `POST /collect/plan`、`POST /collect/run` | 计划（只读）/ 执行（需 `confirm=true`） |

## 常见问题

- **FTS 索引损坏**：启动时会自动探测（行数一致性 + `MATCH` 探活），异常时自动
  DROP 重建虚表 / 触发器并回填（107k 文件约 1.1s），无需人工干预。
- **搜索无结果**：确认关键词 ≥ 3 字符（trigram 限制）；1~2 字符走 `LIKE` 子串匹配。
- **端口被占用**：修改仓库根 `config/settings.yaml` 的端口后重启。
- **删除后"重启又恢复"**：删除 = 物理移动到 `.ff_trash` + 标记 `trashed`，两件事都成功才算删除。
  若移动失败（文件被占用 / 网络共享瞬时不可写 / 权限不足），后端不会标记，前端**保留该条目并明确
  提示失败原因**，避免"删了却还在"的错觉。若确认删除时列表立即移除了、重启后却重现，说明**服务被
  重复实例运行**（8000 端口被旧实例占用，新实例未接管）——请先彻底停止所有 `python main.py`
  进程再启动，务必使用项目 `venv` 环境（`venv\Scripts\python.exe main.py`）。
- **删除瞬间白屏 / 翻页出现空白卡片**：已实现链式补位局部刷新——删除点页剔除被删项后，后续已加载页
  逐页前移补位（不重建列表、不闪烁），链尾缺口保留现有数据渲染并后台重拉补齐；滚动跟随改为同步更新
  （不依赖 requestAnimationFrame，避免部分环境下可视区不随滚动刷新）。
