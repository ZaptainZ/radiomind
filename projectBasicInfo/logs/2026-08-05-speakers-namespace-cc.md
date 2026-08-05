# 2026-08-05 Speaker identity（声纹身份）namespace — migration v7 + SpeakerStore + CLI

> 设计方案（含取舍与调研依据）在 HackWare `projectBasicInfo/lifelog-identity-design.md`。
> 本文只记 RadioMind 侧的实现。分支 `feat/lifelog`，机器 MBP16。

## 背景
生活日志原来的"对方甲/对方乙"是 Omni 每 7 分钟一个 chunk 现编的音色标签，跨 chunk 都不稳定；
声纹向量算完即扔，没有任何跨天累积。方案定为：**音频侧降格为无状态工具**（只出 turn+向量+观察），
**身份与累积全在 Mind**。本次落地 Mind 侧，是第 4 个 namespace（memories / library / lifelog / speakers）。

## 落地

### migration v7 `_add_speakers`
不改 v6（`migrations.py` 头部纪律：迁移只前进、不得编辑已跑过的迁移）。新建五张表：
- `speaker_turns` —— **唯一真相源**，每个说话轮次一行，向量永久保留
- `speakers` —— 稳定 ID（`spk_003`）+ 显示名 + 状态（pending/active/archived）+ 统计
- `speaker_exemplars` / `speaker_centroids` —— **派生缓存**，随时可从 turn 重算
- `speaker_merges` —— tombstone，历史文本里的旧 label 仍可解析

同时给 `lifelog_episodes` 加 `started_at` / `ended_at` / `tz`（绝对时间戳），
`start_clock` 降级为显示字段——时钟字符串表达不了跨午夜的录音。

自然键 `UNIQUE(user_id, source_file, started_at)`：同一份录音重跑不会产生重复 turn。

### `storage/speakers.py`
- 向量约定照抄 `memories.embedding`：**L2 归一化 → float32 `tobytes()` → BLOB**，余弦=点积。
  未引入 sqlite-vec（本仓从未实际使用），几十人 × 几十 exemplar 全扫是毫秒级。
- `MatchPolicy` 全部阈值可经 `config.toml` 的 `speakers.*` 覆盖，**默认值是占位符**。
- `match()`：质心粗筛 top-k → **max-over-exemplars** 精算 → 三段式判定（high/gray/unknown）。
  佩戴者走单独阈值（近讲麦方差远小于对方）。1.5–3s 的短 turn 阈值再抬高。
- `put_turns()`：**写入即解析即更新质心，一次调用**。不拆两步是因为"写 artifact 和建索引分开"
  的架构必然静默漂移。带模型指纹校验（model_id/dim 与库内不符直接拒绝）。
- 准入闸门：只有 `binding=high` + 时长达标 + **非 media 区**的 turn 才能成为 exemplar。
- exemplar 淘汰按**最大化多样性**（删与其余最冗余的那个），不是 FIFO——FIFO 会在某人连续一周
  在同一环境说话后把其他环境的样本整批挤掉。
- `promote()`：pending → active 需 ≥5 turn + ≥60s + **跨 ≥2 天**。跨天这条专杀电视和一次性路人。
- `merge/split/rebuild/forget` + `resolve_label()`（跟随 tombstone）+ `manual()` 自描述。

### CLI `speakers` 组
轻量 `_get_speakers()`（只开 SQLite 不加载 mind）。put-turns / resolve / list / get / name /
promote / merge-candidates / merge / split / rebuild / forget / stats / manual。
- **`--payload-file`**：一天约 300 个 turn 的 base64 向量接近 ARG_MAX，字符串传参不够用。
- **`--out-file`**：RadioHand 解析子进程 stdout 时**截断在 64KB**，所以默认只回汇总，明细落盘。
- `name <label> <名字>` 在 confidence=1 时同步写 KG 别名——`add_alias` 会**回写历史三元组**，
  所以在 `spk_003` 名下记过的事实会自动跟着新名字走。

## 验证
- 新增 `tests/test_speakers_store.py` 16 项全绿；**全量 1153 passed / 6 skipped**。
- CLI 端到端（临时 `RADIOMIND_HOME`，未碰生产）：合成两天、两人 + 一段电视 + 一句 2 秒路人共 20 turn
  → 18 条高置信绑定到恰好 2 个人（各 9 条），**电视和 2 秒路人都没能创建身份**；两人跨 2 天出现后
  `promote` 双双转正；重跑同一份录音 20/20 duplicate（幂等）；换模型指纹被拒（退出码 1）；
  `name spk_002 女朋友` 同步写入 KG `entity_aliases`。
- **在已有 lifelog 数据的库上做了 6→7 迁移**，4 条 episode 完好。

## 踩的坑
测试助手的高维几何错误：在 192 维给单位向量加 per-dim N(0,1) 噪声，噪声范数约 13.9，
完全盖过基向量，"同一个人"的余弦只有 0.28 —— 5 个测试假失败。修法是**先归一化扰动再缩放**。
写这类向量测试时要记得高维空间里"加一点噪声"的直觉是错的。

## 待办
1. 标定实验（需真实录音，在 MBP14）：sherpa-onnx vs pyannote A/B + `t_high`/`t_low` 标定。
   **在标定完成前，`manual()` 的 `calibration.calibrated` 恒为 false，阈值不可信。**
2. micpro 工具化（manual/preprocess/observe 三个子命令）。
3. rollup/consolidate 升级：participants 换 speaker label、绝对时间戳、`@spk` 标记、untrusted 隔离。
4. RadioHand：异步长作业模型（现有 scheduler 是单线程同步的）→ 编排 → 部署 R76S（schema 5→7）。
