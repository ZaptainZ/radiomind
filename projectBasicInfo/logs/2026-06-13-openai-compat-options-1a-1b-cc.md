# OpenAICompatOptions-1a 审计 + 1b max_tokens 可控（timeout 已测/cost-tier 只审）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: LLMRouter-1b/TrinityErrorVisibility-1a 后的最后一块调用参数债。用户裁决:
> 小 scope，只补"长输出 max_tokens 可控 + timeout 测试"，cost-tier 先审不动。

## 1. 1a 审计结论（只读）
| 项 | 现状 | 处置 |
|---|---|---|
| max_tokens | **完全缺失**——ABC + 4 backend 的 generate 均无此参，body 从不设 → 各 provider 用自身默认 completion 上限（DashScope 偏小，长 refinement JSON 会被**截断**，与 45s 超时同族的静默隐患） | **1b 修** |
| timeout | per-profile 已可配（LLMRouter-1b）**且已有 2 测试**（passthrough + default_45） | **已满足，不补** |
| cost-tier × provider 耦合 | `llm.models.<tier>` 是全局单一映射但模型名 provider-specific；router 把解析出的 model 字符串发给**任意**选中 backend → `backend='openrouter'` 配 qwen tier 名会把 qwen id 发到 openrouter | **只审计锁定，不修复**（裁决） |

## 2. 1b 实现（镜像 timeout 模式，默认 None = body 不变 = 完全兼容）
- ABC `generate(..., max_tokens=None)`；4 个实现全部加该参（末位，positional 调用不受影响）。
- `OpenAICompatBackend`: `__init__` 加 per-profile `max_tokens` 默认；generate 里
  `effective = call_param if not None else profile_default`，非 None 才写 `body["max_tokens"]`。
- `OllamaBackend`: max_tokens → `body["options"]={"num_predict": N}`（ollama 的对应字段）。
- `CallableBackend`: 接受但忽略（包裹的 callable 仅 (prompt,system)，宿主自控）。
- `LLMRouter`: `_init_backends` 给 openai 段 + 通用 profile 循环传 `max_tokens=sec.get(...)`；
  `generate(..., max_tokens=None)` 透传给 be.generate。

## 3. 验证
- `tests/test_llm_router.py` 新增 10 测试（共 **26**）: 默认省略字段、call 透传、profile 默认、
  call 覆盖 profile、router 构建 max_tokens、router 透传、ollama→num_predict、callable 忽略、
  **cost-tier verbatim 审计锁定**（断言 qwen 名原样发到 openrouter，文档化非修复）。
- 全量 **1000 passed**；pack 30 类全绿。

## 4. 顺带: 新 logging 立功 + 一个 mock 跟进
TrinityErrorVisibility-1a 的 warning 当场抓到 `test_refinement.py` 的 MockLLMBackend
`generate()` 签名未跟上 ABC（router 现透传 max_tokens → mock 不接 → TypeError 被
trinity 吞空 → 但**这次有 warning**）。修: mock 加 `max_tokens=None`。**契约**: 任何
LLMBackend 子类（含测试 mock）的 generate 必须接受 max_tokens；直接喂 trinity 的
裸 duck-typed mock（`.generate(prompt, system)`）不受影响（trinity 不传该参）。

## 5. 不做 / 守住
不修 cost-tier 跨 provider 耦合（仅测试+审计锁定）。不给 default profile 强加 max_tokens
数值（保持 None=provider 默认，由用户按 provider 在 config 配）。不动 timeout（已足）。

## 6. 遗留（候选）
cost-tier × provider 耦合的真修复（按 provider 分模型映射，或 backend 声明合法模型集）——
需 scope 评估，本次仅锁定行为。
