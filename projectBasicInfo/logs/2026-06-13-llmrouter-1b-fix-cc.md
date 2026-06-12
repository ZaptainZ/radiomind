# LLMRouter-1b — 解析层修复落地（Fix A/B/C/D + 排障追加的 Fix E）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1a 审计设计（a3dbb41）。用户裁决: 按设计严格落地;验证顺序 单测→pack→
> CLI train smoke（不靠宿主注入）;不跑 benchmark;不改 LoRA。

## 1. 实现（`src/radiomind/core/llm.py` + `llm_auto.py`）
- **Fix A 通用 profile 构建**: `_init_backends` 现有 ollama/openai 两段原样,其后遍历
  `llm.*`——非保留键（ollama/openai/models/default_backend）且含 base_url+api_key 的
  section 构建为 `OpenAICompatBackend`,键名即 section 名。防覆盖（`name in self._backends`
  跳过）。→ `default_backend = "dashscope"` 直接命中。
- **Fix B 共享探针**: 模块级 `ollama_ready(host)`（/api/tags 200 **且** models 非空）;
  `OllamaBackend.is_available` 与 `llm_auto._from_ollama`（P3）双路径统一调用——
  双标探活的结构性根除（1a 缺陷 B）。
- **Fix C 兜底可观测**: `generate()` 兜底时 `logging.warning`（每 router 实例每请求名
  一次,`_warned_fallback` 去重）;`_find_available` 改返回 `(name, backend)`;
  全不可用维持 RuntimeError。
- **Fix E（排障追加）: per-profile timeout**。CLI smoke 揭示第四缺陷: 后端写死 45s
  超时（V8.x 按"p99<3s"短调用设计）,炼化级长生成（7836 字符 prompt + 多 stance JSON）
  必超时,再被 trinity `_call_llm` 的裸 except 吞成空 → 0 insights 无声。修法:
  `[llm.<name>] timeout = N` 可配,默认 45 不变（零行为变化）。bench 早已不走此后端,
  影响面仅产品路径。

## 2. Fix D — 本机配置同步（用户授权裁量,备份在档）
`~/.radiomind/config.toml`（备份 `config.toml.bak-20260613-011306`）:
`default_backend` openai→**dashscope**;`[llm.openai]` 加 DEPRECATED 注释（TokenPlan
403 since 2026-04,留作 key 轮换）;`[llm.dashscope]` 加 `timeout = 120`。

## 3. 验证（按裁决顺序,全过）
1. 单测 `tests/test_llm_router.py`（**16**）: dashscope/openrouter 构建+路由、保留键
   不构建、缺 key 跳过、现有两段逐字段回归锁定、共享探针三态（空模型/有模型/连接失败）、
   P3 与 backend 同探针、兜底警告恰一次、default 在场零警告、全不可用 RuntimeError、
   timeout 透传与默认。
2. regression pack 新增 `core:llm-router` → **29 类全绿**;全量 **980 passed**。
3. **CLI train smoke（无宿主注入,空 store 副本,ollama 不在,env 无 key → P4 config 路径）**:
   R1 `prepare-habits: 0 → 5`（general+2/ios+1/rust+2,达阈即停）→ Train 108/Valid 27 →
   habit_ids 5 条输出;R2 `skipped — 5 habits already >= 5`。**LoRAFuel 完成标准在
   纯 CLI 模式下复现 ✓**。
4. 未跑 benchmark（按裁决）。

## 4. 完成标准对照
- CLI refinement/train 不再因 router 缺 profile 静默 0 产出 ✓（smoke 实证）
- bench 注入 llm_call 不受影响 ✓（bench 不经 router;pack/全量套件全绿）
- 现有 openai/ollama 配置兼容 ✓（回归锁定测试）
- pack 全绿 ✓（29 类）

## 5. 遗留（候选,均未动）
- trinity `_call_llm` 裸 except 吞异常（本次排障的减速带,debug 不可观测）——建议
  后续加 logging.debug 级记录;
- `OpenAICompatBackend` 不传 max_tokens（provider 默认上限,长输出场景的下一个潜在坑）;
- cost-tier 模型名（qwen3.6-plus）与 provider 的耦合关系未测试背书。
