# 2026-08-09 两个 checkout 对齐 + 修掉 remote 配置的根因

## 起因

RadioMind 有**两个本地 checkout**，长期不同步，而且 Codex/Claude 会话的 cwd 落在哪个不确定：

| checkout | 对齐前 | 用途 |
|---|---|---|
| `~/code/radiomind` | `feat/lifelog` @ 9745723，main 停在 85e2f0f | 所有 lifelog/speakers 开发都在这里 |
| iCloud `DarkForce/RadioMind` | `main` @ **a5ee3c5 Release 0.2.1** | 落后 15 个提交，但**有会话的 cwd 指向它** |

真实风险：会话若在 iCloud 那个 cwd 里直接动手，就是在一个落后 15 个提交的基座上开工。
2026-08-06 的部署日志已经记过"两个 checkout 容易混淆"，这次把它彻底了结。

## 动作

1. **提交遗留**：R76S 部署日志（有价值的运维记录）入库；`.gitignore` 补 `*.ckpt.jsonl`
   ——原规则只写了 `*.checkpoint.jsonl`，漏了这个拼法，于是 bench 产物一直挂在未跟踪列表当噪声。
2. **`main` 快进到 `feat/lifelog`**：核对过 `main` 有 0 个提交是 feat 没有的 → 纯 fast-forward，
   无分叉、无冲突。11 个提交（speakers namespace、标定、consolidate、绝对时间戳…）落到 main。
3. **两个 checkout 都到 `956a6f6`**；iCloud 那边的 2 处 Codex hook 本地定制**刻意保留**
   （新旧版本之间那两个文件没被改过，fast-forward 能安然带过）。
4. **R76S `/opt/radiomind-src` 也拉到 956a6f6**。先核对 `9745723..956a6f6` 对 `src/ tests/
   pyproject.toml` 的 diff 为空 → **纯文档变更，不需要重装、不需要重迁移**，daemon 未受影响。

## ★根因修复：remote URL★

`~/code/radiomind` 的 origin 是 **HTTPS 且 keychain 无凭据** —— 这一个配置错误制造了两个症状：

- Mind 会话 2026-08-06 想推分支时 `git push` 直接报 `could not read Username`；
- 绕过办法（`git push <ssh-url> ...`）**能推上去，但不更新 remote-tracking ref**，
  于是本地 `origin/main` 长期停在陈旧值。这正是部署日志里"两个本地 ref 互相矛盾、
  照 `origin/main` 判新旧会得出错误结论"的成因——**而防降级判断恰恰依赖它**。

已 `git remote set-url origin ssh://git@ssh.github.com:443/ZaptainZ/radiomind.git`
（443 端口那条实测可用），fetch 后 tracking ref 归位。以后 `git push` 直接可用，不必绕 URL。

**教训**：用显式 URL 推送是"能绕过去"的临时手段，但它会**悄悄留下陈旧的 tracking ref**；
下游任何依赖 `origin/*` 做新旧判断的逻辑都会被它误导。撞到"没凭据"时应该修 remote，而不是绕开它。

## 最终状态

```
~/code/radiomind          main@956a6f6   0 ahead / 0 behind   工作区干净
iCloud RadioMind          main@956a6f6   仅 2 处 hook 本地定制
GitHub main / feat/lifelog       956a6f6
R76S /opt/radiomind-src          956a6f6
生产库                     schema 7 / 9142 turns / 6 active speakers / daemon active
```

`~/code/radiomind` 另有 3 个旧 stash（`WIP on main`，2026-06 前后的 trinity/bench 工作），
**不是本次产物，未动**。owner 若确认不再需要可自行 `git stash drop`。
