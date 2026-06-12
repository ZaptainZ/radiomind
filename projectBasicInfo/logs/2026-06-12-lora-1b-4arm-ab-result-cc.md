# LoRA-1b 四臂 A/B 结果 — "量化损失"被证伪，真凶是 Modelfile；部署链路成立

> 作者: Claude Code (cc) ｜ 日期: 2026-06-12
> 前置: 审计 1a + 用户钉边界（四臂/双指标/超时单列/判读规则）。
> 范围: bench 侧 driver + 实验。零 `src/radiomind` 改动（产品修复待批）。

## 1. 实验设置（按裁决执行）
- **数据**: live store 0 habits（被 14 天过期清空——产品级发现）→ 在 4 月备份副本上跑
  三体炼化铸 6 条真实习惯 → data_gen **114 train / 28 valid**（未改生成逻辑）。
- **训练**: Qwen2.5-0.5B-Instruct-4bit, 150 iters, val 4.344→**0.487**（与 4 月 0.485-0.492
  同带）;adapter 落持久目录 `~/rm-lora-exp/adapters`。
- **部署**: fuse --dequantize（988MB,同 4 月）→ convert f16（994MB）+ q8_0（531MB,
  同 4 月尺寸）→ ollama 注册。
- **评测**: 28 题 valid 留出集（个人 QA,训练未见）,四臂同 prompt;双指标
  （token-overlap + qwen-max pairwise judge vs base）;driver `bench/lora_ab/ab_4arm.py`。

## 2. 中途抓获的两个真凶（比分数更重要）

### 真凶 ①: 裸 Modelfile → 失控生成（4 月"超时+漂移"的真因）
首轮 C/D 大面积"超时"。ollama serve 日志显示单请求 **17,000+ tokens 失控解码
（147 t/s 全速,根本停不下来）**——我们与产品 `lora.py:384` 的 Modelfile 一样
**无 TEMPLATE、无 stop**,`/api/generate` 退化为无终止裸补全。
加上 qwen 模板 + `stop <|im_end|>` + `num_predict 256` 后,**同一模型 1.2s 干净返回**。
> 4 月 deploy-roundtrip-finding 的"q8_0 量化 roundtrip 损失信号、输出漂移、5/6 超时"
> 与此形态完全吻合——**当年很可能冤枉了量化,真凶是 Modelfile**。

### 真凶 ②（次要,harness 级）: 双模型交替 → ollama 换载抖动
四臂交替调用两个 ~1GB 模型导致每题重载超时;改单模型整轮后消失。被杀客户端的
失控请求会继续占 GPU（"Stopping..." 卡住后续）,需重启 daemon 清场。

## 3. 四臂结果（干净轮,28/28 全臂零 runtime failure）

| 臂 | overlap | judge vs base | 备注 |
|---|---|---|---|
| A MLX base | 0.1535 | — | 基线 |
| B MLX+adapter | **0.1767** | **20W/7L/1T**（重复轮 19W/4L/4T、20W/6L/1T,稳定） | adapter 本体有效,judge 口径这次也立住（4 月平局是数据质量问题,新数据 114 例+EVIDENCE 习惯） |
| C f16/Ollama | 0.1760 | 18W/7L/3T | **≈ B** |
| D q8_0/Ollama | 0.1909 | 19W/8L/1T | **≈ B**（overlap 略高属噪声,结论是"≈"非"更好"） |

## 4. 按预设判读规则定性
命中规则 1 的加强版: **`B > A` 且 `C ≈ B` 且 `D ≈ B`** →
- **产品路径成立,且连 q8_0 都不是瓶颈**——修复对象不是 outtype,是 Modelfile。
- 审计 1a 的损失点表更正: ~~fuse+q8_0 复合 roundtrip~~ → **export_to_ollama 的
  Modelfile 缺 TEMPLATE/stop**（量化无罪,fuse 无罪——证据: D 臂 q8_0 与 MLX-direct
  judge 口径等价）。

## 5. 建议（待批,产品侧小修）
**LoRA-1c**: `lora.py` `export_to_ollama` Modelfile 增加 TEMPLATE（按 base 家族,
qwen 系即 ChatML）+ `stop` + `num_predict` 上限 + 单测;顺带产品文档把 LoRA 从
"实验功能"升为"受支持路径"（MLX-direct 质量首选,GGUF/Ollama 部署可用）。
另两个产品 backlog 项: live store 习惯全被 14 天过期清空 → LoRA 燃料供给与过期
策略的矛盾需要产品决策;`radiomind doctor` 可加 "deployed model 失控生成" 检测。

## 6. 诚实边界
28 题模板派生 valid 集,gold 是模板答案（overlap 绝对值低,看差值);0.5B 单 base
单次训练;qwen-max 单 judge。结论支持"部署链路成立",不支持任何跨模型泛化 claim。

## 7. Artifacts
`bench/lora_ab/ab_4arm.py`(driver) / `lora1b-4arm.json`(首轮,含换载伪影证据) /
`lora1b-pass-f16.json` / `lora1b-pass-q8.json`。训练产物在 `~/rm-lora-exp/`
（adapter 11MB + 双 GGUF,持久保存——不再只落 /tmp）。
