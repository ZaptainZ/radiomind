# 2026-05-15 V7 Full-Answer 重测 — 修 truncation bias 后的真实 X/10

## 背景

Codex 审查发现 `bench/end_to_end/run_locomo_mem0.py:564` 用 `answer[:2000]` 截断保存答案。V7 之前 6 次 run 的 strict 6/10 中，许多 qid 的答案在 2000 chars 处被截断（c3 Nate 6/6 都截断），strict 的 body-match 在截断答案上误 lenient（找到 reasoning 中的 gold token 就 PASS，没看到 LLM commit 阶段）。

## 修复

1. **bench** (`run_locomo_mem0.py:564`)：`answer[:2000]` → `answer`（保存全文）
2. **strict_judge**：检测 truncation，没 ANSWER: marker 且明显截断时，只用 last-paragraph 匹配（不用整 body）

## 旧 6 runs 用新严格 strict 重判

| 旧 strict (lenient) | 新 strict (严格防 trunc) |
|---:|---:|
| V7 R1: 6 | 3 |
| V7 R2: 6 | 5 |
| V7 R3: 5 | 3 |
| V7 R4: 6 | 6 |
| V7 R5: 5 | 3 |
| V7 R6: 5 | 5 |

旧 mean 5.5 → 新 mean **4.17**。说明 1/3 旧 PASS 是 truncation 误判。

但只有 run 4（thinking 时长 12127s，答案足够长）真的拿到了完整 commit 并 strict PASS = 6/10。其他 run 因 2000 char cap，LLM 没机会 commit。

## Full-Answer 3 runs（修 bench 后）

| Run | raw orig | strict | 时长 |
|---|---:|---:|---:|
| Fullans R1 | 6/10 | **5/10** | 3862s |
| Fullans R2 | 3/10 (5 SSL) | **5/10** | 3839s |
| Fullans R3 | 4/10 (3 SSL) | **5/10** | 4410s |

**3 runs 完全收敛到 strict 5/10**。

## Per-qid 稳定性（3 fullans runs）

| qid | gold | F1 F2 F3 | PASS/3 |
|---|---|:---:|---:|
| c1 Gina tattoo | A few years ago | F P P | 2/3 |
| c2 John financial | Middle-class or wealthy | F F F | 0/3 |
| c2 Maria community | August 4, 2023 | P P P | **3/3** |
| c3 Joanna big screen | two | F F F | 0/3 |
| c3 Joanna Tilly | stuffed animal Tilly | P P P | **3/3** |
| c3 Nate dragons | dragons | P F P | 2/3 |
| c4 John Seattle | Seattle | F F F | 0/3 |
| c5 Audrey Voyageurs | Voyageurs | F F F | 0/3 |
| c6 John meeting | September 2022 | P P F | 2/3 |
| c9 Calvin/Dave goals | Hard work and determination | P P P | **3/3** |

**3 题 100% stable PASS**：c2 Maria, c3 Tilly, c9
**3 题 67% rotating PASS**：c1 Gina, c3 Nate, c6（LLM commit 方向漂移）
**4 题 0% stable FAIL**：c2 financial, c3 count, c4 Seattle, c5 Voyageurs

按二项分布期望：3 + 3×(2/3) = **5/10** ↔ 与 3 次实测一致。

## V7 真实 X/10 = **5/10 strict**

3 fullans runs 完全一致 5/10 — 修了 truncation bias 后的真实数字。

## 与 baseline 对照

| 版本 | strict | 备注 |
|---|---:|---|
| V6.3 baseline | 4/10 | 单次跑 |
| V6.5.3 | 2/10 | 题干元判定主动伤害 |
| V6.6.p2 (旧) | 4/10 | 旧 lenient strict |
| V6.6.p2 (新严格) | 2/10 | 同样受 truncation 影响 |
| **V7 fullans (3-run)** | **5/10** | +1 over V6.3 |

V7 净 **+1 over V6.3**（不再是之前夸的 +1.5）。

## V7 真实架构层增益（3 fullans 验证）

### 100% 稳定的 3 题

- **c2 Maria August 4, 2023**：V6.3 单次 PASS 但有 SSL judge 风险；V7 evidence candidate "2023-08-04" 稳定输出，judge 健康时稳过
- **c3 Tilly**：V6.3 单次 PASS；V7 proper_noun candidate "Tilly" 稳定排前，3/3 PASS
- **c9 Calvin/Dave hard work + determination**：V6.3 单次 FAIL；V7 evidence 引导 LLM 含 "hard work" + "perseverance/determination"，3/3 PASS

### 67% 轮换的 3 题（LLM commit 方向漂移）

V7 evidence block 让正确选项 salient，但 LLM 的 instinct 偶尔 override：
- **c1 Gina**：V7 给 "a few years ago" 高 conf 候选；LLM 偶尔被 "specific date preferred" 逻辑拉走 → "Feb 8, 2023"
- **c3 Nate dragons**：V7 给 "dragons" 候选；LLM 偶尔被 named series 偏好拉走 → "Lord of the Rings"
- **c6 Sept 2022**：V7 给 date 候选；LLM 偶尔分 planning-date vs meeting-date 时选错 → "August 21, 2022"

### 0% 稳定 FAIL 的 4 题（V7 candidate 层无能为力）

- **c2 financial / c4 Seattle / c5 Voyageurs**：retrieve 层没召回含 gold token 的 memory（candidate 拿不到原料）
- **c3 count "two"**：需 dedup ordinal "third"→2，需要 reasoning 而非 extraction

## 教训（写入方法论）

1. **Bench 默认截断会扭曲评估**：truncated answer 让 strict 判定误 lenient（body 含 gold 但不是 commit）。fix: 保存全文 + strict 区分 truncated 和 committed。
2. **Mean inflation 风险**：6 旧 runs mean 5.5 是 truncation 误判后的 inflated 值；真实 mean 5.0。任何 LLM bench 结果都该 spot-check 答案完整性。
3. **stable vs rotating PASS 矩阵比 mean 更有信息量**：100% stable 才是真架构胜利；67% rotating 是"V7 让选项 salient 但不强制"的真实情况。
4. **V7 真实贡献 = +1 strict over V6.3**：3 个 stable PASS 题里 c9 Calvin 是 V7 新增的（V6.3 FAIL），c2 Maria 和 c3 Tilly 是 inherit V6.3 但 V7 让 judge SSL 干扰更难 false-FAIL。

## Git 状态

```
分支: v7-evidence-candidates
分数最终: strict 5/10 (3 fullans runs 一致)
```

需要 commit：
- bench/end_to_end/run_locomo_mem0.py（answer 不截断）
- bench/end_to_end/strict_judge.py（truncation 检测 + last-para 严格）
- bench/end_to_end/validation/v7-flip10-fullans*.json (3 runs)
- 本 log
