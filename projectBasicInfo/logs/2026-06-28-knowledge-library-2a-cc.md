# KnowledgeLibrary-2a — 信息收集库底座（schema + LibraryStore + CLI）

- 日期：2026-06-28
- 角色：cc
- 来源：RadioHand 需要"信息收集库 / Reading Library"能力——用户主动收藏的外部资料（文章/论文/笔记），
  agent 自动打标签/组织/去重/建关系。架构裁定（owner）：**truth 入 RadioMind**（与长期记忆/profile/检索同
  底座），不在 RadioHand 偷存（否则 RadioHand 长成第二个 Mind）。
- 范围（2a）：先在 RadioMind 补 namespace + schema + CLI skeleton + LibraryStore；RadioHand 后续只接最小
  capture/search。

## 关键设计：薄新增 + 复用现有 knowledge_graph
信息收集库**不另起一套实体/关系系统**。RadioMind 已有 `triples + entity_aliases`（knowledge_graph），所以：
- **新增 3 张表**（migration v5，与 `memories` 分表、不污染对话记忆召回）：
  - `library_items`：资料条目 truth（title/source_url/source_domain/source_type/author/published_at/
    captured_at/language/content_hash/status + digest 字段 short_summary/key_points/why_it_matters/
    useful_for/open_questions + user_id/metadata）。
  - `library_tags`：facet 标签（name/facet[domain/topic/method/product/person/format/source/status]/
    aliases/parent_id/status）。
  - `library_item_tags`：关联（item_id/tag_id/confidence/source[llm/user/system]）。
  - `library_items_fts`（fts5 over title+short_summary）。
- **claim/relation/entity 复用 KG**：`library link <s> <rel> <o> --source-id <item>` → `kg.add_triple`
  （claim = triple，source_id 指向 library_items.id）；entity 去重/合并走现有 `entity_aliases`/canonicalize。
  **绝不建 library_claim/library_edge**（避免第二套关系图不同步）。

## 实现
- `storage/migrations.py`：`@register(version=5)` `_add_knowledge_library`，`CURRENT_SCHEMA_VERSION=5`。纯
  增表（CREATE IF NOT EXISTS），对既有 DB 幂等、不动 `memories`。
- `storage/library.py`（新）：`LibraryStore(conn)` + `LibraryItem` dataclass + `normalize_url`（去 utm_*/
  fragment）+ `content_hash`。方法：put_item(强去重：normalized url ∨ content_hash)/get_item/list_items/
  search_items(FTS→LIKE 回落 + tag/user 过滤)/upsert_tag(alias 解析)/tag_item/item_tags/merge_tag(重指
  +archive 旧 tag+记 alias)/set_status/stats。共享 memories 连接（分表，不另开 db）。
- `core/mind.py`：`mind.library`（lazy LibraryStore over `_store.conn`）+ `mind.kg` property。
- `cli/main.py`：`@cli.group("library")` → put（--payload JSON / 扁平 flags）/get/search/list/tag/tag-merge/
  link/stats，**stdout 全 JSON**（RadioHand subprocess 解析）。多租户 --user（user_id 隔离）。

## 测试 / 回归
- `tests/test_library.py`（+8）：migration 建表+版本≥5、normalize_url、put/get、URL+hash 双去重、faceted
  tags、FTS+tag 过滤、merge_tag 重指+alias、user 隔离搜索。
- **全套 333 passed / 6 skipped**（migration v5 纯增表，未破坏既有 246→现 325 基线）。
- 注：项目 `.venv` 是 py3.13（本机 pyexpat/libexpat ABI 坏、pip/uv 不可用）；用临时 **python3.12 venv**
  （`/tmp/rm-test-venv`，`pip install -e . pytest`）跑测试。owner 环境若同样 3.13 坏，测试需 3.12 env。

## 边界（守）
- 资料库与 `memories` 分表，库召回不污染个人记忆召回。
- 不重建第二套 KG（claim/relation/entity 复用 triples/entity_aliases）。
- CLI 输出 JSON、不含密钥；user_id 隔离。

## 待办（下游）
- **RadioHand KnowledgeLibrary-2b**：capture intent（hint+planner）→ ReaderManager 读 → LLM 结构化 payload →
  `radiomind library put --payload` → 自然回执；query → `radiomind library search`。adapter 加 `library`
  子命令封装（现 `memory_radiomind.rs` 只 search/learn）。
- 部署：R76S 重装 radiomind（rsync 源码 build，无 GitHub）。
- 2c：标签 hygiene/taxonomy proposal、near-dup review、向量召回（embedding 增强 search）。

## 文件
`storage/migrations.py`、`storage/library.py`(新)、`core/mind.py`、`cli/main.py`、`tests/test_library.py`(新)。
