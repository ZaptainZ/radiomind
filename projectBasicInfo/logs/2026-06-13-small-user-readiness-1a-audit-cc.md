# SmallUserReadiness-1a — 小用户冷启动失败链路审计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: CLIProductSmoke F2。用户裁决: 只读审计,不改阈值/gate/classifier,不训练,不 benchmark。
> 目标: 判定 F2 是"合理保护"还是"过严阻断",有证据才开 1b。

## 1. 失败链路图（8 条 smoke 样本实测 trace）
```
8 messages
  │ L1 gate (core/gate.py)
  │  ✗ 3 assistant turns 丢弃（role != user 硬过滤）
  │  ✗ 2 user turns 丢弃（"I add..." / "I validate..." 不匹配正则白名单）
  ▼
3 kept memories
  │ detect_domain（关键词子串匹配，5 个生活域）
  │  ✗ parsers / adapter → domain="" （技术内容无任何关键词）
  │  ⚠ network services → "work"（**子串误判: "work" ⊂ "network"**，非真分类）
  ▼
命名 domain = {work} = 1（2 条落空 domain，不计入）
  │ prepare-habits 只炼命名 domain → 只能炼 work（1 条）
  ▼
1 habit
  │ data_gen ~18 examples/habit
  ▼
11 examples
  │ guard: ≥5 habits AND ≥2 domains AND ≥30 examples
  ▼
全部不达 → Refused
```

## 2. 审计四问答案
**Q1 为何 8→3?** 两个独立硬过滤: (a) **所有 assistant turn 丢弃**（`role != user`）;
(b) user turn 必须命中 16 条正则白名单之一（identity/preference/routine/goal/...）。
"For any AI feature I add layered fallbacks"、"I validate inputs defensively" 这种**强持久
习惯陈述被丢,仅因不以白名单动词短语开头**。→ **过滤掉的内容恰恰能产生 habit**。

**Q2 为何只 1 个 domain?** 两层问题: (a) `DOMAIN_KEYWORDS` 只有 health/work/learning/
finance/hobby **5 个生活域,零技术/专业覆盖**——开发者的 parsers/adapter/AI/validation
全部 → domain=""; (b) `detect_domain` 用裸 `kw in text_lower` 子串匹配 → **"work" 误配
"network"**（唯一的"命名 domain"是个 substring 事故,不是真分类）。**不是小样本只有一个
主题,是 classifier 对技术内容近乎全盲 + 子串误判。**

**Q3 ≥2 domains guard 必要吗?** 对小用户/单一强领域用户是**结构性敌对**: 即使写一百条
同领域强偏好,也凑不出第 2 个命名 domain（尤其技术用户因 Q2 几乎全部落空 domain）。
该 guard 的本意是防过拟合,但实现上变成"必须横跨 ≥2 个**恰好被 5 个生活域关键词命中**
的主题"——代理失真。

**Q4 ≥30 examples 是 examples 还是 habit 不足?** examples 从 habit 派生（实测 ~18/habit:
1 habit→11、6 habits→108）。**examples 不足是 habit 不足的下游**,habit 不足是 Q1+Q2 的
下游。三个门槛**同源失败**（gate+domain),不是三个独立信号。

## 3. 判定: **过严阻断,非合理保护**（证据充分,支持开 1b）
- gate 正则白名单丢弃真习惯陈述（Q1）+ domain classifier 技术内容全盲且子串误判（Q2）
  是**设计缺陷**,不是"数据太少"的合理后果。
- 反证"合理保护"说法: 8 条样本里至少 5 条是清晰的第一人称工程习惯,人类一眼能提炼
  ≥4 个 habit;系统因白名单+域盲只留下 1 个。**信号在,是管道漏了。**

## 4. 最小策略候选（待你定,均未实现;1a 只给方向）
按"改动面 × 风险"排序:
1. **train refuse 更明确（最小,纯文案,zero-risk）**: 当 domains=1 但 habits/examples 接近
   阈值时,提示"再添加一个不同主题的记忆即可"——已部分在 1b 做,可强化。
2. **单 domain 允许训练但标 `narrow_adapter`**: 放宽 `≥2 domains` 为"≥2 domains **或**
   单 domain 且 examples 充足",产物标记 narrow。需看单域 examples 多样性是否够（防过拟合）——
   1b 可加只读多样性度量先验证。
3. **domain classifier 修子串误判 + 扩技术域**（中风险,改 classifier,用户明确说本轮不改）:
   `kw in text` → 词边界匹配;DOMAIN_KEYWORDS 补 tech/coding 域。属 F2 的真修,需单独立项。
4. **gate 语义化**（大改,高风险）: 正则白名单 → 轻量分类"这句是否含持久自述"。
   违反"不改 gate",仅记为远期方向。

## 5. 建议
开 **SmallUserReadiness-1b** 做**候选 2 的只读前验 + 候选 1 文案强化**: 先加一个只读
"单域 examples 多样性度量"(不改阈值),证明单域能否安全训练;若能,再做 narrow_adapter
放宽。候选 3/4（classifier/gate 真修）证据已足但改动面大,各自单独立项。**本轮纯审计,
未改任何代码。**

## 6. 不做 / 守住
未降门槛、未改 gate、未改 classifier、未训练、未 benchmark。子串误判 / 技术域缺失虽已
定位,但按裁决本轮不修,记入 1b/独立线候选。
