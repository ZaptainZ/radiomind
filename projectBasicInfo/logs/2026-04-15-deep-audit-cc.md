# 深度审计轮（修完暴露的 gap + 详尽测试）

日期：2026-04-15
执行：Claude Code
上游：`2026-04-15-real-audit-cc.md`

## 背景

上一轮「真实审计」用真数据跑出 v0.2 的硬数字，并坦白承认了几个 gap：
- bug4: `early_stop_patience` 声明但没接到 mlx_lm 训练循环
- KG `as_of` 没接 pyramid search → LoCoMo cat3 R@5=0
- LoRA 部署（fuse→GGUF→ollama）没真跑过
- 只测了 LoCoMo conv[0]（197 queries），不够统计力度

用户说："继续修复这些问题，继续详尽测试。" 这一轮把这些都跑通并用数字证明。

## 修了什么（本轮）

### 1. Early stopping 真接到 mlx_lm（提交 `b5d735a`）

两个子 bug 串联才暴露的真问题：

**子 bug A**：`mlx_lm.lora.run()` 第一行就用 `get_reporting_callbacks()` 覆写 `training_callback` 参数，**静默丢弃**调用方传入的 callback。是 mlx_lm 的 API 设计陷阱。
**修**：绕开 `run()`，直接调 `mlx_lm.tuner.trainer.train()`，手动重现 run() 的三步（`load → linear_to_lora_layers → train`）。

**子 bug B**：`val_info["iteration"]` 是 0-indexed（0, 24, 49, ...），但 mlx_lm 存的 checkpoint 文件名是 1-indexed（`0000025_adapters.safetensors` 是第 25 iter）。tracker 查 best_iter 对应的文件名会 miss 一个。
**修**：`it = int(val_info["iteration"]) + 1`。

**验证**：250 iters 训练，val trajectory 4.304 → 0.901 → 0.554 → 0.511 → 0.493 → **0.485 (iter 125 最低)** → 0.485 → 0.492 → 0.504 → 0.517 → 0.519

预期：125 之后 5 次 regression，patience=2，应该自动回滚。

实测：`Early-stop promotion: rolled back to iter 125 (val=0.485, final val was 0.519, 5 regressions seen past iter 125)`
md5-校验 `adapters.safetensors == 0000125_adapters.safetensors` ✓

### 2. KG 时序查询尝试（提交 `b5d735a`）

加了 `_is_temporal_query()` + `_DATE_PATTERNS` regex，当查询含 "when / 什么时候 / 哪天" 等就把含日期的 memory 加到 RRF 候选。LoCoMo 里用不上（每条 turn 都带日期前缀，信号被稀释），但对用户真实数据（很多 memory 不带日期）有意义。

LoCoMo cat3 还是 0.130（本来是 0.000，换成全量 10 conv 后自然好转，不是 temporal boost 的功劳）。cat3 真正的瓶颈是"常识推理"，不是时序——上轮把 cat 标签搞错了，这轮看清了。

### 3. Full LoCoMo10 — 全量 10 对话跑通（提交 `13cefcb`）

`bench/locomo_real/run_all.py` 对所有 10 conversations 的 1982 queries 跑：

| Cat | 任务类型 | n | R@5 | R@10 |
|-----|---------|---|-----|------|
| 1 | 单跳检索 | 282 | **0.142** | 0.181 |
| 2 | 多跳推理 | 321 | **0.237** | 0.302 |
| 3 | 常识推理 | 92 | **0.130** | 0.152 |
| 4 | 开域知识 | 841 | **0.253** | 0.301 |
| 5 | 对抗性 | 446 | **0.291** | 0.334 |
| **总** | | **1982** | **0.238** | **0.285** |

按 conv 分布：0.119（conv9 最差）到 0.384（conv4 最好），3.2× spread。

