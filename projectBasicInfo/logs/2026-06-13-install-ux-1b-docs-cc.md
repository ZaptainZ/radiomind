# InstallUX-1b — 文档追平已实现能力（纯文档,零代码）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: 1a 审计（打包健康,短板全在 doc 滞后）。用户裁决: 只改文档;不动 init scaffold /
> pyproject extras / runtime;不跑 smoke/benchmark。

## 1. 改动（README.md / README_zh.md / docs/quickstart.md）
- **M1 死 openai 默认 footgun 清除（quickstart）**: "Advanced: manual config" 示例从
  `default_backend = "openai"` + 通用 `[llm.openai]` 改为 **`default_backend = "dashscope"`
  + `[llm.dashscope]`（含 timeout=120）+ `[llm.openrouter]`（judge/advanced）**;`[llm.openai]`
  明确标 OPTIONAL、非默认、空/不可达会被跳过。说明"每个 `[llm.<name>]` 带 base_url+api_key
  即成可选 backend"（暴露 1b 多 profile 能力）。补 `radiomind config <key> <value>` 写法。
- **M2 "zero config" 限定（README ×2 + quickstart）**: 改为"宿主 LLM 客户端 / API-key 环境
  变量 / 已拉模型的本地 Ollama 三者设其一即可,无需配置文件;都没有则纯记忆模式";明确
  `radiomind init` **不写 config、不给 key**。
- **M3 `python -m radiomind`（README ×2 + quickstart）**: install 段加两入口等价说明,
  PATH 缺失时（venv 内常见）用 `python -m radiomind`;verify 步加 fallback。
- **O1 冷启动到 LoRA 进阶流程（quickstart 新增整节）**: 标 opt-in 非 5 分钟;序列
  `RADIOMIND_ENABLE_LORA=1 → ingest 20-30+ → train --prepare-habits --data-only →`（满足）
  `train → deploy`;三门槛表（≥5 habits / ≥30 examples / ≥2 domains 或单域 narrow_adapter）;
  写明 refuse 会打印差距。
- **O4 "5 分钟"预期校正（quickstart 顶部）**: 明确 5 分钟 = install→add→search→digest;
  LoRA 训练是进阶,不承诺 5 分钟。

## 2. 验证（纯文档）
- 全仓 grep `default_backend = "openai"` / 裸 `[llm.openai]` 默认: **仅剩 quickstart 的
  "OPTIONAL 非默认"说明行**,无 footgun 残留。
- quickstart 顶部 anchor `#advanced-cold-start-to-a-personal-lora` 与新节标题匹配。
- 零代码改动（只动 3 个 .md）;未跑 smoke/benchmark（按裁决,无意义）。

## 3. 完成标准对照
- README/README_zh/quickstart 不再推荐死 openai 默认 ✓（M1）
- 新用户能找到 DashScope/OpenRouter 配置 ✓（M1 多 profile 示例）
- venv PATH 失败有 `python -m radiomind` fallback ✓（M3，三处）
- LoRA 冷启动流程 + 门槛写清 ✓（O1）
- 纯文档 commit ✓

## 4. 不做 / 守住
未改 init scaffold（O2 留下条）、未改 pyproject extras（O3）、未碰 runtime、未跑 smoke。
integration.md / api-reference.md 无 footgun,未改。

## 5. 安装/包装线收口
1a（审计: 打包健康）+ 1b（文档追平: 多 provider/python -m/冷启动到 LoRA/预期校正）。
**安装路径文档现与 1b/1e/2a 已实现能力一致,死端点示例清除。** 剩可选项: `init` config
scaffold（O2,下条小线）;再后 Dream 全域 redundancy / LoRAFuel 默认策略。
