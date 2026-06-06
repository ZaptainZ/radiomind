# VR-3a — stability report 只读设计 audit

> 作者: Claude Code (cc) ｜ 日期: 2026-06-06
> 方向（用户明确）: **先做 n-run reporting,不做 self-consistency**。先把测量口径稳住,
> 才知道架构真实水平是否接近 SOTA。范围: 只读设计,不实现、不跑 benchmark、不改 runtime。

---

## 1. 目标
建立不作弊的 stability report:
> Mem0-compatible single-run scores over repeated runs: mean ± std, plus per-qid mode.
仍是原协议（每 run = 单 answer + 单 judge）,只是对多个 run 做统计,不改单次评测协议。

## 2. 关键前提审计: 哪些历史 artifact 可聚合？

stability report 只在 **same qid set + same order** 的 artifact 间有效。盘点结果:

**Cohort A（可用,9 文件,set `782b2daa` / order `e88c12d2`,全 deepseek-v3.2 + gpt-4o judge）:**
| acc | file |
|---|---|
| 0.93 | lme-s-n100-2026-05-26 |
| 0.91 | lme-s-n100-2026-06-04-baseline（current-main） |
| 0.93 | lme-s-n100-v6.1.1 |
| 0.92 | lme-s-v82-1-n100 |
| 0.92 | lme-s-v822a-n100.judge-fixed |
| 0.92 | lme-s-n100-v5 |
| 0.89 | lme-s-n100-v6.2.2 |
| 0.86 | lme-s-v822a-n100 |
| 0.82 | lme-s-n100-v4 |

（另有 cohort 09c71731 = 不同 qid 集/混 gpt-4o-answer,**不与 A 混用**。）

**致命 caveat（schema 必须编码）**: Cohort A 的 9 个是**不同架构版本各跑 1 次**,
**不是同一架构的重复**。所以:
- 它们的 mean/std 是 **cross-version envelope**（版本差 + 采样噪声混合）,
  **不是纯 run-to-run 采样 std**。
- 真正的"同架构 stability std"需要 current-main 跑 **k 次重复**（VR-3 尚未授权的新 n=100）。
  目前每版本 N=1,**无同架构重复**。
- 但 **per-qid pass-rate over the 9 runs 仍有用**: 9/9 pass = 稳健解决;
  ~5/9 = unstable（无论来自版本还是采样,都是脆弱题）。这直接产出 unstable-qid table。

→ VR-3 工具必须把"跨版本包络"和"同架构 stability"**当两种东西**,标签分明。

## 3. 三种 score 口径（必须分清,不可混用 / 不可冒充对外）
| 口径 | 定义 | 用途 |
|---|---|---|
| **single-run Mem0-compatible** | 1 run = 单 answer + 单 judge,逐字原协议 | 唯一对外 SOTA headline |
| **multi-run stability estimate** | 同 qid+order **同架构** k runs 的 mean±std + per-qid mode | 内部判断真实水平（**需新重复,当前缺**） |
| **cross-version envelope** | 同 qid+order 但**不同版本** runs 的分布 | 仅描述性上下文（历史区间,**非 stability**） |
| ~~self-consistency adjusted~~ | （暂不做,VR-3 不含） | — |

**铁律**: 后三者都不得冒充 single-run Mem0-compatible headline;报告时显式标注口径与
是否同架构。

## 4. stability report schema（VR-3b 实现目标）
输入: N 个 artifact 路径（工具须先校验 **same qid set + same order**,不一致直接报错列出差异）。
可选 `--cohort-label` 与 `--same-arch`(bool,默认 false → 标 envelope,不标 stability std)。

输出 `stability.json` + `stability.md`:
- `runs[]`: {file, acc, answer_model, judge_model, n}
- `aggregate`: {n_runs, mean, std, min, max, median, label: "stability"|"cross-version-envelope"}
- `per_qid[]`: {qid, qtype, pass_rate(over runs), mode_verdict(P/F), n_pass, n_runs, stable(bool)}
- `unstable_qids[]`: per_qid 里 0<pass_rate<1 的,按 |pass_rate-0.5| 升序（最摇摆在前）
- `by_qtype`: 每 qtype 的平均 pass_rate
- `family_summary`: stable-pass / stable-fail / unstable 三类计数
- `placement`（可选,给单个 target run,如 current-main）: 该 run 的 acc 在分布里的分位
  + 是否 ≥ max（lucky high）/ ≤ min（unlucky low）

## 5. VR-3b 实现设计（纯 artifact parser,不跑 benchmark）
新增 devtools 子命令:
```
python -m bench.end_to_end.devtools stability-report \
  --artifacts run1.json run2.json ... --out reports/stability [--same-arch]
```
- 复用 PX 的 dispatch 风格;纯函数 `build_stability_report(runs, same_arch) -> dict` +
  `render_stability_md` + `write`。
- 校验: same qid set + order,否则 hard fail 并列出 set/order 差异。
- 加 deterministic 测试（小 fixture: 3 个 mini per_query,验 mean/std/mode/unstable/
  set-mismatch hard fail）,挂 regression pack。
- 不碰 src/radiomind。

## 6. VR-3c 验证计划（实现后,纯回放,不跑新 benchmark）
对 Cohort A 9 文件跑 stability-report（`--same-arch=false` → cross-version envelope）:
- 预期能回答: current 0.910 是否落在历史区间内（肉眼: 区间 0.82–0.93,current 0.91 偏中上）;
  v6.1.1 0.93 是否是 high-end（与 05-26 并列最高 → 很可能 lucky high）;
  哪些 qid 跨 9 run unstable（= 9ee3ecd6 类）。
- **明确不声称同架构 std**（cohort 混版本）。若要纯 stability std → 需另授权 current-main
  k×n=100 重复（VR-3 之后再议）。

## 7. 暂不做
answer self-consistency、N-judge、改 prompt/helper、README current score、新 n=100 repeat。

## 8. 进度 / 下一步
- [x] VR-3a 设计 + cohort 审计（发现 9 文件同题集同序,但跨版本——schema 据此分 envelope vs stability）。
- [ ] VR-3b 实现 `stability-report`（纯 parser + 测试）。
- [ ] VR-3c 回放 Cohort A → cross-version envelope + unstable-qid table。
- [ ] （之后再议）current-main k×repeat 取真 stability std。