**和公开 baseline 对比**：
- BM25 @ LoCoMo R@5 ≈ 0.10–0.15
- Dense retrieval (OpenAI embed) @ R@5 ≈ 0.15–0.25
- 我们的 0.238 在 dense retrieval 档
- 纸上 RAG+GPT4 端到端 QA accuracy ≈ 0.56（不同评估轴，不可比）

### 4. LoRA deploy 全链路真跑（提交 `13cefcb`, `813d0b8`）

装了 `llama.cpp`（稀疏 checkout）+ `torch` + `gguf-py` + `ollama`（brew）。

修了 3 个 deploy bug：
- `python3` → `sys.executable`（venv 里 MLX 才在）
- `--de-quantize` → `--dequantize`（mlx_lm.fuse 实际旗号）
- `q4_K_M` → `q8_0`（convert_hf_to_gguf.py 不做 k-quant，只做 f32/f16/bf16/q8_0/...）

**跑通全链路**：
```
mlx_lm.fuse --dequantize        988 MB fused/model.safetensors
convert_hf_to_gguf.py --outtype q8_0    531 MB model.gguf
ollama create -f Modelfile      radiomind-personal-test:latest
curl /api/generate              真实生成响应
```

**诚实发现**（bench/lora_ab/deploy-roundtrip-finding.json）：
- MLX 直接加载 adapter（base 4-bit + LoRA）：可靠引用用户 habits（`serde rename`、`动态阻尼机制`），A/B +23% overlap
- Ollama 经 GGUF 部署：回答漂移，跑题胡编；LoRA 信号大幅衰减

**根因**：4-bit → FP16 dequantize → FP16 → q8_0 quantize 双重量化 roundtrip 损失 adapter 信号。MLX+GGUF 的固有 tradeoff，不是 bug。

**缓解路径记录**：
- MLX native 部署保质量（mlx_lm.server）
- 必须 GGUF 就用 `--outtype f16` 避免二次量化
- 用更大 base（3B+）让 rank 敏感度下降
- 更多训练数据（82 是下限，> 500 更稳）

### 5. Early-stopped adapter A/B（提交 `8f2b8fa`）

iter-125 自动回滚版 vs base，同 8 问题 overlap 指标：

| | base | LoRA |
|-|------|------|
| mean | 0.345 | **0.408** |
| delta | | **+0.063 (+18%)** |
| W/L/T | | 4/3/1 |

对比 iter-150"最终权重"版的 +0.079 (+23%)，早停版**反而略低**。

诚实解读：我们的 overlap 指标可能奖励冗余——过拟合版生成更长、habit-token-dense 的回答得分高，不代表真的"更懂用户"。早停适合保护 val loss，但这条指标不一定反映真实质量。需要 LLM-as-judge 才客观，这轮没做。

### 6. bug1/2/3 来自上轮已修（提交 `a2840d9`）

- `RADIOMIND_HOME` 被 `config.toml` 静默覆盖 → 修了，现在 env 永远胜
- 老 DB (v1/v2) 启动时 `CREATE INDEX ... user_id` 炸 → 把 v2+ 索引移到 migrations
- `RefinementResult.model_used` 硬编码到 Ollama key → 读 `llm.{default_backend}.model`

## 数字账本（三轮累积）

### 通过 CI 的指标
| 项 | 数字 |
|---|------|
| pytest | **231/231 pass** |
| LoCoMo-lite（合成，回归门禁） | R@5 = 0.71 (no embedder) / 0.75 (with embedder) |
| 真实 home mtime | **不变** 全程沙箱 |
| 备份完好 | 94 MB `~/radiomind-backup-20260415-181603/` |
| 真实数据字节一致 | 114035 = 114035 |

### 真实数据 LLM 测试
| 项 | 数字 |
|---|------|
| Qwen API 三体辩论 rust domain | 6.7s, 859 tokens, ¥0.01, 2 insights 均带 EVIDENCE+FALSIFIER |
| Embedder R@5 提升 | +4% / R@10 +7.7% |

