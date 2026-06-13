# PersonalOnboarding-1c — Hermes provider 授权门控 + readiness_report（极窄实现）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 性质: 首个 runtime 改动,仅限 Hermes/provider onboarding 面。依据
> `05_HOST_AGENT_CAPABILITIES_CONTRACT.md`。不做导入 UI/订阅/向量/MCP 工具扩展/RadioHeader。

## 1. 改动
- **新模块 `src/radiomind/adapters/onboarding.py`（纯数据+投影,零 IO/LLM/store）**:
  `HostCapabilities`（14 字段,frozen,全保守默认）、`SCOPES`（10 个,契约 §2）、
  `AuthorizationState`（granted frozenset,`from_iterable` 丢弃未知 scope,`has()`）、
  `ReadinessReport`（7 字段 + to_dict）、`readiness_report(caps, authz, *, llm_available,
  habit_count, example_count)` 纯投影。字段名与契约对齐,无外部依赖。
- **`adapters/hermes.py` 加性门控**:
  - `initialize(**kwargs)` 接受 `capabilities`（HostCapabilities 或 dict,未知字段丢弃）+
    `authorized_scopes`（AuthorizationState 或 iterable）;缺省 = 最保守。
  - `_auto_dream` 默认 **True→False**;由 `dream_after_session` grant 决定。
  - **sync_turn**: 无 `ingest_new_turns` → no-op（debug log skipped_by_authorization,不写 store）;
    每 10 轮 trigger_chat 额外要 `background_refinement`。
  - **on_session_end**: 无 `dream_after_session` → no-op。
  - **on_memory_write**（镜像宿主记忆=持续导入）: 无 `import_existing_memory` → no-op。
  - 新增 `readiness()` 方法: 投影当前 caps+grants+state（llm 可用/habit 数）为 report dict,
    纯函数不写 store。
  - 向后兼容: 旧 `initialize(session_id, hermes_home=, llm=)` 不崩;但**旧调用不再默认跑
    后台副作用**（按裁决: 必须显式授权才恢复,不 implicit True）。

## 2. 验证
- 新增 `tests/test_personal_onboarding.py`（13）: deny-by-default（无 grant 不 ingest/refine/
  dream/mirror）、各 grant 后恢复（ingest 单独/refinement 需双 grant/dream/mirror）、
  initialize 接受 caps dict + scopes（未知字段/scope 丢弃）、旧调用保守、readiness 保守默认 +
  授权升级 + lora needs_more_data + provider.readiness()。
- 更新 `tests/test_hermes.py`: `test_sync_turn`/`test_on_memory_write` 拆成 denied-by-default +
  after-grant 两组（行为变更是有意的,断言"未授权不写/授权后写"）。
- pack 新增 `adapter:personal-onboarding` → **36 类全绿**;全量 **1056 passed**。

## 3. 完成标准对照
- 无宿主授权时 provider 不再自动 ingest/refine/dream ✓（deny-by-default 测试 + 实现）
- 宿主显式授权后原能力恢复 ✓（after-grant 测试）
- readiness 告诉宿主缺什么、下一步请求什么授权 ✓（readiness_report + recommended_next_action）
- 老调用不崩,默认更安全 ✓（backward-compat 测试 + 行为默认 OFF）

## 4. 治理原则落地
契约的"未声明能力/未授权 scope = 保守,绝不取宽松"在代码层兑现: 缺省 caps/scopes →
三个后台副作用全 no-op;RadioMind 本地 add/search/digest 不受影响（provider 的 search/
learn tool 仍可手动调,handle_tool_call 未门控——那是用户经宿主显式发起的前台动作,非后台
副作用）。

## 5. 不做 / 守住
未做记忆导入 UI、订阅、向量托管、MCP 工具集扩展、RadioHeader repo;未问普通用户 API key。
provider 4-tool vs MCP 17-tool 的能力缺口未碰（契约 §3 记的后续步）。

## 6. 下一步
PersonalOnboarding 线（1a 审计→1b 契约→1c 门控+readiness）安全默认已与产品原则一致。
按既定顺序,接下来 PowerUserOnboarding-1a（CLI/API/MCP 命令图 gap，只读）。
