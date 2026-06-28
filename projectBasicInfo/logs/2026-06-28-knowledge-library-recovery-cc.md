# KnowledgeLibrary 恢复 — 本地旧 checkout 致 R76S 降级，rebase 到 v0.2.1 恢复

- 日期：2026-06-28
- 角色：cc
- 问题：本地 `~/code/radiomind` 是旧 checkout(v0.1.0)，远端 main 已 v0.2.1(领先 10+ commit)。在旧基线上建
  了 KnowledgeLibrary-2a + 把它 `pip install -e` 部署到 R76S → **R76S radiomind 从 0.2.1 降级回 0.1.0**(live
  runtime 回退；reranker/RetrievalUX 等增强丢失)。
- 恢复（按 owner 计划 A）：
  1. 备份 R76S live(db 172KB→`radiomind.db.bak-recovery-2026-06-28`、env→`.env.bak-recovery`、记 version
     0.1.0/schema 5/51 memories/2 library_items)。
  2. 本地 `git rebase --onto FETCH_HEAD 4cbad775 main`：库工作纯增量(新 library.py、cli 末尾 append、迁移 v5
     是远端 v4 的下一个、远端无 library.py) → **零冲突**接到 `a5ee3c5 Release 0.2.1`。version 回 0.2.1。
  3. 全套测试 **1125 passed/6 skipped**(v0.2.1 真实测试集 + library + schema/doctor)；reranker/retrieval_tier
     未被覆盖。
  4. R76S `pip install -e` 重装 v0.2.1+library：**version 回 0.2.1、doctor schema v5、51 memories+2
     library_items+embedding+retrieval-tier 全保留**。
  5. RadioHand 侧验证：library 搜"高斯"命中、同 URL capture dedup("已经收过了")、memory 问答"五分钟后喝水
     提醒"工作。
  6. push fast-forward(`a5ee3c5..208ea64`，含 2a `64ef7b9` + doctor 修复 `208ea64`)。不 tag。
- doctor 修复(208ea64)：`database.SCHEMA_VERSION = CURRENT_SCHEMA_VERSION`(单一来源)；doctor 经 MemoryStore
  开库(应用迁移)再报版本 vs 目标——不再读旧常量/迁移前的表值。
- 教训：对独立项目动手/部署前先 `git fetch` 比对本地 vs 远端版本；`pip install -e <旧源>` 到 live=静默降级。
