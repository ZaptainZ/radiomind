# LoRA 量化损失审计 1a — 链路图 + 损失点证据 + 最小 A/B 设计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-12
> 范围: 只读 artifact/log/code 审计。不训练、不跑大实验、不改代码。
> 背景: benchmark 线全部收口后转产品 backlog 第一项（用户 2026-06-11 裁决）。
> 约束: LoRA must stay（用户 4 月裁决,改进而非弃用）。

## 1. 链路图（现状,code = `src/radiomind/training/lora.py` + `data_gen.py`）

```
~/.radiomind store (786 active memories + habits)
  │ data_gen.py — 纯模板 QA 生成(零 LLM),80/20 真实拆分,严格去重
  ▼
train.jsonl (≥30 例硬门槛;4 月实测 82 train + 20 valid)
  │ train_lora() — mlx_lm Python API,4-bit base,early-stop+回滚(md5 校验)
  ▼
adapter.safetensors (~6MB)                    ←—— ① MLX-direct 推理(质量基准)
  │ export_to_ollama() Step1: mlx_lm.fuse     ←—— 4-bit base 反量化
  ▼
fused/ FP16 safetensors (988MB)
  │ Step2: convert_hf_to_gguf.py --outtype q8_0   ←—— **硬编码 q8_0**(lora.py:369,
  ▼                                                    注释自述: k-quants 需另跑 quantize 二进制)
model.gguf q8_0 (531MB)
  │ Step3-4: Modelfile(FROM gguf) + ollama create
  ▼
ollama: radiomind-personal                    ←—— ② 部署态推理(实测严重退化)
```

## 2. 已知损失点与证据（全部来自 4 月 artifact,`bench/lora_ab/*.json`）

| 环节 | 证据 | 判定 |
|---|---|---|
| 训练数据 | v0.2 已修（80/20 拆分+去重）;val 4.304→0.492 真实下降,early-stop 回滚可用 | **非损失点**（已修复的历史问题） |
| adapter 本体（MLX-direct, 0.5B） | token-overlap: base 0.3455 → LoRA **0.4245（+23%, 5W/2L/1T）**;early-stop 版 +18% | 信号真实存在,**但见 ⚠️ 度量分歧** |
| ⚠️ 度量分歧 | 同一 adapter 用 **qwen-max LLM judge** 重评: **5W/5L/0T 平局**（llm-judge-retrained）;token-overlap 偏好习惯引用的字面重叠 | MLX-direct 的 "+23%" 是 metric-dependent,LLM-judge 口径下未证优 |
| 大 base 适配 | Qwen3-4B 上 LoRA **输给自己 base 2W/7L/1T**（llm-judge-qwen3-4b）——82 例对 4B 太小/秩失配 | "换大 base"缓解方案**在现有数据量下被证伪** |
| fuse（4-bit→FP16） | 与 q8_0 合并观察: 4bit→FP16→q8_0 roundtrip 后 "outputs drift into off-topic stories…no reliable habit citations"（deploy-roundtrip-finding） | **主嫌疑（与下一环节耦合,无法从现有证据分离——正是最小 A/B 要拆的）** |
| GGUF q8_0 转换 | 同上;且 ollama 手测 **5/6 query 超时**,完成的 1 条 overlap −49%（0.378→0.192）,输出漂移示例在档 | 同上;**超时还混入 runtime 因素** |
| Ollama runtime | 5/6 超时无法归因于量化本身（量化不致超时） | 独立疑点（num_ctx/template/0.5B GGUF 推理配置） |

## 3. 三问回答

**Q1 损失发生在哪?** 现有证据只能定位到 **fuse+q8_0 转换的复合 roundtrip**（4-bit→FP16→q8_0 两次量化）,无法分离 fuse 与 q8_0 各自贡献;Ollama 超时是混入的第三因素。训练数据与 adapter 本体排除。**f16 GGUF 从未被实测**——"推荐缓解"只停在 finding JSON 的建议里。

**Q2 f16 能否保住 MLX-direct 效果?** **未测,这正是最小 A/B 的核心问题。** 利好: 转换可手动调 `convert_hf_to_gguf.py --outtype f16`,**零代码改动**即可做实验（q8_0 硬编码只影响产品路径,实验可绕开）。

**Q3 产品默认 vs 实验功能?** 现状已是实验态（`RADIOMIND_ENABLE_LORA=1` 门控,v0.2 起）。**建议维持门控直到 A/B 出结果**: 若 f16≈MLX-direct → 改一行 outtype,LoRA 可升产品路径（MLX-direct 为质量首选,GGUF f16 为跨平台部署）;若 f16 仍崩 → 损失在 fuse,产品定位收窄为 "MLX-direct only"（mlx_lm.server 路线）,Ollama 导出降级为带警告的实验功能。

## 4. 关键盘点事实: **4 月 adapter 已不存在,A/B 必须重训**
- 4 月 adapter 路径 `/tmp/rm-lora-test/...`（artifact 内记载）→ /tmp 已被系统清理;
- `~/.radiomind/models/` 与备份 `radiomind-backup-20260415/dotradiomind/models/` 均为空
  （4 月实验全程在 /tmp,从未落到持久目录——本身就是一个流程教训）;
- 重训成本低: data_gen 纯模板零 LLM,786 条活跃记忆 ≫ 30 例门槛;0.5B 4-bit 训练
  4 月实测 ~5 分钟（MLX, Apple Silicon）。

## 5. 最小可逆 A/B 实验设计（待批,预计半天内）
**固定**: 同一 query set（沿用 4 月 8-10 题 LoCoMo-lite 集 + 相同检索上下文）;
**双指标并报**（token-overlap + LLM judge,因历史分歧）;adapter 落**持久目录**
（如 `~/rm-lora-exp/`,不进 /tmp 不进 iCloud 仓库）。

| 臂 | 路径 | 回答的问题 |
|---|---|---|
| A | MLX-direct base（Qwen2.5-0.5B-4bit） | 基线 |
| B | MLX-direct + adapter | adapter 信号(复刻 4 月) |
| C | fuse → GGUF **f16** → ollama | **Q2 主问题** |
| D | fuse → GGUF q8_0 → ollama | 复现损失(阳性对照) |

判读规则: C≈B → q8_0 是主损失点,产品改 outtype 一行;C≈D≪B → 损失在 fuse,
LoRA 收窄为 MLX-direct;B≈A（judge 口径） → adapter 价值本身待商榷,先解决数据量
再谈部署。D 臂同时记录超时/延迟以分离 runtime 因素（必要时 num_ctx 调参一次重测,
仍属实验内）。**全程零 runtime 代码改动**（f16 手动转换;adapter 重训用现有 CLI）。

## 6. 不做 / 守住
不动 `lora.py` 的 q8_0 硬编码（等 A/B 结果说话）。不换大 base（已被 4B 证据证伪,
除非先扩数据）。不碰 LME-S。训练数据从真实 store 只读生成,训练产物不写入
`~/.radiomind`（沙箱纪律同 bench）。
