# 2026-08-04 Life Log 桥二：蒸馏升格（`lifelog consolidate`）

> 接 `2026-08-04-lifelog-namespace-cc.md`（存储核心 + CLI）。本次在 MBP16 真源码仓 `~/code/radiomind`
> 的 `feat/lifelog` 分支上完成。上一段工作在 MBP14 的 clone 上做，经 GitHub origin 取回。

## 背景与目标
生活日志有两座桥通往正常记忆：
- **桥一 检索注入**（已就绪）：`lifelog search` → RadioHand 对话时注入相关 episode。
- **桥二 蒸馏升格**（本次）：读近期日画像/情节 → 提炼**耐久事实**（"养猫""和同住者住一起""在追漫威"）
  → 写成普通 L2 fact + 习惯 + KG 三元组。这样即使不搜生活日志，日常对话也能用上这些沉淀。

## 设计取舍
**host-thinks 模式**（照 `refinement/step.py`）：RadioMind 只组织材料与落库，LLM 调用归调用方。
理由是 R76S 上 bare CLI 是 pure-memory（无 LLM 环境变量），daemon 才注入 LLM。因此拆成
`prepare`（出 prompt）/ `apply`（写结果）两次 subprocess 调用，RadioHand 夹在中间出思考；
另给 `auto`（本机有 LLM 时一次跑完，开发/单机部署用）。

**幂等**由三层保证：日画像 metadata 打 `consolidated_at` 戳 → 下次 `prepare` 跳过；已蒸馏事实进 prompt
的 "do NOT repeat" 列表；`MemoryStore.add` 同 content+domain 去重。事实更新走 `supersedes`（归档旧条）。

## 落地文件
- `storage/lifelog.py`：+`recent_days()`（默认跳过已蒸馏）、`mark_consolidated()`、`episodes_for_dates()`。
- `refinement/lifelog_consolidate.py`（新）：`build_context` / `format_material` / `build_prompt` /
  `parse_response`（容忍 ```json 围栏与前置话）/ `apply_result`（facts→L2、habits→HabitStore、
  entities→KG、标记日期）。事实默认落 domain=`lifelog`，metadata 记 source/dates/confidence/evidence。
- `cli/main.py`：`lifelog consolidate` 组 = prepare / apply / auto，轻量路径（不加载 mind）。
- `tests/test_lifelog_consolidate.py`（新）：上下文、解析、置信度门槛、幂等、supersede 归档、dry-run。

## 验证
- pytest 全绿：**1131 passed, 6 skipped**（含 MBP14 遗留待复核的 `test_lifelog_store.py`，本次一并跑过）。
- 端到端（临时 `RADIOMIND_HOME`，未碰真实库）：合成 rollup → `put-rollup` → `consolidate auto`
  （真实 DashScope qwen3.8-max）→ **6 facts + 6 triples 落库、0 habits**（单日材料按提示词规则不产习惯）；
  再次 `prepare` 返回空（幂等生效）；`radiomind search 猫/戒指/漫威` 均命中蒸馏出的事实。

## 遇到的问题
1. **Homebrew python@3.13 坏了**：`pyexpat` 找不到 `_XML_SetAllocTrackerActivationThreshold`（对不上
   系统 libexpat），导致仓内 `.venv` 的 pip 与 uv 都无法使用（uv 报 `platform.mac_ver()` 空）。
   绕法：`uv venv --python 3.13` 另建独立环境跑测试，不动仓内 venv。**根治需 `brew reinstall python@3.13`**。
2. **推理模型超时**：qwen3.8-max 蒸馏一天材料耗时 ~2 分钟（5.4k reasoning token），
   `OpenAICompatBackend` 默认 45s 直接 read timeout。`auto` 因此加 `--timeout`（默认 300s）并下压到 backend。
3. **单日不该产习惯**：首版提示词让模型给出 3 条 0.5 置信的"习惯"，全被 `HabitStore.MIN_CONFIDENCE=0.7`
   拦下。改提示词要求"同一模式需跨至少两天才算习惯"，模型即不再硬凑。
4. **模型自觉抹掉了同伴代号**：提示词说 `对方甲` 只是当日标签、非稳定身份，模型输出统一写成"同住者"——
   与隐私意图一致，符合预期。

## 待办（接续）
1. RadioHand 侧（Rust，R76S 生产代码）：capture（rollup→`lifelog put-rollup`）+ 注入（`lifelog search`）
   + 定时蒸馏（`consolidate prepare` → daemon LLM → `consolidate apply`）。仿 `library.rs` subprocess 契约。
2. 部署 R76S：rsync `feat/lifelog` → 重装 `/opt/radiomind-venv`；**先备份 db**、schema 5→6 自动迁移、
   对 git 版本防降级、审计零泄露。
3. 观察项：`memories_fts` 是 `unicode61`，中文整段成一个 token，中文检索实际靠 `pyramid` 的 LIKE 兜底
   （代码已注明）。生活日志侧不受影响，但若日后要提升中文召回，这是核心侧的改造点。
