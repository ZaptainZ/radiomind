# LoRA-1c — export_to_ollama Modelfile 修复 + 状态升级为 supported/opt-in

> 作者: Claude Code (cc) ｜ 日期: 2026-06-12
> 前置: LoRA-1b 四臂 A/B（量化无罪,真凶=裸 Modelfile）。用户裁决: 1c 直接修
> （bug 非研究）;短 smoke 即可不重跑大 A/B;状态改 supported but opt-in;
> 习惯燃料问题另开 LoRAFuel-1a 不混批。

## 1. 修复（`src/radiomind/training/lora.py`）
- 新增纯函数 `modelfile_content(gguf_path, mlx_base_model, num_predict=512)`:
  ChatML TEMPLATE（System/Prompt 槽位）+ `stop <|im_end|> / <|im_start|> /
  <|endoftext|>` + `num_predict 512` + 原有 temperature/SYSTEM 行。
  qwen/ChatML 是唯一受支持 recipe;docstring 写明扩 base 家族需先扩映射,
  否则部署模型会退回裸补全。
- `export_to_ollama` 的 Modelfile 写入改为调用该函数（删除裸 FROM 三行体）。

## 2. 验证
- `tests/test_lora_modelfile.py`（6,含"防退回 4 月裸 Modelfile"回归断言）;
  regression pack 新增 `training:lora-modelfile` → **27 类全绿**;全量 953 passed。
- **Ollama smoke（用产品函数生成的 Modelfile 建模型）**: f16 GGUF,
  `radiomind-1c-smoke` → 1.28s 返回,eval_count=7,干净终止,无失控——对照修复前
  同一 GGUF 单请求 17k+ tokens。smoke 模型已删,不留垃圾注册。

## 3. 状态升级（CLI 文案,gate 保留）
`train`/`deploy` 文档与 gate 提示从 "[EXPERIMENTAL]" 改为 **"[SUPPORTED, OPT-IN]"**;
删除已被翻案的 "Ollama GGUF deploy measurably degrades quality (roundtrip)" 声明,
替换为 1b 重新归因 + 证据指针。维持 opt-in 的理由如实写入: (a) 4B 级 base 在当前
数据量下仍输（llm-judge-qwen3-4b 证据不变）;(b) 训练需 ≥5 live habits,而 14 天
零命中过期可清空燃料（LoRAFuel-1a 待开）。

## 4. 不做 / 守住
不重跑大 A/B（按裁决）。不默认开启 LoRA。不动习惯过期策略（LoRAFuel-1a 范畴）。
非 ChatML base 家族不假装支持。

## 5. LoRA 部署链路线 — 完成
审计 1a → 四臂 1b（翻案）→ 1c（修复+升级）闭环。下一条待开: **LoRAFuel-1a**
只读审计（习惯过期策略 × 训练消费记录 × 何时触发炼化）。
