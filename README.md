# TED Procurement Intelligence MCP v0.2.0

把欧盟 TED（Tenders Electronic Daily）公开采购数据变成 Agent 可直接调用的 **采购情报数据 MCP**。

V2 不再只是“实时搜 TED”。它加入了：

- 产品关键词 → CPV 自动推断（基于真实 TED 历史公告频次与样例）
- SQLite / Supabase 采购数据仓库
- TED `ITERATION` 有界增量同步
- 供应商画像持久化
- 供应商画像 → 实时采购机会匹配
- 仓库内“每日新机会”匹配
- API Key + 每日额度
- MCP Python SDK v2 Streamable HTTP 部署入口
- Vercel Python ASGI 部署配置

目标用法：

> “我是中国 GPS 追踪器供应商，帮我持续找欧洲政府采购机会，并告诉我为什么值得跟。”

## 数据源

- TED Search API v3：`POST https://api.ted.europa.eu/v3/notices/search`
- 搜索公开采购公告无需 TED API Key。
- 支持全文、CPV、采购方国家、日期、买家、公告类型等 TED Expert Search 条件。
- `PAGE_NUMBER` 用于普通搜索；`ITERATION` 用于仓库同步。

## 15 个 MCP Tools

### V1 实时采购情报

| Tool | 用途 |
|---|---|
| `raw_ted_search` | 直接执行 TED Expert Query |
| `search_procurements` | 按关键词、CPV、国家、日期搜索采购 |
| `find_opportunities` | 搜近期采购并做透明相关性评分 |
| `get_notice` | 按 publication number 获取结构化公告 |
| `find_buyers` | 聚合买家/采购机构 |
| `buyer_history` | 查看采购方历史公告 |
| `find_awards` | 找历史中标公告及 winner/value 线索 |
| `market_stats` | 按国家、CPV、买家、金额做当前结果统计 |

### V2 数据产品层

| Tool | 用途 |
|---|---|
| `suggest_cpv` | 用 TED 历史公告反推产品最可能对应的 CPV |
| `upsert_supplier_profile` | 保存/更新供应商画像 |
| `get_supplier_profile` | 读取供应商画像 |
| `match_supplier_opportunities` | 按供应商画像实时搜索 + 排序 TED 机会 |
| `sync_notices` | 用 ITERATION 将 TED 数据同步进仓库 |
| `daily_opportunities` | 从已同步仓库里找最近机会并按画像排序 |
| `warehouse_stats` | 返回仓库条数、供应商数、数据最新日期 |

## 供应商画像

示例：

```json
{
  "profile_id": "gps_factory_cn",
  "products": ["GPS tracker", "dog GPS tracker"],
  "cpv_codes": ["32522000"],
  "target_countries": ["DE", "FR", "PL"],
  "excluded_countries": [],
  "certifications": ["CE"],
  "moq": 100,
  "lead_time_days": 30,
  "notes": "OEM/ODM available"
}
```

V2 匹配分数会使用产品词、CPV、目标国家、公告新鲜度、未来截止日期、证书文字提及等可解释信号。MOQ、交期、资质、技术规范等不能从 TED 自动确认的内容，会返回到 `constraints_to_verify`，不会伪装成已满足投标资格。

## CPV 自动推断

`suggest_cpv("GPS tracker")` 不依赖 LLM 猜分类，也不要求维护一张手工 CPV 映射表。

流程：

```text
产品词
  ↓
TED 历史匹配公告
  ↓
提取公告 CPV
  ↓
按出现次数排序
  ↓
返回 CPV + support_count + support_share + 样例公告
```

所以 Agent 能看到“为什么推荐这个 CPV”。最终投标使用的 CPV 仍应以具体公告/采购分类要求为准。

## 本地运行

需要 Python 3.11+。

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

### stdio

```bash
ted-procurement-mcp
```

默认本地仓库：`ted_procurement.db`。

### Streamable HTTP

```powershell
$env:MCP_TRANSPORT="streamable-http"
$env:MCP_HOST="0.0.0.0"
$env:MCP_PORT="8000"
ted-procurement-mcp
```

连接：

```text
http://127.0.0.1:8000/mcp
```

健康检查：

```text
http://127.0.0.1:8000/health
```

## Supabase 生产数据仓库

### 1. 建表

在 Supabase SQL Editor 执行：

```text
schema/supabase.sql
```

它会创建：

```text
notices
supplier_profiles
sync_state
api_keys
api_usage
warehouse_stats (view)
increment_api_usage(...) (RPC)
```

