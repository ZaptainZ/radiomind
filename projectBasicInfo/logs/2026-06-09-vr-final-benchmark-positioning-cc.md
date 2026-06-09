# VR-final — 诚实 benchmark positioning update（口径 A）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-09
> 范围: 纯文档口径更新。不改 runtime、不跑 benchmark、不开 helper、不做 self-consistency。
> 前置: 整条 VR 测量线（VR-1~4b）已结案。

---

## 1. 背景
VR 测量线结论稳定: current-main 诚实中心 **0.91 ± 0.01**（same-arch 3-run）;
历史 0.930（V6.1.1 单跑）是 lucky 上沿,非中心。README 此前 headline 仍以 0.930 为代表性
现状,会持续误导。本步把对外口径改诚实,不删历史、不把 0.91 写成失败。

## 2. 三层口径（统一写入所有文档）
1. **Current main**: LME-S same-arch 3-run = **0.91 ± 0.01**（min 0.90 / max 0.92）,
   Mem0-compatible 单 answer + 单 judge,deepseek-v3.2 / gpt-4o judge。= 稳定中心 / 常驻分数。
2. **Historical high**: V6.1.1 单跑 **0.930**（2026-05-10）= lucky 上沿单跑,标注非 current 中心。
3. **vs SOTA**: current 中心距已发布 SOTA 0.930 约 2pt,≈1/10 推理成本,+23pt over Mem0 0.680;
   同组合 favorable 单跑能 touch 0.93,但诚实中心是 0.91。

## 3. 改动文件
- `README.md`: badge（V6.1.1 0.930 historical → current-main 0.91 ± 0.01）;headline 三层口径;
  Validated performance 段改为"current-main 中心表"在前 + "历史单跑高点表"在后（标 lucky upper-tail）;
  qtype 表标注为 historical V6.1.1 单跑;新增"突破中心需架构提升,非测量技巧"段。
- `README_zh.md`: 同 README 全部对应改动（badge / headline / 性能验证段 / qtype 标注 / 路径段）。
- `RELEASE.md`: TL;DR 改为 current-main 0.91 ± 0.01 为 standing score + historical highs 区分;
  表格加表头"Historical single-run highs (provenance, not standing scores)" + 补 V6.1.1 0.930 行
  标 lucky upper-tail。
- `01_PROJECT_OVERVIEW.md`: 北极星"当前状态"更新为 0.91 ± 0.01 已解析 + 下一步架构提升线门槛。
- 本 log。

## 4. 完成标准对照
- ✅ README headline/badge 不再以 0.930 暗示代表性现状（badge = current-main 0.91 ± 0.01）。
- ✅ 明确 current-main line: 0.91 ± 0.01（same-arch 3-run）。
- ✅ historical 0.930 保留,标 historical high / lucky upper-tail single run。
- ✅ 明确 0.930 不是 current center（envelope mean 0.90 / median 0.92 / max 0.93 佐证）。
- ✅ LoCoMo 仍 historical-only（未动其段落）。
- ✅ 写清: 超过 0.92 需开架构提升线,先找 ≥2 同机制 cohort。

## 5. 不做（守住）
不改 runtime / 不跑 benchmark / 不开 helper / 不做 self-consistency /
不把 stability-adjusted（0.91 band）冒充成"比 SOTA 高"或改写单跑协议。

## 6. 下一步（B 线,待用户立项）
架构提升线: 针对 unstable qid（answer-gen 对同一检索表述不稳 + 部分检索/记忆质量）
找 ≥2 同机制 cohort,按 DEV_WORKFLOW §3 修复门槛立项。这是唯一不作弊把中心推过 0.92 的路径。
本 positioning update（A）完成后即可择机开 B。
