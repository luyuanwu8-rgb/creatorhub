# 公众号文章指标 Agent 接入与重构说明

本文面向需要调用或重构 CreatorHub 公众号文章采集能力的 Agent。服务默认监听：

```text
http://127.0.0.1:18765
```

## 1. 功能边界

公众号文章指标链路分为两层：

1. **CreatorHub 数据层**：校验文章链接、读取公开 HTML、保存当前指标、追加时间快照、计算增量并提供本机 HTTP API。
2. **PC 微信视觉层**：在已登录的 PC 微信中打开文章，通过后台窗口截图识别底部指标，再调用 CreatorHub API 写回。

这两层通过 JSON 接口解耦。视觉 Agent 可以替换成其他 OCR 或视觉模型，CreatorHub 的数据库与查询接口无需跟着变化。

## 2. 数据字段

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `read_count` | 阅读量数值；`10万+`按下界保存为 `100000` | `100000` |
| `read_display` | 页面原始显示文本，必须保留 `+` | `10万+` |
| `like_count` | 底部拇指数量 | `273` |
| `share_count` | 底部分享箭头数量 | `214` |
| `collect_count` | 底部红心数量 | `86` |
| `comment_count` | 底部评论数量 | `33` |
| `source` | 采集来源 | `public_page` / `pc_wechat_visual` |

`read_display` 是页面证据，`read_count` 是便于排序和计算的数值。遇到 `10万+` 时，不应把 `100000`解释成精确阅读量。

## 3. Agent 标准调用流程

### 第一步：健康检查

```http
GET /health
```

期望响应：

```json
{"status":"ok"}
```

### 第二步：创建或刷新文章记录

```http
POST /api/wechat/articles/sync
Content-Type: application/json
```

```json
{
  "url": "https://mp.weixin.qq.com/s/ARTICLE_KEY"
}
```

该接口会规范化链接、抓取公开 HTML，并按 URL 复用已有记录。公开页通常能返回标题；登录态指标由后续视觉步骤补齐。响应中的 `id` 是后续写回所需的 `article_id`。

### 第三步：PC 微信视觉采集

视觉 Agent 应执行以下检查：

1. 确认窗口中的文章标题或 URL 与目标文章一致。
2. 读取文章底部左侧的“阅读”文本。
3. 读取底部固定栏中的拇指、分享箭头、红心、评论四项数字。
4. 页面未展示某项时提交 `null`，不要猜值。
5. 保留阅读量原始文本，例如 `10万+`。

现场验证使用的窗口采集方式：

- Windows `user32.dll`：`EnumWindows`、`EnumChildWindows`、`GetWindowRect`；
- Windows `PrintWindow`：后台生成窗口截图，不执行窗口激活；
- `System.Drawing.Bitmap`：保存单张 PNG；
- Codex `view_image` 视觉读取：识别文章标题与底部数字；
- CreatorHub HTTP API：校验并写入 SQLite。

当前视觉采集器位于 CreatorHub 进程之外。重构时建议保持这一边界，避免浏览器或视觉模型异常带倒持续监控服务。

### 第四步：写回视觉指标

```http
POST /api/wechat/articles/{article_id}/metrics
Content-Type: application/json
```

```json
{
  "read_count": 100000,
  "read_display": "10万+",
  "like_count": 273,
  "share_count": 214,
  "collect_count": 86,
  "comment_count": 33
}
```

接口行为：

- 所有数值必须大于或等于零；
- 至少提交一项指标；
- 只覆盖本次明确提交的字段；
- 更新文章当前值；
- 写入一条 `WechatArticleMetricSnapshot`；
- 将来源标记为 `pc_wechat_visual`；
- 返回文章当前值和新快照 ID。

### 第五步：查询当前值与趋势

列出文章：

```http
GET /api/wechat/articles?limit=100
```

查询单篇文章快照与增量：

```http
GET /api/wechat/articles/{article_id}/metrics?limit=200
```

每条快照包含：

```text
read_delta
like_delta
share_delta
collect_delta
comment_delta
```

第一条快照的增量为零；后续快照与上一条有效快照比较。

## 4. Python Agent 调用示例

```python
import requests

BASE_URL = "http://127.0.0.1:18765"
ARTICLE_URL = "https://mp.weixin.qq.com/s/ARTICLE_KEY"

requests.get(f"{BASE_URL}/health", timeout=10).raise_for_status()

article = requests.post(
    f"{BASE_URL}/api/wechat/articles/sync",
    json={"url": ARTICLE_URL},
    timeout=30,
).json()

# visual_metrics 由 PC 微信窗口视觉识别器产生。
visual_metrics = {
    "read_count": 100000,
    "read_display": "10万+",
    "like_count": 273,
    "share_count": 214,
    "collect_count": 86,
    "comment_count": 33,
}

saved = requests.post(
    f"{BASE_URL}/api/wechat/articles/{article['id']}/metrics",
    json=visual_metrics,
    timeout=30,
)
saved.raise_for_status()

series = requests.get(
    f"{BASE_URL}/api/wechat/articles/{article['id']}/metrics",
    timeout=30,
).json()
print(series)
```

