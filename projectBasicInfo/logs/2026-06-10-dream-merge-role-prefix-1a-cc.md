# DreamMergeRolePrefix-1a — merge 保留角色前缀 + 拒绝跨角色合并

> 作者: Claude Code (cc) ｜ 日期: 2026-06-10
> 前置: Origin-3b 探针发现 `_merge_pair` 的 LLM 改写丢失 `[user]/[assistant]` 前缀,
> 且实测发生过 user turn 被并入 assistant turn（ids 527→528）。用户裁决: 单独小线修复,
> 只改 merge prompt/parser + 单测,跑 regression pack,不跑 n=100。
> 范围: `src/radiomind/refinement/dream.py` 一处 + 测试。产品正确性修复,非追分。

## 1. 改动（确定性规则,不靠 prompt 央求）
`split_role_prefix(text) -> (role|None, body)`（模块级,正则 `^\[(\w+)\]\s+`）;
`_merge_pair` 改为:
- **角色不同（含 tagged×untagged）→ 拒绝合并**,返回 None,零 store 变更,LLM 调用都不发——
  user turn 并入 assistant turn 毁掉的是角色语义,不是冗余。
- **角色相同** → 先剥前缀再喂 LLM（LLM 只见 body）,合并文本由代码**确定性重挂前缀**;
  LLM 自己回了前缀也不会双写（先剥再挂）。
- 无前缀（产品侧普通记忆）→ 行为不变。

## 2. 验证
- `tests/test_dream_merge_role_prefix.py`（8）: split 边界（mid-sentence `[user]` 不算前缀）、
  同角色保前缀 + LLM 不见前缀、echo 不双写、跨角色拒绝（零 mutation 零 LLM 调用）、
  tagged×untagged 拒绝、无前缀照旧、空回复不动 store。
- regression pack 新增 `refinement:dream-merge-role-prefix` → **23 类全绿**。
- 全量 `pytest tests/` → **934 passed**。未跑 n=100（按裁决;dream 默认不进 bench 路径,
  本修复无分数影响claim）。

## 3. 边界说明
`_are_similar_text` 仍按全文（含前缀）算重叠——同角色对的 `[user]` 共享 token 轻微抬高
相似度,但合并入口已由角色规则把守,且改相似度算法超出"只修 merge"的授权范围,不动。

## 4. 后续（未开,候选）
S2 section-quality audit: 等下一次 n=100 / target pack 自然积累 `prompt_sections`
telemetry 后,分析 atomic/cardinal 注入与正确率的关联,再决定是否动 decomposer。
不在本线提前盲改。
