# TrinityErrorVisibility-1a — 裸 except 变可诊断日志（控制流不变）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: LLMRouter-1b 排障在 trinity `_call_llm` 裸吞异常上耗时。用户裁决: 窄 scope,
> 只把静默失败变可观测,不改控制流;不做 max_tokens / cost-tier（下一条）。

## 1. 改动（5 个 LLM 调用吞错点，全部仍返回原值，仅先 logging.warning）
| 位置 | stage 标签 | 原行为(不变) | 日志内容 |
|---|---|---|---|
| `trinity._call_llm` | `{agent_role}/round{N}` | return "" | stage / exc type / backend / prompt_len |
| `trinity._parse_json` | 同上 | return None | stage / exc type / raw_len / head（**仅当 raw 非空**,空 raw 已在 _call_llm 警告过,不双记） |
| `decompose.decompose` | `decompose` | return [] | stage / exc type / backend / prompt_len |
| `dream._merge_pair` | `dream/merge` | return None | stage / exc type / backend |
| `dream._wander` | `dream/wander` | pass | stage / exc type / backend |

共享助手 `trinity._describe_llm(llm)`: 优先 `config.get("llm.default_backend")`（LLMRouter）,
退 `name`/`default_model`,再退类型名;永不抛。decompose/dream 复用之（无循环导入,已验证）。
窄类型 except（TypeError/ValueError 置信度归一、json 解析内 number cast）**不动**——
它们是数据归一,非调试黑洞。

## 2. 验证
- `tests/test_trinity_error_visibility.py`（**10**）: 每个吞错点 monkeypatch 抛 TimeoutError
  断言"返回值不变 + warning 恰一次 + 含 stage/exc-type"; 成功路径零警告;
  `_parse_json` 空 raw 不双记; `_describe_llm` 三级回退。
- regression pack 新增 `refinement:trinity-error-visibility` → **30 类全绿**。
- 全量 **990 passed**。

## 3. 顺带修复: 昨日 LLMRouter-1b Fix D 损坏了 live config（真实回归）
全量套件首次暴露 `tomllib.TOMLDecodeError`(line 8): 昨日用 `str.replace('[llm.openai]',
..., 1)` 加 DEPRECATED 注释时,**首次匹配命中了第 7 行注释里的 `[llm.openai]` 字样**
而非第 11 行真正的 section header,把 `#` 挤错行 → 第 8 行变成非法裸 `[llm.openai] =
TokenPlan...`。昨日"980 passed"是在该编辑**之前**跑的,编辑后未复跑全量 → 漏网。
**修复**: 从备份 `config.toml.bak-20260613-011306` 恢复,改用行锚定多行 anchor 重做
Fix D（default→dashscope / 真 header 前加 DEPRECATED / dashscope timeout=120）,
tomllib 校验通过。教训: (1) 改 config/代码后必须复跑全量再宣称通过,别用编辑前的结果;
(2) `str.replace(x, ..., 1)` 对"既出现在注释又出现在真实位置"的 token 会咬错首处,
要用多行唯一 anchor。

## 4. 不做 / 守住
不改控制流（失败仍静默降级,只是不再无声）。不动窄类型 except。不做 max_tokens /
cost-tier provider 测试（下一条）。trinity stance 命名等既有纪律未触及。
