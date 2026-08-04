# 2026-08-04 Life Log (生活日志) namespace — storage core

## 背景
HackWare 的随身麦生活日志流水线（micpro-audio）需要把归纳出的"情节/日画像"入库。按 owner 既有裁定
（truth 入 RadioMind、不在 RadioHand 偷存，见 KnowledgeLibrary），生活日志=**第三类 namespace**，
与 memories（对话）、library（收集的文档）并列，独立表、不污染前两者的召回。

## 已落地（本仓 feat/lifelog，commit b6ff77f）
- **migration v6 `_add_lifelog`**（`storage/migrations.py`，CURRENT_SCHEMA_VERSION→6）：
  - `lifelog_episodes`(date/start_clock/end_clock/activity/participants[json]/topics[json]/
    topics_text/media[json]/summary/content_hash/status/user_id/created_at/metadata)
  - `lifelog_day_profiles`(date/narrative/people[json]/topics/activities/highlights/...)
  - `lifelog_episodes_fts` FTS5 over **activity+summary+topics_text**（比 library 的 title+summary 更宽：
    话题只出现在 topics 也能被全文搜到——修掉 library "搜戒指/面包返空"的问题）
  - UNIQUE(user_id,date,start_clock) 自然去重；UNIQUE(user_id,date) 日画像 upsert。
- **`storage/lifelog.py`**：`LifelogStore`（put_episode/get/list/search_episodes/put_day/get_day/stats）
  + `LifelogEpisode`/`DayProfile` dataclass。参与者/话题/媒体存 json 列（不建 library 那套 tag 表）；
  people 需跨天身份绑定时复用 knowledge_graph（同 library link）。
- **测试** `tests/test_lifelog_store.py`：迁移建表 / 话题全文可搜（核心改进）/ 去重 / 人物过滤 /
  日画像 upsert / stats。自带最小 memories 基表（v1 在 database.py），无需 DB fixture。

## 验证
本机 python3.9 独立脚本（按文件路径加载 migrations+lifelog，绕重依赖）跑通全部断言：
schema→6、`search 戒指`命中（话题在 topics 非 summary）、dedup、person filter、day upsert、stats。
committed 测试待在 RadioMind 3.13 env 跑 pytest 复核。

## 数据契约（micpro-audio → RadioHand → 此处）
episode/day-profile JSON schema 见 HackWare `radiohand-integration-log.md §3`。

## 待办（接续）
1. CLI：`storage/lifelog.py` 之上加 `cli/main.py` 的 `lifelog` 命令组（put/put-day/search/get/list/
   day/stats），仿 library 用轻量 `_get_lifelog()`（只开 SQLite 不加载 mind，避免 30s embedding 加载）。
2. RadioHand 侧最小 capture（收 rollup → `radiomind lifelog put`）+ query。
3. 部署 R76S：rsync+重装，先备份 db、schema 5→6、对 git 版本（防降级）。

## 追加：CLI（commit 见下）
`cli/main.py` 加 `_get_lifelog()`（轻量 SQLite）+ `lifelog` 组：put / **put-rollup**（一次灌整份
rollup=episodes+day，RadioHand 入口）/ search（=检索桥，注入对话）/ get / list / day / stats。
端到端验证（真实 rollup_260803）：4 episodes+1 day 入库；search 戒指/复仇者/面包 命中（话题词可搜）；
py_compile 过。两座桥：桥一(检索注入)=lifelog search 就绪；桥二(蒸馏升格)待做=lifelog consolidate。