## 5. PowerShell 调用示例

```powershell
$base = 'http://127.0.0.1:18765'
$article = Invoke-RestMethod -Method Post `
  -Uri "$base/api/wechat/articles/sync" `
  -ContentType 'application/json; charset=utf-8' `
  -Body (@{url='https://mp.weixin.qq.com/s/ARTICLE_KEY'} | ConvertTo-Json)

$metrics = @{
  read_count = 100000
  read_display = '10万+'
  like_count = 273
  share_count = 214
  collect_count = 86
  comment_count = 33
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "$base/api/wechat/articles/$($article.id)/metrics" `
  -ContentType 'application/json; charset=utf-8' `
  -Body ([Text.Encoding]::UTF8.GetBytes($metrics))
```

## 6. CreatorHub 内部实现

### 代码位置

| 文件 | 职责 |
| --- | --- |
| `app/platforms/wechat_article.py` | URL 规范化、公开 HTML 下载、标题/阅读展示/动态指标解析 |
| `app/models.py` | 当前文章记录与历史快照模型 |
| `app/main.py` | 同步、列表、趋势查询、视觉指标写回接口 |
| `tests/test_wechat_article.py` | URL、动态指标和 `10万+` 下界解析测试 |

### 使用的项目与组件

- **CreatorHub**：主服务与统一 API；
- **FastAPI**：本机 HTTP 路由与参数校验；
- **Pydantic**：请求模型和非负数约束；
- **SQLModel + SQLite**：文章当前值、时间快照和增量查询；
- **Python `urllib.request`**：获取公众号公开 HTML；
- **PC 微信 `Weixin.exe` / `WeChatAppEx.exe`**：提供登录态文章页面；
- **Windows Win32 API + System.Drawing**：无激活后台截图原型；
- **可替换视觉 Agent**：将窗口图像转换为结构化指标 JSON。

### 数据模型

`WechatArticleRecord` 每个规范化 URL 保存一条当前状态：

```text
url + title + 五项当前指标 + source + last_collected_at + last_error
```

`WechatArticleMetricSnapshot` 每次有效写回追加一条：

```text
article_id + sampled_at + 五项指标 + source
```

数据表由 SQLModel 在服务启动时创建，数据库仍使用 CreatorHub 现有 SQLite，不另建第二套事实库。

## 7. 重构建议

推荐保留以下稳定契约：

```text
视觉采集器 -> WechatArticleMetricIn JSON -> CreatorHub API -> SQLite 快照
```

可独立替换的部分：

1. `PrintWindow` 可换成 Windows Graphics Capture；
2. Codex 视觉读取可换成 OCR、本地视觉模型或远程多模态模型；
3. 视觉层可增加标题匹配、截图哈希、置信度和原始证据路径；
4. `fetch_article_metrics()` 可接入登录态 `getappmsgext` 响应，并继续输出同一个字段结构；
5. 批量任务可在外部 Agent 编排，CreatorHub 只承担幂等文章记录与快照写入。

视觉层输出建议扩展为：

```json
{
  "article_id": 1,
  "metrics": {},
  "confidence": {},
  "observed_at": "ISO-8601",
  "evidence": {
    "window_title": "微信",
    "article_title": "页面标题",
    "screenshot_sha256": "..."
  }
}
```

扩展字段应由新版本接口接收；现有 `/metrics` 接口继续保留，供轻量 Agent 使用。

## 8. 验收标准

1. `/health` 返回 `ok`；
2. 同一规范化文章 URL 串行重复同步复用同一条当前记录；
3. 标题或 URL 与目标不一致时，视觉 Agent停止该次写回并记录原因；
4. `10万+` 同时保存 `read_display="10万+"` 与 `read_count=100000`；
5. 负数请求返回 `422`，空指标请求返回 `400`；
6. 每次有效写回只新增一条快照；
7. GET 当前值与最新快照一致；
8. 连续采集后五项增量计算正确；
9. PC 窗口截图不调用 `SetForegroundWindow`、`ShowWindow` 或模拟前台点击；
10. 视觉 Agent 异常时 CreatorHub 持续监控进程仍保持健康。

## 9. 本机运行入口

本项目仓库：

```text
E:\Videohao\抖音监控\creatorhub
```

本机辅助启动文件位于仓库外，不随 Git 提交：

```text
E:\Videohao\抖音监控\启动抖音监控.ps1
E:\Videohao\抖音监控\停止抖音监控.ps1
E:\Videohao\抖音监控\run_creatorhub_service.py
```

该安排把机器路径、浏览器目录和运行日志留在本机，把可复用的数据模型与 API 保留在 CreatorHub 仓库内。
