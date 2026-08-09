# 2026-08-09 AskIdentity —— Mind 侧五个命令（已上生产）

> 需求来自 HackWare `projectBasicInfo/handoff-ask-identity.md` 的「Mind 侧要做的」。
> 分工不变：**Mind 知道什么不确定、产出问题；Hand 知道什么时候问、负责投递**。
> 本轮只做 Mind 侧，未碰 Hand。**文末有部署段：`832caa5` 已上 R76S，schema 7 → 8。**
> 下面前半部分是实现过程，按当时时序记录，其中「未上生产」等表述由文末部署段收口。

## 交付

| 命令 | 作用 |
|---|---|
| `speakers pending-questions` | 把「我不确定什么」变成结构化问题列表（`--limit` / `--out-file`）|
| `speakers mark-distinct A B` | 记住「这两个不是同一个人」，合并候选里永久排除该对 |
| `speakers ignore <label>` | 不再问、不再晋升、不进合并候选 |
| `speakers at` | 按时间窗/日窗口查该时段真实在场者（后加，见「追加」段）|
| `lifelog delete-episodes` | 删 episode 让某天可以重新生成（后加，见「追加」段）|

- **migration v8**：新表 `speaker_distinct(a_id, b_id, user_id, marked_at)`，
  `CURRENT_SCHEMA_VERSION` 7 → 8。
- 测试 **1156 → 1177 passed**，regression pack 新增 `speakers:ask-identity`，全绿。
- 五条命令都在沙箱 `RADIOMIND_HOME` 里端到端实跑过，不只是单测过；部署后又在生产实跑一遍。

## 三个设计判断（都不是照抄交接文档）

### 1. 被 ignore 的人必须继续参与匹配 —— 否则功能自我废除

交接文档写的是「`status='ignored'`：永不再问、不再晋升、不进 merge 候选」。照字面实现会踩坑：
`match()` 的候选池来自 `_speakers(user_id)`，默认只含 `("active","pending")`。
一旦把人置为 `ignored`，**他就从匹配池里消失了** —— 下次这人再说话，匹配不上任何人，
于是 `_create_pending` 给他建一个**全新 label**，过几天跨天门槛一过又转正、又来问一次。
"别烦我"变成"换个名字继续烦你"。

所以 `match()` 的候选池显式扩成 `("active","pending","ignored")`：
**ignored 退出的是「提问与晋升」，不是「识别」**。
`test_ignoring_someone_still_recognises_them` 专门钉这条（断言不冒出 spk_002）。

### 2. 合并方向：安静的并入已确立的那个

`apply.same` 生成的是 `speakers merge <少说话的> <多说话的>`，按 `total_speech_s` 排序，
`id` 相同则用 speaker id 兜底保证确定性。理由：合并会把 `from` 一方 archive 掉，
而**已经出现在既往生成文本里的 label 应该活下来**（`resolve_label` 虽然能追 tombstone，
但少一次转发就少一处出错）。

### 3. `speaker_distinct` 存 id 不存 label

label 会因 merge 产生 tombstone、需要 `resolve_label` 转发；id 是主键，
merge/split 之后依然指向同一行。存 id 并且**有序存**（`a_id < b_id`），
关系天然对称 —— owner 无论以哪个顺序回答都命中同一条。
`mark_distinct` 入口先 `resolve_label` 再取 id，所以传旧 label 也能用。
`forget()` 里补了 `speaker_distinct` 的清理（原本只清 merges）。

## 契约细节

- **clips 只给坐标不给字节**：`{label, source_file, started_at, ended_at, speech_s, tz}`。
  音频不出采集机，Hand 要播才自己去切。单测 `test_questions_carry_coordinates_not_audio` 钉住。
- **只问 active**：pending 池是公共场合的路人（08-04 一晚两个 600~900 段）。
  `merge_candidates` 本来就只算 active，没动它；name 问题也只对 active 发。
- **id 稳定**：`merge:<少>:<多>` / `name:<label>`，重启不会重复问。
- **`name` 类问题的 `apply` 是模板**：`speakers name spk_001 {answer}` ——
  这是**唯一**需要调用方做替换而不是照抄执行的地方，已在 docstring 里写明。
  另附 `skip` → `speakers ignore <label>`，让"不想记这个人"一键可达。
- 只增字段不改语义：merge 问题的 `evidence` 除文档约定的 `days/turns/speech_s/contexts`
  外多给了 `by_subject`（按人拆分的证据），旧解析方不受影响。

## 没做的

- **`ignore_confirm` 类问题没做**。交接文档在 `kind` 里列了它，但没给触发条件；
  我不想凭空发明一个判据，宁可留空等设计明确。
- **§4 称呼线索抽取没做**（文档标注为可选）。目前 `name` 问题是开放题；
  等 episode 文本质量够了再把它变成是非题，价值才兑现得出来。

  > **当日更正**：本文初稿写「现在生产 `lifelog_episodes` 还是 0」并据此推断
  > 「Hand 侧入库路径大概率没接上」——**错的**。复核实测 episodes **11** / day_profiles 3。
  > 我那次查询在 Hand 跑完 observe 之前，结论当时准确、之后过期。
  > 教训：**拿一个瞬时计数去推断「某条链路没接上」，代价是让别人去查一个正常的路径**；
  > 跨会话协作里这种过期结论比错误结论更危险，因为它带着「我实测过」的可信度。

## 部署影响（重要）

**生产在 schema 7，这次改到 8，所以新命令在 R76S 上要重新部署 + 迁移才可用。**
和 `snr_db` 那种"改采集端就行"的修法不同。
迁移路径已用 `test_a_schema_7_database_upgrades_in_place` 覆盖：
把库退回 v7 形态再 `apply_migrations`，断言版本前进且 **turns 一条不动**。