所有业务表都开启 RLS，客户端角色不直接读取；生产 MCP 使用 `service_role` 调 PostgREST。

### 2. 环境变量

```text
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
```

**不要把 service-role key 放进浏览器、Git 或 MCP 客户端配置。**它只属于服务端环境变量。

## API Key / 配额

远程收费版可以开启：

```text
MCP_REQUIRE_API_KEY=true
```

客户端支持：

```http
Authorization: Bearer <your-mcp-key>
```

或：

```http
X-API-Key: <your-mcp-key>
```

数据库只保存 SHA-256 hash，不保存原始 key。

生成 hash：

```bash
python scripts/hash_api_key.py ted_live_your_secret
```

然后向 `api_keys` 表插入：

```sql
insert into public.api_keys(key_hash, name, daily_quota, enabled)
values ('<sha256>', 'client-a', 1000, true);
```

`increment_api_usage` RPC 用数据库原子 upsert 计数，避免多实例并发下用本地内存计数。

## TED → Supabase 同步

示例 MCP 调用：

```json
{
  "query": "publication-date >= 20260901",
  "max_pages": 4,
  "page_size": 250
}
```

单次同步硬限制：

- `max_pages <= 20`
- `page_size <= 250`

即使 Agent 参数写错，也不会一次无限抓取。

同步使用 TED `ITERATION` token，并把 cursor 保存到 `sync_state`。公告按 `publication_number` upsert，所以重复同步不会重复插入同一公告。

## 每日机会

先保存 supplier profile，再同步对应 TED 数据，然后：

```json
{
  "profile_id": "gps_factory_cn",
  "since_hours": 24,
  "limit": 50
}
```

返回：

- 最近仓库公告
- supplier match score
- 分项评分
- 待确认投标条件
- warehouse stats
- 数据完整性提示

TED 的 `publication-date` 是日级字段，所以小时窗口会保守地向日期边界取整。

## Vercel 部署

项目根目录已经配置：

```toml
[tool.vercel]
entrypoint = "app:app"
```

`app.py` 暴露 MCP ASGI app。远程模式使用 MCP Python SDK v2 `streamable_http_app()`，JSON response + stateless HTTP，更适合 serverless。

生产环境至少配置：

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

如果没有 Supabase，Vercel 上仓库会显示为 `none`；代码不会偷偷使用 `/tmp` SQLite 并把易丢失的数据伪装成持久数据库。

如果使用自定义域名，再配置 host（只写 hostname，不写 `https://`）：

```text
MCP_ALLOWED_HOSTS=mcp.example.com
```

Vercel 自带 hostname 会从 `VERCEL_URL` 自动加入 MCP transport-security allowlist。

## Docker

```bash
docker build -t ted-procurement-mcp .
docker run --rm -p 8000:8000 \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  ted-procurement-mcp
```

## Live TED smoke test

联网环境：

```bash
python examples/live_smoke_test.py
```

Search API 本身不需要 TED API Key。

## 数据正确性边界

1. TED 是采购事实的唯一来源；缺失金额、winner、deadline、证书等字段不会被编造。
2. `suggest_cpv` 是基于 TED 匹配公告的统计推断，不是法律/技术分类保证。
3. `daily_opportunities` 只代表已经同步到仓库的数据，不会声称覆盖所有 TED 公告。
4. supplier match 是机会筛选，不等于投标资格确认。
5. `market_stats` 是返回数据的聚合，不是去重后的完整市场规模。
6. TED 返回 `timedOut=true` 时，客户端会报错，避免把部分结果当完整数据。
7. API key 原文不落库、不写日志。

## 项目结构

```text
src/ted_procurement_mcp/
├── ted_client.py
├── query_builder.py
├── normalizer.py
├── scoring.py
├── service.py
├── cpv_discovery.py
├── storage.py
├── supplier_profiles.py
├── supplier_matcher.py
├── sync_service.py
├── auth.py
├── asgi.py
├── mcp_adapter.py
└── server.py

schema/
└── supabase.sql

scripts/
└── hash_api_key.py

app.py
vercel.json
```

## 商业化下一步

V2 已经有“可收费 API/MCP”的骨架。接下来最值得加的是：

- Vercel Cron / Workflow 自动跑每日增量同步
- 用户/tenant 隔离
- Stripe/稳定币计费与额度套餐
- 邮件 / Telegram / 飞书推送
- Buyer / Winner 实体去重和采购关系图
- 供应商证书、MOQ、交期知识库
- 更多公开采购源（各国采购门户、世界银行、UNGM 等）统一到同一 MCP
