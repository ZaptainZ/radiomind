# CLIProductSmoke-1a — 空环境→可用 LoRA 的完整产品路径手动 smoke（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 范围: 只读/手动 smoke,零代码改动。从用户视角走完整路径,记录不清晰输出与不可操作
> 的失败信息。环境: 全新 RADIOMIND_HOME=/tmp/rm-smoke-product,复制 live config
> （dashscope 默认）,8 条真实-ish memories,RADIOMIND_ENABLE_LORA=1。

## 1. 走过的路径与结果
| 步骤 | 命令 | 结果 |
|---|---|---|
| init | `radiomind init` | ✓ 清晰 |
| doctor | `radiomind doctor` | ✓ 7 检查,2 WARN（见 F4/F5） |
| ingest | `radiomind ingest memories.jsonl` | 8 条 → **仅 3 memories**（F2） |
| status | `radiomind status` | ✓ 但 3 memories 只 1 命名 domain（F2） |
| train --prepare-habits --data-only | 同上 | prepare 0→1 habit,**Refused: need ≥30 examples**（F1） |
| deploy | `radiomind deploy` | ✓ 失败信息清晰: "No trained adapter found. Run 'radiomind train' first." |
| search 关键词 | `radiomind search "retry backoff"` | ✓ FTS 命中 score=1.02 |
| search 自然问句 | `radiomind search "how do I build network services"` | ✗ **No results found**（F3） |

## 2. 核心产品答案
**一个真实用户能否从空环境走到可用 LoRA？**
- **数据充足时: 能。** 已由 LoRAFuel-1b（746-memory 备份 → 5 habits → 108/27 → 训练）
  与 LoRA-1b（真实 train→fuse→deploy→4 臂）端到端证明。
- **小数据量（本次 8 条）: 不能,但每个卡点现在都"明确失败"而非静默。** 卡在三重门槛
  的合取,且上游有放大效应。

## 3. 发现（按产品严重度排序）
**F1 — 门槛对小用户过高（最关键,体验断点）**
data_gen 三门槛是合取: ≥5 habits **且** ≥2 domains **且** ≥30 unique examples。
8 条 memories 走完只够 1 habit / 11 examples。失败信息准确但**不可操作**——没告诉
用户"还差多少、怎么补"（如"再积累 ~N 条不同领域的记忆,或 ingest 更多历史"）。
prepare-habits 已尽力（炼出 1 个）但天花板在数据量,不在炼化。

**F2 — ingest L1 gate 激进 + domain 稀疏（F1 的上游放大器）**
8 输入 → 3 memories（assistant turns 被丢 + gate 过滤）;且 parser/adapter 两条
落 `domain=?`（空）,status 只认 1 个命名 domain "work"。→ 直接撞 F1 的"≥2 domains"。
用户视角: "我明明输入了 8 条有信息的话,为什么只记了 3 条、只算 1 个领域?" 无解释。

**F3 — 无 embedder 时自然语言检索静默失空（高频体验坑）**
"how do I build network services" → No results;但 "network" / "retry backoff" FTS 命中。
embedder 未装时只有词面匹配,自然问句的 "how do I" 稀释命中。doctor 有 WARN 但
**search 本身零提示**——不引导"装 embedder 或换关键词"。用户最常做的就是问句式查询。

**F4 — doctor "radiomind CLI not on PATH" 误导**
通过 venv 的 radiomind 脚本正常运行时,doctor 仍 WARN "not on PATH"（它查 system PATH）。
正在用的入口可用却被警告,降低 doctor 可信度。

**F5 — `python -m radiomind` 不可用**
无 `__main__.py`;只能用 console script `radiomind`（pyproject entry point）。文档/新手
直觉常试 `python -m`,失败信息是 Python 的通用报错,不友好。

**F6（次要）— doctor/status 把死 openai 列在 LLM 后端首位**
"LLM backend — openai, dashscope, openrouter"——openai 是已 DEPRECATED 的死端点却列首,
未标记不可用/默认。可读性: 应标出 default 与活性。

## 4. 哪些做得好（确认产品基础已立）
- 失败信息**多数可操作**: deploy 无 adapter、prepare 不足、refuse 原因都明确。
- LLMRouter-1b 生效: doctor/status 正确列出 dashscope/openrouter,默认 dashscope。
- prepare-habits（LoRAFuel-1b）真触发并如实报告 0→1 + 失败原因。
- FTS 关键词检索可用且带 score/method,可解释。

## 5. 建议（待你定优先级,均未实现）
- **CLIProductSmoke-1b（UX 修补候选,按 F 严重度）**:
  - F1: refuse 信息升级为可操作——"还差 X habits / Y domains / Z examples;建议 ingest
    更多历史或 `radiomind learn`"。
  - F3: search 空结果且 embedder 未装时,提示"未装 embedder（仅词面匹配）,试关键词或
    `pip install radiomind[embedding]`"。
  - F4: doctor PATH 检查改为"当前入口是否可用",或区分 system-PATH vs venv-script。
  - F6: doctor/status LLM 行标出 default + 跳过/标记死端点。
- F2 属架构语义（gate 阈值 / domain 分类),不在 UX 修补范围,需单独评估。

## 6. 不做 / 守住
本轮零代码改动。未跑 benchmark。smoke 全程在 /tmp 沙箱,live store/config 未碰。
