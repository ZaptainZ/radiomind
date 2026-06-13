# SmallUserReadiness-1c — domain classifier 确定性修复（word-boundary + 最小技术域）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1a 定位 detect_domain 两缺陷（子串误判 + 技术域全盲）。用户裁决: 只做确定性修复,
> 不碰 L1 gate regex、不做 LLM 语义分类、不调 habits/examples 门槛、不 benchmark。

## 1. 改动（`src/radiomind/core/gate.py`）
- **子串误判修复**: `detect_domain` 的 `kw in text_lower` → `_kw_matches`: ASCII 关键词
  用 `\bkw\b` 词边界（`"work"` 不再命中 `network`/`workflow`/`workout`）;CJK 关键词无
  词边界,保留子串匹配。多词/连字符短语（"circuit breaker"/"fine-tune"）经 re.escape 仍
  按词边界短语匹配。
- **扩 5 个最小技术域**: software（parser/adapter/refactor/接口/重构…）、ios（swift/xcode…）、
  rust（cargo/borrow/serde…）、networking（network/retry/backoff/circuit breaker/代理…）、
  ai（llm/embedding/fallback/inference/微调…）。**刻意窄**——覆盖 1a 样本形态,非完整分类学。
  移除易误配的 "ai"/"ml"/"api"/"function" 裸词,保留高信号词。

## 2. 验证
- `tests/test_domain_detect.py`（12）: network/workflow/workout 不再误判 work、真 work 仍命中、
  parsers/adapters→software、retry/circuit breaker→networking、ai inference→ai、rust/ios、
  生活域不受影响、无关键词返空、CJK 子串仍匹配。pack 新增 `core:domain-detect` → **34 类全绿**;
  全量 **1034 passed**（无回归——无旧测试依赖子串误判行为）。
- **8 样本 re-trace（CLI status）**: 3 kept → **domain_count 1→2**（software ×2 + networking ×1,
  真实分类），告别 1a 的单个误判 "work"。所有技术内容正确落域。

## 3. 结论: domain 修复有效,下一个瓶颈是 L1 gate
domain 层已修——技术内容能落对域,小用户更易达 ≥2 domains 或得到准确 single-domain
（喂 1b narrow 判定）。**但 8 样本仍只有 3 条进入分类,因 L1 gate 丢了 5 条**（3 assistant
硬过滤 + 2 user "I add"/"I validate" 不匹配 16 条正则白名单——1a 已记）。即: **8→3 的
保留率是当前冷启动的下一个、也是最后一个结构瓶颈,根因在 gate regex 白名单的召回,
不在 domain。** gate 语义化属更大改动,留 SmallUserReadiness-1d / 单独审计。

## 4. 完成标准对照
- network 不再误判 work ✓ / workflow/workout 不误判 ✓
- 技术内容落技术域 ✓（software/networking/ai/rust/ios）
- domain_count 较 1a 改善 ✓（1→2,且从"误判"变"真实"）
- 单测 + pack + smoke 通过 ✓（1034 / pack 34）
- 仍不足时结论写清: domain 修复有效,下一瓶颈是 L1 gate ✓（本节）

## 5. 不做 / 守住
未改 L1 gate regex、未做 LLM 语义分类、未调 habits/examples 门槛、1b narrow 规则保留、
未训练、未 benchmark。技术域刻意保持最小,不追泛化。
