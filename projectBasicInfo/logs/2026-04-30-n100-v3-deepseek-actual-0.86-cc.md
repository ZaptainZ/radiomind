# 2026-04-30 n=100 v3 实测：0.860（不是预测的 0.95）

## 背景

2026-04-27 跑了两轮分层 stress test（20×2，从 79 v2-PASS 中独立采样），
两轮一致 5% 回归率。基于此外推 n=100 投影 **0.95**：

```
原 79 PASS × 95% = 75 仍 PASS
20 / 20 v2 错题翻正 = 20 PASS
75 + 20 = 95 / 100
```

为锁定数字，部署到远端 macbook-pro 跑 n=100 v3 全量。

## 部署

- 远端：macbook-pro (Tailscale 100.70.180.78, M-series macOS 26.2)
- Python 3.13.12 / venv（uv 安装失败因网络代理，直接用 pip）
- git push 137 commits → remote git pull
- scp `~/.radiomind/config.toml`（API key），纠正 path 大小写
- scp `longmemeval_s_cleaned.json`（278MB，HuggingFace cache）
- nohup + python3 -u 后台跑

配置：
- answer = deepseek-v3.2 / dashscope
- judge = gpt-4o / openrouter
- reranker = on
- temporal_math = off
- agentic = off

## 实测结果

**0.860（86 / 100），20h 用时**

```
[10/100] acc=1.000  t=7368s
[20/100] acc=1.000  t=14581s
[30/100] acc=0.967  t=21221s
[40/100] acc=0.950  t=27942s
[50/100] acc=0.920  t=34902s
[60/100] acc=0.917  t=42457s
[70/100] acc=0.914  t=49846s
[80/100] acc=0.900  t=57276s
[90/100] acc=0.856  t=64730s
[100/100] acc=0.860  t=72221s
```

按 qtype：

| qtype | n | acc |
|---|---:|---:|
| single-session-assistant   | 16 | **1.000** |
| knowledge-update           | 17 | 0.941 |
| single-session-user        | 16 | 0.938 |
| single-session-preference  | 16 | 0.875 |
| multi-session              | 18 | 0.722 |
| temporal-reasoning         | 17 | 0.706 |

## 为什么投影 9pt 偏高？

5% 副作用率成立的前提是**新 sample 的 qtype 分布与 stress test sample 同
质**。但实际：

- stress test 的 79 v2-PASS 里：multi-session 12 题、temporal-reasoning 12 题
  （单类 occupancy ≈ 15% × 79）
- v3 的 stratified n=100：multi-session 18 题（18%）、temporal-reasoning
  17 题（17%）
- 这两类正是 RadioMind 当前最弱的（acc=0.722 / 0.706）
- v3 给这两类更高占比 → 整体被拉低

数学上：
- 假设其他 4 qtype 均值 ≈ 0.94，多/时 2 类均值 ≈ 0.71
- v3 实际 0.34 加权多/时 + 0.66 加权其他 = 0.34×0.71 + 0.66×0.94 ≈ 0.86 ✓

stress test 的 0.30 加权多/时 + 0.70 加权其他 ≈ 0.71×0.30 + 0.94×0.70 = 0.87
而我们在 stress test 上看到的是 0.95，说明 stress test 那 40 道里恰好把
multi/temporal 的难题都避开了。

**教训**：5% 副作用率是局部信号，不能直接外推到全样本，必须让 stress
sample 的 qtype 分布 = 目标 sample 的分布。

## 14 道失败分析

| qtype | qid | gold | model | 失败模式 |
|---|---|---|---|---|
| knowledge-update | 031748ae_abs | "info not enough" | 5 | 应 abstain 没 abstain |
| multi-session | **d851d5ba** | $3,750 | $2,750 | **class-aware dedup v2 修过，v3 又破** |
| multi-session | c18a7dc8 | 7 | 0 | age_interval skill 输出 0 |
| multi-session | d3ab962e | 8 miles | 45 miles | 数值聚合溢出 |
| multi-session | gpt4_ab202e7f | 5 items | 4 items | 漏 1 件 |
| multi-session | bb7c3b45 | $300 | abstained | 过 abstain |
| pref | d6233ab6 | user-anchored | "no info" | B3 anchor 没触发 |
| pref | 95228167 | 偏好特化 | 通用建议 | B3 anchor 没触发 |
| user | 29f2956b_abs | "did not mention" | 30 min | 应 abstain 没 abstain |
| temporal | b46e15ed | 2 | abstained | 过 abstain |
| temporal | 6e984301 | 3 | 9 weeks | event_interval 误算 |
| temporal | gpt4_fa19884d | bluegrass+banjo | abstained | 过 abstain |
| temporal | **370a8ff4** | 15 | 11 weeks | **errata（应被过滤）** |
| temporal | gpt4_59149c78 | Metropolitan Museum | City Art Museum | 实体错配 |

**关键问题：**

1. **`d851d5ba` 在 v3 seed 又失败**：之前 v2 的 commit `836c78e`
   class-aware dedup 让它通过了。v3 哪里破？需要诊断：
   - 同样的 charity bake-sale memory 是否仍正确入库到 charity_donations？
   - regex 抽取器是否触发？
   - 求和是否仍调用 cardinal cache？
   
   不能只是 "上次看着对就行了" — 需要 deterministic regression test。

2. **errata `370a8ff4` 没被主 bench 过滤**：只有
   `regress_activated_channels.py` 读 `dataset_errata.json`。需要把同样的
   skip 逻辑加到 `run_longmemeval_mem0.py`，否则每次 n=100 都白损 1 道。

3. **abstain calibration 双向出错**：3 道应 abstain 没 abstain（031748ae_abs
   29f2956b_abs，加 1 道 multi-session）+ 3 道不该 abstain 却 abstain
   （bb7c3b45, b46e15ed, gpt4_fa19884d）。净 0 但损 6 道。说明 B4
   PREMISE-VERIFICATION 规则过松和过紧都有，不是单向偏倚。

## 修文档（去掉投影 0.95，只写 0.860）

- `README.md` / `README_zh.md`：表格 0.860（取代 ~0.95），加 qtype 分布表
- `RELEASE.md`：TL;DR 改 0.860，benchmark 表对应一行更新，known issues
  整段重写（增加 d851d5ba 复发、errata filter、multi/temporal 迭代等）
- `projectBasicInfo/01_PROJECT_OVERVIEW.md`：n=100 v3 实测段落

## 下一步候选

1. **`d851d5ba` 决定性修复**：写 deterministic 单题测试 →
   找到为什么 v3 又错 → 修真正的根因
2. **errata filter 移植到主 bench**：1 行小改动，每次 n=100 多 1 pt
3. **multi-session + temporal 架构迭代**：当前 acc=0.706/0.722，
   是迭代密度最高的设计面
4. **多 seed n=100**：跑 3 个 seed 取中位 ± stddev，量化 0.860
   本身的方差（怀疑 ±2-3 pt）

## 修改文件

- `bench/end_to_end/lme-s-n100-v3-deepseek-judge4o.json`（结果 JSON, 60KB）
- `bench/end_to_end/lme-s-n100-v3.ckpt.jsonl`（checkpoint，留存于远端）
- `README.md` / `README_zh.md`
- `RELEASE.md`
- `projectBasicInfo/01_PROJECT_OVERVIEW.md`
- 本日志
