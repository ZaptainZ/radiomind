# 2026-04-16 — LongMemEval E2E 优化全量实验

## 背景
v0.2 审查后，需要量化 RadioMind 在主流记忆基准上与 MemMachine / Mem0 的差距，并逐项优化追齐。
用户要求：尝试 GPT-4o（Codex OAuth）；其余全部修正、优化。

## 目标
端到端 LongMemEval oracle（n=120，stratified×6 类）上把 overall accuracy 从 baseline 0.517 推到尽可能高。

## 方法与每步增量
- baseline (qwen-turbo + FTS+vector): 0.517
- +cross-encoder reranker (BAAI/bge-reranker-v2-m3): 0.558 (+4.1)
- +contextualized retrieval（nucleus+邻接 turn，必须 nuclei-first 排序否则退化）: 0.575 (+1.7)
- +KG 桥接进 pyramid（bitemporal triples, entity 回查 memory）: 0.583 (+0.8)
- 答题模型 qwen-turbo → qwen-plus: 0.617 (+3.4，最大单项)
- +qwen-max + query rewriter + 会话日期注入 content/prompt: 0.608 (-0.9，轻微回退)

## 修改文件
- `src/radiomind/storage/reranker.py`（新）：cross-encoder 封装
- `src/radiomind/storage/query_rewriter.py`（新）：LLM rewriter + 磁盘缓存
- `src/radiomind/storage/pyramid.py`：`_kg_candidates` + `_expand_with_context`（nuclei 优先）
- `src/radiomind/core/mind.py`：KG 初始化前置于 PyramidSearch，habits 注入
- `src/radiomind/hooks/habit_pusher.py`（新）：Plan C 宿主记忆写入 + 幂等 hash marker
- `src/radiomind/meta/profiles.py`：Plan A digest 融合 habits
- `src/radiomind/cli/main.py`：LoRA train/deploy 隐藏在 `RADIOMIND_ENABLE_LORA=1` 后
- `bench/end_to_end/run_longmemeval.py`：stratified sample、会话日期注入、`--rewriter` 旗标、系统代理绕过、gold_str UnboundLocalError 修复

## 遇到的问题
1. **contextualized retrieval 初始 acc=0.000**：context turns 挤掉 nuclei，`results[:K]` 返回全是 context。修复：严格 `nuclei + context_adds` 拼接。
2. **qwen-max 最终跑全部 `Connection refused`**：macOS scutil 级系统代理（Surge 127.0.0.1:8234）在进程停了之后被 Python urllib 自动读取。修复：`urllib.request.build_opener(urllib.request.ProxyHandler({}))`。
3. **reranker 下载失败**：sentence-transformers HEAD 检查走系统代理。修复：`HF_HUB_OFFLINE=1`。
4. **Codex OAuth 无 API 额度**：ChatGPT Plus OAuth token 能到 api.openai.com 但 quota=0，GPT-4o 实验无法进行。
5. **结题后续 ablation 失败**：`tokenizers` 依赖缺失（可能被 pip cache 清理），加上 Surge 端口未监听导致 pip 无法联网补装。Ablation 未完成。

## 结论
- 默认推荐配置：qwen-plus answer + reranker + context + KG + 会话日期（预估 ~0.63）。
- 查询重写 (`[retrieval.query_rewriter] enabled = false`) 默认关闭：paraphrase 噪声伤害 single-session-preference 类查询；只在 accuracy > latency 时开启。
- 与 MemMachine SOTA (0.917 on LoCoMo) 仍差约 30 pt，后续方向：agentic 多轮检索、替换 MiniLM embedder、session-timestamp 结构化检索。
- LoRA 已从普通用户视野隐藏，Qwen3-4B 上实测负向，保留内部实验入口。

## 输出物
- `bench/end_to_end/lme-e2e-n120-*.json`（6 个进度节点 JSON）
- commits `7d5e183`..`c18e20f`
