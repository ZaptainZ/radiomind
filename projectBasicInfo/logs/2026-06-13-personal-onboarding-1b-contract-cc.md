# PersonalOnboarding-1b — HostCapabilities + Authorization 契约草案

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 性质: 契约/接口文档,零 runtime、不改 provider、不碰订阅、不动 RadioHeader repo、
> 不要求普通用户 API key。
> 产出: `projectBasicInfo/05_HOST_AGENT_CAPABILITIES_CONTRACT.md`。

## 1. 做了什么
按指令把 1a 发现的"provider 后台副作用默认开"问题固化为契约,**先定默认与边界,再谈实现**:
- **§1 HostCapabilities 草案**: 14 字段（host_name/host_kind + LLM 2 + can_prompt_user +
  数据访问 3 + 后台 2 + 检索 2 + 外部 URL/持久配置 2),全部**保守默认**（未声明=无能力=不允许）;
  字段只表达能力不执行动作;区分 has_host_llm（有）vs llm_call_available（已接线）。
- **§2 AuthorizationScopes 草案**: 10 个 scope（import_existing_memory / ingest_new_turns /
  write_long_term_memory / background_refinement / dream_after_session / train_lora /
  call_external_llm / call_external_embedding / export_or_upload_memory /
  enable_background_hooks），每个写 触发场景 / 授权文案要点 / 未授权降级 / 可撤销。
  **deny-by-default,scope 独立**（授 ingest 不等于授 dream）。
- **§3 Hermes 当前行为合规映射表**: current behavior / required scope / proposed default(无授权)
  / fallback。明确三处不合规——sync_turn 每轮 auto-ingest、每 10 轮 trigger_chat、
  on_session_end auto_dream(默认 True)——**默认应全改 no-op until granted**;并记 provider
  4 tools ≪ MCP 17 tools 的能力缺口。
- **§4 初始化流程草案**: detect→explain→ask import→import(授权后)→host LLM 优先(不问普通
  用户 key)→检索本地优先(托管延后)→readiness→按条件建议进阶。
- **§5 ReadinessReport 草案**: 7 字段（memory_import/host_llm/retrieval/background_hooks/
  lora/privacy_status/recommended_next_action）;privacy_status 默认 local_only,授外部调用
  才升级——报告兼作隐私账本。
- **§6 1c 最小实现建议**: provider 接受 capabilities+scopes(加性,缺=保守)→**三个后台默认翻
  OFF**→加纯 readiness_report()→**单测先覆盖保守默认**(无授权零后台副作用)。

## 2. 完成标准对照
- 个人 Agent 能看出要声明哪些能力 ✓（§1）
- 必须问授权的动作明确 ✓（§2,10 scope + fallback）
- Hermes 当前默认后台副作用哪里不合规明确 ✓（§3 映射表,三处）
- 给 1c 足够窄的实现范围 ✓（§6: 仅默认翻 OFF + readiness + 保守单测;不做导入 UI/订阅/向量/
  RadioHeader repo）

## 3. 治理原则（本契约的核心）
**未声明能力 / 未授权 scope = 保守行为,绝不取宽松。** RadioMind 无任何宿主能力或授权时
也必须安全可用（本地 add/search/digest 照常）。这把 1a 的"装上就自动 ingest/dream"从
"日后补说明"提升为"契约级默认"。

## 4. 不做 / 守住
零代码、不改 provider 行为、不设计订阅、不动 RadioHeader repo、不要求普通用户 key。
1c 第一刀严格限定: provider 默认副作用改授权门控 + readiness report,不顺手做导入 UI/
订阅/向量服务/工具集扩展。
