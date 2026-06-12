# LoRAFuel-1b — prepare-habits + 训练消费记录（不碰 prune_stale）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-12
> 前置: LoRAFuel-1a（生成断流是真因）。用户裁决: 只做 ①prepare-habits ②消费记录;
> 不接 prune_stale（记账仍是噪声）;不做镜像回流。

## 1. 实现
- **`src/radiomind/training/fuel.py`**（新）: `prepare_habits(habits, domains_by_size,
  refine_fn, min_count, max_domains=8)` 纯函数——燃料足时 no-op;不足时按 domain 体量
  从大到小炼化,达阈值即停;单 domain 异常不致命;返回 PrepareReport（before/after/
  per-domain 产出/失败原因）。refine_fn 注入 → 零 LLM 可单测。
- **消费记录（纯观测）**: `data_gen.habit_id()`（sha1[:12],HDC store 无 id 列）;
  `DataGenReport.habit_ids`;`TrainResult.habit_ids`;`mind.train` 改走 report 版并在
  adapter 旁写 `train_meta.json`（ids/计数/model/iters/时间,写失败不影响训练结果）。
- **CLI**: `train --prepare-habits/--no-prepare-habits`（默认开,保守=燃料足即跳过）;
  echo 准备前后数量、refined domains 与各自产出、失败原因;data-only 输出 habit_ids。

## 2. 验证（全部完成标准命中）
- 单测 `tests/test_lorafuel_prepare.py`（11）: 低燃料触发+达阈即停、archived 不算燃料、
  足够不触发（refine_fn 零调用）、域耗尽给明确原因、异常不致命、max_domains 限额、
  habit_id 稳定性、report/TrainResult 字段、CLI/mind 接线守卫。pack 新增
  `training:lorafuel-prepare` → **28 类全绿**;全量 **964 passed**。
- **E2E smoke（宿主注入模式,产品首要形态）**: 空 store(4月副本) R1 → prepare 触发
  **0→5**（general+1/ios+1/rust+2/network+0/ai+1,达阈值即停未碰剩余域）→ data_gen
  通过 **108 train/26 valid** → **habit_ids 5 条全记录**;R2 → triggered=False 零炼化。
- **失败分支真实验证（CLI 模式,意外但有价值）**: CLI 语境下炼化静默 0 产出,prepare
  正确报"refined 8 domains but only 0/5 — LLM unavailable/refusing"——明确失败原因
  分支被三次实测覆盖。

## 3. 排障中挖出的两个产品级缺陷（1b 范围外,候选立项）
1. **`LLMRouter-1a` 候选: config.toml 多 provider 形同虚设。** `_resolve_llm` Priority 4
   的 config router 只构建 `ollama`/`openai` 两种后端——`[llm.dashscope]`/
   `[llm.openrouter]` 段从未被构建;`default_backend = "dashscope"` 静默回落到 openai
   （本机 = 4 月起 403 的 TokenPlan 死端点）。**这就是"产品 CLI 炼化静默 0 产出"的
   完整因果**,也是 bench 一直自带 llm_call 绕过 router 的原因。
2. **Ollama 探活只查 daemon 不查模型。** Priority 3 见 daemon 即选用——本机因实验
   起的 ollama（零模型）劫持了整条链,所有调用 404。应至少校验有可用模型再入选。
3. （用户配置项,非代码）live `~/.radiomind/config.toml` `default_backend = "openai"`
   指向死端点——即使修了 router,默认后端也该切到 dashscope。

## 4. 不做 / 守住
不接 prune_stale（1a 风险结论不变）。不做镜像回流。不在 1b 内修 LLMRouter（缺陷
独立成因,需自己的 audit/scope）。live config 未动（切 default_backend 是用户决定）。
smoke 全程在副本 home,live store 零写入。

## 5. 结论
**燃料闭环成立**: 空 store 一条 `radiomind train` 命令（宿主注入下）走通
补燃料 → 生成数据 → 可训练;消费记录就位为保鲜策略打了地基。LoRA 线现状:
部署链路 ✓（1c）+ 燃料闭环 ✓（1b）;剩余依赖 = LLMRouter 修复后 CLI 独立模式
才能享受同样体验（宿主模式不受影响）。
