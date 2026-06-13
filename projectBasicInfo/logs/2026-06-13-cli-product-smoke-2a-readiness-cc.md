# CLIProductSmoke-2a — 小用户冷启动端到端复测（产品 readiness 证据）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 范围: 只读/手动端到端 smoke,验证 domain(1c)+单域(1b)+gate(1e) 修复组合后的真实用户
> 冷启动体验。零代码改动。不跑 benchmark。沙箱 /tmp,live store/config 未碰。
> 样本: 24 条接近真实的第一人称 memories（22 user + 2 assistant）,3 主题
> （rust / ios / 工作偏好）,混合 routine/preference/practice 句式。

## 1. 完整路径与结果
| 步骤 | 结果 |
|---|---|
| doctor（fresh） | 7 检查清晰: LLM `dashscope [default], …, openai [deprecated]`（1b F6）、
  radiomind CLI `current entry works`（1b F4 不再误报）、embedding WARN 可操作 |
| ingest 24 | **24 → 22 memories**（2 assistant 硬过滤,22 user 全留——1e practice pattern
  把 "For any…/Whenever…/at every…" 全部召回） |
| status | Memories 22 / **Domains 4**（ios 7, rust 6, software 3, work 1）——1c 技术域生效,
  多 domain |
| search "rust async tokio" | FTS 命中 score 6.78,带 method/score 可解释 |
| **train --prepare-habits --data-only** | prepare 0→**5 habits**（炼 ios+2/rust+2/software+1）
  → **Train 40 / Valid 10**,habits_used=5 domains_used=4 examples=50 → **refused=False,
  narrow_adapter=False = FULL adapter** |

## 2. 完成标准对照（全部命中）
- **每步状态可看懂** ✓: doctor/status/ingest/refuse 输出都明确,下一步清晰。
- **小用户不再因系统漏召卡住** ✓: 22/22 user turns 保留,4 个真实 domain,5 habits,
  50 examples——**冷启动直接走到 FULL 训练数据,既不 refuse 也不 narrow**。
- **失败=数据不足且告知差距** ✓（机制已在,本样本未触发——它成功了）: 8-样本旧 smoke
  仍走 F1 三项 gap;本 24-样本越过门槛。
- **metadata 区分 full/narrow** ✓: domains_used=4 → narrow_adapter=False（full）;
  单域路径会标 narrow（1b 集成测试已证）。
- **readiness 日志** ✓（本文件）。

## 3. 对比: 修复前后的同类小用户
| | 8-样本（1a 时）| 24-样本（2a,全修复后）|
|---|---|---|
| gate 保留 | 3/8（漏 #5/#6 习惯）| 22/24（仅丢 assistant）|
| domains | 1（且 work 是子串误判）| 4（真实分类）|
| 训练 | 三门槛全 refuse | **FULL adapter 数据就绪** |

→ **domain(1c)+单域(1b)+gate(1e) 三修复组合,把"明显信号被系统漏掉而冷启动失败"
彻底转为"信号保全、达标即训练"。** 小用户产品链路确认顺畅。

## 4. 未做（按裁决）
未跑 MLX 真训练/部署——train.jsonl(40/10) 已就绪,且 train→fuse→deploy→4 臂 端到端
早由 LoRA-1b 证明,不重复跑重实验。未 benchmark。

## 5. 结论与下一步候选
**产品冷启动链路 readiness 确认**: 干净环境 → 24 条真实记忆 → FULL 训练数据,每步可读、
失败可操作、成功标 full/narrow。SmallUserReadiness + LoRA 部署/燃料/router/失败可见
一整套产品化修复,组合后经端到端复测有效。
下一步更大方向（待用户定,本轮不开）: ① 安装/包装体验 ② LoRAFuel 默认策略
（何时自动炼化）③ Dream 全域 redundancy ④ LoCoMo current-main refresh。