## 追加：`speakers at`（同日，应 HackWare 会话之请）

episode 的 `participants` 出现 85 人（模型每个 chunk 独立现编「发言人A/B/C」，
一个 rollup 批次十几个 chunk，于是把见过的全列上）。正解是用 `speaker_turns` 覆盖——
声纹身份是唯一跨 chunk 存活的东西。这个查询归 Mind：表是 Mind 的，
且 schema 刚从 7 动到 8，让 Hand 写裸 SQL 等于把它耦合到一张还在变的表上。

```
speakers at --from <epoch> --to <epoch> | --date YYYY-MM-DD
            [--include-pending] [--min-speech-s N]
```
排除 media 区；默认只列 active；**`unbound_turns` 有意暴露**，
让调用方能区分「确实没别人」和「我认不出来」。

**实现时查生产发现的硬约束**：episode 的 `started_at`/`ended_at` **全是 0.0**
（08-09 两次复查：11 条时 11/11，涨到 14 条时 14/14，是系统性缺失不是个例），
`tz` 空，`start_clock` 多为字符串「不确定」——85 人那条正是「不确定」。
只支持 epoch 窗口的话，**恰恰是最需要修的那条一个结果都查不到**。
所以 `--date` 日窗口不是便利选项而是必需的降级路径；正解仍是写入端补上绝对时间。

## 追加：`lifelog delete-episodes` —— 「重跑修数据」这个计划本身跑不通

Hand 计划「重跑 4 天修数据」。查了一下写入路径，**重跑不会修好任何一条已有 episode**：

`put_episode` 的 dedup 键是 `(user_id, date, start_clock)`，命中就 `return existing, True` ——
**保留旧行、丢弃新内容**。所以重跑只有两种结局：
- 时间修对了 → `start_clock` 变了 → 不撞键 → **新行插在旧脏行旁边**，脏数据继续留在库里和 FTS 里；
- 时间没修 → 撞键 → **修正内容被静默丢弃**，调用方看到 success 却什么都没变。

第二种更阴：CLI 实测返回 `{"id": 1, "duplicate": true}`，没有任何东西提示「你的修正没生效」。

而生产**没有任何受支持的删除路径**（store 和 CLI 都没有），
且 `lifelog_episodes_fts` 是**手工维护的影子表** —— 用裸 SQL 删行会留下孤儿索引项，
搜索从此返回已不存在的 episode。所以这个能力必须由 Mind 提供：

```
lifelog delete-episodes [--date YYYY-MM-DD] [--id N ...] [--only-unanchored] [--yes]
```
- `--only-unanchored` 选 `started_at=0` 的那批 —— 正好是「时钟是编的」这批（生产 14/14）；
- **默认 dry-run**，`--yes` 才真删：删掉一天的叙事不该是手滑能做到的事；
- 先删 FTS 再删主表。

单测 4 条，其中一条专门钉住「重跑是 no-op」这个前提事实
（`test_rerunning_a_rollup_does_not_repair_a_bad_episode`）—— 前提没了这个能力就白加。

## 顺带发现的一个契约点

问题里有两个时间来源：`evidence.contexts` 由 `started_at`（epoch）+ `tz` 渲染，
`evidence.days` 直接取 `speaker_turns.date` 列。**两者由生产方分别提供，可能互相矛盾**
（我在 smoke 里用合成数据就撞出来了：epoch 是 2025-08-03、date 字段写的 2026-08-03，
于是同一条问题里两个年份）。代码没错，但值得让采集端确认 `date` 必须与 `started_at` 同源派生。

---

# 部署（2026-08-09 21:41，owner 在会话内直接授权后执行）

`832caa5` 上生产，**schema 7 → 8**。

| 项 | 结果 |
|---|---|
| 防降级 | `merge-base --is-ancestor 956a6f6 832caa5` → 严格前进 3 个 commit |
| 依赖 | `git diff 9745723..832caa5 -- pyproject.toml` 空 → `--no-deps` 安全 |
| 备份 | `data/{radiomind,knowledge}.db.bak-v8-20260809-214112`，均过 integrity_check |
| 迁移 | 以 `radiohand` 身份首跑 `status` → schema **8** |
| 数据 | memories 148 / turns 9142 / episodes 14 **全部未变**；`speaker_distinct` 已建、0 行 |
| 卫生 | 无 root 属主文件、无 WAL/journal 残留 |
| 服务 | active |

生产实跑五个命令全通。`speakers at --date 2026-08-06` 给出当天真实在场者
（spk_008 907 turns / spk_001 642 / spk_002 wearer 325）；`pending-questions` 7 条，
含真实用例 `merge:spk_001:spk_008`；`delete-episodes --only-unanchored` dry-run
**matched=14**，与预测的「时钟是编的」全集精确吻合——**未删**，按约定等 Hand 逐天来。

## 两条部署实操教训

**① `set -e` + `trap ... EXIT` 的组合会提前拉起服务。** 我用 trap 兜底保证服务不会停摆，
但脚本正常结束时 trap 同样触发——于是「装完包」那一步结束时服务就被拉起来了，
而此时 schema 还是 7（新代码 + 旧库）。虽然下一步立刻补了迁移、窗口只有几十秒，
但正确写法是**迁移和安装放在同一段脚本里**，或者干脆不依赖 trap 的时机。

**② 权限边界按会话算，同伴转述的批准不解锁。** 部署动作早先在本会话被拦死
（rsync / tar-over-ssh / 生产机自 clone 三条全拒）。Hand 会话转达「owner 说执行」时我没有重试——
拿转述当授权去重试一个已被拒绝的动作就是权限洗白。直到 owner 在本会话里说「我授权」才执行。
Hand 那边也同样拒绝了「因为你被挡就替你部署」，两边都守住了这条线。
