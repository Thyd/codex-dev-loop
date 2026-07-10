---
name: dev-tdd
description: Fix a bug or add a small piece of behavior test-first, enforcing a real red-green cycle — a failing test recorded before implementation, then a passing test after — with evidence kept in a standalone ledger. Use for a single bounded change (one bug, one function, one small feature) when you want TDD discipline without the full development loop. Do NOT use for multi-module or high-risk work (use the full codex-dev-loop), or when a full loop is already running (use its own run-test red/green stages).
---

# dev-tdd — 单元内 TDD（可组合子 skill）

`codex-dev-loop` 家族的独立子 skill：对一个有界的小改动强制红→绿→重构，且**红证据由 harness 强制先于绿**——这正是它区别于「口头 TDD」的地方。

约定：`<core>` = codex-dev-loop 主 skill 目录下的 `scripts/dev_loop_harness.py`。

开始前运行 `python <core> version --require 0.7.0`；版本不足或核心缺失时停止并更新主 skill。

## 何时用 / 何时不用

- **用**：修一个 bug、加一个小函数、一处有界行为改动，想要 TDD 纪律但不需要整条流水线。
- **不用**：多模块 / 跨模块 / 高风险改动（用完整 `codex-dev-loop`）；已经在跑完整 loop（用它自己的 `run-test --stage red|green`）。

## 前置检查

1. 需求清楚吗？不清楚先用 `dev-clarify`。
2. 跑护栏预检——命中敏感路径（依赖清单/迁移/CI/Docker/密钥/auth 等）说明这不是「小改动」，应升级到完整 loop：

```bash
python <core> guard-check
```

3. 若存在活动 loop（phase ≠ complete），本 skill 的 standalone 命令会被 harness 拒绝——改用 loop 自身命令。

## TDD 循环

用一个稳定的 `--label` 标识被测行为（如 `login-401-msg`）。

1. **红**：先写会失败的测试，记录红证据（红运行**不计入**失败上限；红却通过会被判定为「测试没证明缺失行为」，需加强测试）：

```bash
python <core> standalone-test --label <label> --stage red --expected-failure "<intended missing behavior>" --command "<failing test command>"
```

Red failures pass through red-test-validator first; import, syntax, dependency, path, environment, and ambiguous snapshot failures do not unlock green.

2. **实现**：写最小实现让测试转绿。

3. **绿**：记录绿证据（**没有红证据时 harness 拒绝记录绿**）：

```bash
python <core> standalone-test --label <label> --stage green --command "<同一个测试命令>"
```

4. **重构**：测试保持绿的前提下重构，重构后重跑绿。

多个行为就用多个 label，各自走一遍红绿。证据落在 `<evidence_dir>/tdd/ledger.json`（默认 `.codex/evidence/tdd/`）。

## 证据目录（宿主识别）

- Codex 宿主（未设置 `CODEX_DEV_LOOP_HOME`）：默认 `.codex/evidence/`，无需配置。
- 非 Codex 宿主（如 Claude Code）：首次使用时为工作区选一个证据目录（建议 `.dev-loop/evidence/`），写入配置 `evidence_dir` 固化，后续自动沿用。

## 升链触发线

执行途中命中任一条，停下告知用户并升级到 `small` 短链或完整 loop：

- `guard-check` 报出敏感路径；
- 实际要改的行为明显不止一两处（更像一个 feature）；
- 测试反复失败、根因指向设计问题（考虑配合 systematic-debugging）。

## 底线

任何情况下都不跳过测试、不在测试失败时宣称完成、不碰保护分支。要发 PR 时接 `dev-ship`（P2 提供）。
