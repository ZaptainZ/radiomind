# Origin-3b — 做梦探针（--dream-after-ingest, 2-qid, sandbox-copy 隔离）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-10
> 前置: Origin-1a/3a 审计 + 用户裁决（与 hygiene 批分开;成功标准是窗口稳定性/不受伤/
> 不错合并,**不是分数**;不得在跑出证据前宣传"会涨分"）。
> 范围: bench-side flag + 只读探针。零 `src/radiomind` 改动。不跑 n=100。

---

## 1. 基础设施（已落地,deterministic 验证）
- `--dream-after-ingest`（默认 off）: 每题 ingest 后调 `mind.trigger_dream()`（"夜晚"巩固,
  模拟实际使用）。无 domain scoping → 标注 probe-scale only。失败仅记录不致命。
  与 `--answer-only` 组合被 `_validate_dream_flag` 拒绝（exit 2,CLI 实测）。
- telemetry: per_query `dream_stats {merged, pruned, insights, duration_s}`。
- 探针脚本 `bench/end_to_end/origin3b_dream_probe.py`: store snapshot → trigger_dream →
  snapshot → diff（archive/merge 改写/新增）+ gold evidence top-30/200 排名前后对照。
- `tests/test_origin3b_dream_flag.py`（8）+ regression pack `harness:origin3b-dream-flag`
  → **22 类全绿**。

## 2. 实验设计（ingest 混淆已消除）
seed（fresh ingest）→ **文件级复制 sandbox**（dream 是两臂间唯一变量;复制后 sed 修正
config.toml 内绝对路径,防 dream 误写原 store）→ dream 探针跑在副本 → 4 臂 answer-only ×5。
- d3ab962e（probe 靶: ingest 方差决定窗口构成,VR-4a FFF / VR-2c 固定store 5/5）
- 6aeb4375（stable-pass control,counting 同类,无 helper 依赖）
- 模型: deepseek-v3.2/dashscope + gpt-4o/openrouter（标准组合）。

## 3. 结果

| 臂 | answer-only ×5 | gold top-30 | gold top-200 | store 变化 |
|---|---|---|---|---|
| d3ab base | PPPPP | 1 | 16 | — |
| d3ab dream | PPPPP | 1→**1**（无变化） | 16→**16** | merge 3 + archive 2（全在无关"大教堂"turns）+ 1 habit |
| ctrl base | PPPPP | 15 | 22 | — |
| ctrl dream | PPPPP | 15→15 | 22→22 | **零变化** + 1 habit |

注: 本次两个 seed 恰为"好 ingest"（seed 即 PASS,d3ab962e 答 8 miles）——与 VR-2c
"store 对就 5/5 过"一致。**坏 ingest 的"救援"场景本轮未出现,无法测**。

## 4. 判读（对照预设成功标准）
1. "d3ab962e evidence window 更稳定" — **未证实**: 窗口逐条不变（1/30, 16/200 前后相同）。
   机制原因: `_prune_decay` 30 天 cutoff 对刚 ingest 的记忆永不触发; `_prune_redundancy`
   只扫每 domain 前 10 条 FACT 的近邻配对（605 条的 domain 覆盖 ~1.7%）; `_wander` 只加
   1 条 habit。**当前实现的 dream 在 bench 时间尺度上是"近中性"** —— 触发面与 bench
   场景错配,够不到窗口构成。
2. "control 不受伤" — ✅（零 store 变化,5/5）。
3. "没把 distinct FACT 错合并" — ✅ 本对（merge 命中的是真冗余的重复表述 turns,工作
   如设计）。**但发现一个真实缺陷: merge 改写丢失 `[user]`/`[assistant]` 角色前缀**
   （id 524: "[assistant] It is undeniable…" → "While the cathedrals…" 无前缀）。本次
   碰巧落在无关 turns;若证据恰在 domain 前 10 条,会破坏 role-tagged 格式（SelfAnchor
   user-turn 扫描、answer prompt 的 role 语义都依赖它）。这是 **dream 产品侧 bug**,
   与 bench 无关,应另行修（`_merge_pair` 的 MERGE_PROMPT 应保留 role 前缀）。

## 5. 结论与处置
- **dream-as-score/稳定性-lever: PARK**。安全中性已证,但对目标场景（ingest 方差→窗口
  构成）无作用——不是"做梦没价值",是当前修剪范围设计服务的是长期个人记忆维护
  （decay/真冗余）,与单次 bench ingest 的时间尺度天然错配。
- **flag 保留**（默认 off）: 作为"模拟实际使用"的基础设施与未来实验入口,符合
  A2A-practice 精神;不宣传任何分数效应。
- **重开条件**: (a) dream 增加全域 redundancy pass + 修复角色前缀丢失后,且 (b) 复现出
  一个坏 ingest seed（d3ab962e FFF 形态）验证"救援"假设——两者都需单独立项。
- 顺带产出: prompt_sections telemetry 首批真实数据 —— 两道 counting 题
  `atomic_present=True`（337/436 chars）、`cardinal_present=False`,即 **decomposer 在
  counting 题上确实触发**,S2 的问题收窄为"触发但精度/利用问题",非触发缺失。

## 6. Artifacts
`o3b-seed-{d3ab962e,6aeb4375}.json` / `o3b-dream-diff-*.json` / `o3b-ao-{d3ab,ctrl}-{base,dream}-rep{1..5}.json`（20）。沙箱 `/tmp/rm-sandbox-o3b-*`、`/tmp/rm-o3b-dream-*`（不入库）。

## 7. 不做 / 守住
不改 dream 实现（角色前缀 bug 另行立项）。不跑 n=100 dream。不把"近中性"写成"无害可常开"
（n=100 下 trigger_dream 每题全 store 扫描,成本叠加,未评估）。