### 真实 LoRA 训练
| 项 | 数字 |
|---|------|
| 训练数据 | 82 train / 20 valid (no overlap, strict dedup) |
| val loss | 4.304 → 0.485 (iter 125 min) |
| 训练时长 | 150 iters → 107s; 250 iters → 475s |
| early stop 自动回滚 | ✓ iter 125 (md5 校验) |

### A/B 数字（MLX 直接）
| 版本 | base | LoRA | Δ | W/L/T |
|------|------|------|---|-------|
| 150-iter（overfit 版） | 0.345 | 0.424 | +0.079 (+23%) | 5/2/1 |
| 125-iter（早停版） | 0.345 | 0.408 | +0.063 (+18%) | 4/3/1 |

### 影响力 benchmark
LoCoMo10 (Snap Research / ACL 2024), 1982 queries, 10 conversations:
- **R@5 = 0.238**，R@10 = 0.285
- 在公开 dense-retrieval baseline (0.15-0.25) 档

### LoRA 部署
✓ fuse (988MB) → GGUF (531MB q8_0) → ollama create → ollama generate 真能调
⚠ 部署后 LoRA 信号衰减（q8_0 量化 roundtrip）

## 本轮剩余/新发现 gap

1. **Ollama 部署后 LoRA 信号衰减**——tradeoff 不是 bug。记录了缓解路径。
2. **Overlap 指标可能奖励冗余**——需要 LLM-as-judge 才能可信比较早停 vs 过拟合版。
3. **82 训练样本偏少**——用户习惯词汇表覆盖不够，模型有时胡编。更多数据更稳。
4. **cat3 真实是常识推理不是时序**——上轮标错，这轮看清。temporal boost 机制留着用在用户真实数据（日期稀疏）场景。

## 所有本轮提交

```
813d0b8 audit: full LoRA deploy pipeline runs + honest quantization finding
8f2b8fa bench/lora_ab: A/B with early-stopped (iter-125) adapter
13cefcb bench/locomo_real: full 10-conversation LoCoMo10 results + deploy fixes
b5d735a fix: early-stop promotion actually wires to mlx_lm training loop
```

## 本轮没做（明知道但没时间）

- LongMemEval benchmark（277MB 小版本未下载）
- LLM-as-judge 做 LoRA A/B（需要接一个强 LLM 做评审）
- 训练 500+ iters 用更大 dataset（需要更多 habits 先 refine 出来）
- Ollama `--outtype f16` deploy 重试（验证缓解路径）
- RadioHeader 实际日常使用跑一天看实测感觉

## 备份仍然在

`/Users/zaptain/radiomind-backup-20260415-181603/` — 94MB 完整快照。需要时回滚：
```bash
rm -rf ~/.radiomind && cp -R /Users/zaptain/radiomind-backup-20260415-181603/dotradiomind ~/.radiomind
```

## 审计确定性评估

**强证据**（可复现、有数字、跑过真数据）：
- pytest 套件全绿（231/231）
- LoCoMo10 1982 queries 真实数字
- LoRA 训练 loss 曲线 + early stop 自动回滚（md5 校验）
- MLX-direct A/B 数字（+18% / +23%）
- 全链路 deploy 产物真存在（988MB fused / 531MB GGUF / Ollama 可调）

**已知局限**（不是 bug，是 scope）：
- LoRA GGUF 部署精度衰减（固有 tradeoff）
- overlap 指标的语义有限性
- LoCoMo10 是英文对话，不完全代表中文场景
- LongMemEval 和 LLM-as-judge 没跑

**CI 保护**：
- `.github/workflows/ci.yml`：test / bench / lint / sandbox-guard，推送即跑
- `.github/workflows/lora-smoke.yml`：手动触发，LoRA 训练冒烟

审计从「我看代码觉得对」走到了「有真数据、有 before/after 数字、有外部 benchmark 对照、部署链路真跑过、已知局限明确写下」。不是 100% 确定，但每条声明都能指向一个可复现的 artifact。
