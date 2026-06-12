# LoRAFuel-1a — 燃料链路审计：真正的断点是"生成"而非"过期"（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-12
> 范围: 只读 code/artifact 审计,零代码改动。代码建议全部拆入 1b 候选。
> 前置: LoRA 部署链路线闭环（1a→1b→1c）;用户裁决燃料问题独立开线。

## 1. 燃料链路图（实测代码路径）

```
记忆积累 (hooks ingest, L1 gate)          ← 产品日常路径,自动
  ↓ ✗✗ 断点①: 无任何自动炼化触发 ✗✗
三体炼化 chat.refine                       ← 仅 CLI `radiomind refine` 手动 /
  │                                          stop_hook 仅"建议"宿主调 refine_step
  ▼
add_habit (confidence≥0.7 → CANDIDATE)
  ├─→ L2 PRINCIPLE 镜像 (mind.py:783)      ← pyramid 检索真正命中的是镜像
  ▼          ✗ 断点③: 镜像命中不回流 habit.hit_count ✗
HDC hit 记账: search 时拿原始 NL 串查随机超维码本,
  min_score=0.005 → top-3 噪声命中          ← 晋升(3 hits)实质随机
  ▼
prune_stale (CANDIDATE+0hit+14天 → ARCHIVED)
  ✗✗ 断点②: 全代码库零调用方——14 天过期从未自动运行过 ✗✗
  ▼
data_gen.all_habits(非 ARCHIVED) ≥5 门槛 → train.jsonl → adapter
  ✗ 断点④: 无"已消费/已固化"标记——DataGenReport 只有 habits_used 计数,
    无 habit ids;MemoryStatus 枚举无 CONSUMED;TrainResult 不记数据来源 ✗
```

## 2. 核心翻案: live store 0 habits 的真因**不是** 14 天过期
- `prune_stale` / `prune_stale_habits` **没有任何调用方**（CLI/hooks/dream/doctor 都不调）——
  过期机制是死代码,从未清空过任何东西。**1a/1b 日志与 commit 中"被 14 天零命中过期
  清空"的归因是错的,以本节为准（erratum）。**
- 真因 = **断点①（生成断流）**: 产品日常路径（hooks ingest）从不跑炼化;`trigger_chat`
  只有手动 CLI 入口;stop_hook 对宿主只是文字建议。live store 自 4 月中 P1 重构后
  没有任何东西铸造过习惯——0 是"从未生成",不是"生成后被清"。
- 4 月 14 digest"9 条习惯" vs 4 月 15 备份 0 条: P1 重构引入门控 HabitStore（新
  schema: status/evidence/falsifier）,旧习惯未迁移即清零,或 digest 计的是另一数据目录
  ——两种解释都指向"重构期一次性清零",与过期机制无关。

## 3. 三问回答
1. **habit 何时生成/过期怎么判/过期前进训练集吗/有无已消费态?**
   生成=仅手动炼化;过期判定存在但从不运行;CANDIDATE 即可进训练集（data_gen 只排
   ARCHIVED,不区分 CANDIDATE/CONFIRMED）;**无任何已消费/已固化状态**。
2. **训练入口读什么/最低燃料/有无 guard/记录 ids 吗?**
   读 `all_habits()` 非 ARCHIVED;双 guard 已存在且有效（data_gen: ≥5 habits + ≥2
   domains;train_lora: ≥30 examples——本次 live store 正是被第一道 guard 正确拒绝）;
   **不记录所用 habit ids**（只有 habits_used 计数）。
3. **策略问题**（建议,定夺在用户）:
   - "训练消费过的 habit 延长保鲜" — 在过期被接通**之前**无意义（它根本不跑）;正确
     顺序是先修断点①③,再谈过期与保鲜。
   - "训练前自动触发炼化补燃料" — **是当前最小可行解**: `radiomind train
     --prepare-habits`,燃料不足时对 top-N domain 跑 chat 炼化（LoRA-1b 实测 6-11 个
     domain 产 6 条,几十次 LLM 调用,几分钟）。
   - 但根治是断点①: 习惯生成需要一个自动化挂载点（候选: stop_hook 从"建议"升级为
     条件触发 refine_step / ingest 累积 N 条后自动炼化 / 每日 dream 时段),这是产品
     节奏决策。

## 4. LoRAFuel-1b 候选（按性价比排序,全部待批）
1. **`train --prepare-habits`**: 燃料 <MIN_HABITS 时自动炼化 top domains（闭环最小修,
   复用 trigger_chat,LoRA-1b 已验证产出率）。
2. **训练消费记录**: DataGenReport/TrainResult 增 habit ids + adapter 元数据;为未来
   保鲜/增量训练打地基（纯增字段,零行为变化）。
3. **接通 prune_stale**: 挂到 dream Phase 1 或 doctor,且必须同时带"消费保护 +
   命中记账修复",否则按噪声 hit 归档等于随机删燃料——**单独接通有害,不建议先做**。
4. **镜像命中回流**（断点③,中风险）: PRINCIPLE 镜像被检索命中时回写源 habit
   hit_count;让晋升/过期建立在真实使用信号上。1b 不必做,记为 2 期。

## 5. 不做 / 守住
零代码改动（含"顺手接通 prune_stale"的诱惑——见 §4.3 风险）。不动 14 天阈值数值。
不把 digest "9 条" 之谜当阻塞项（两种解释都不改变结论）。
