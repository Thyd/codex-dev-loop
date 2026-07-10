---
name: dev-ship
description: Turn a set of local changes into a pull request — create a feature branch, verify every declared behavior has current green evidence, commit, push, open a PR with an evidence-linked description, and watch required CI checks. Use to ship a low-risk change that already has green test evidence, typically after dev-tdd. Do NOT use for sensitive-path or high-risk work, and never commit directly to a protected branch.
---

# dev-ship — 交付 PR（可组合子 skill）

`codex-dev-loop` 家族的独立子 skill：把本地改动规范化为一个带证据的 PR，并盯住必需的 CI 检查。它守住底线闸门，不替代完整 loop 的评审深度。

约定：`<core>` = codex-dev-loop 主 skill 目录下的 `scripts/dev_loop_harness.py`。

开始前运行 `python <core> version --require 0.7.0`；版本不足或核心缺失时停止并更新主 skill。

## 何时用 / 何时不用

- **用**：一个已有绿测证据的小改动要发 PR（通常紧跟 `dev-tdd`）。
- **不用**：想绕过评审强推有风险的改动（升级到完整 `codex-dev-loop`）；绝不直接提交到保护分支。

## 底线闸门（发 PR 前必过）

Create or switch to the feature branch first, then run the gate with every behavior label from this change:

```bash
python <core> ship-check --label <behavior-1> [--label <behavior-2>]
```

`ship-check` 强制：① 在 git 仓库内；② 当前不在保护分支；③ 未触及敏感路径；④ 每个 `--label` 的最新记录都是**针对当前代码树**的绿测。改了代码就要重跑本次变更的全部 label。

若无绿证据：先用 `dev-tdd`（或 `standalone-test --mode regression-only --stage green`，用于已被现有测试覆盖的非行为改动）补一条绿证据。

## 流程

1. 创建特性分支（若还没在特性分支上）。
2. 若改动含规格变更：先用 `dev-spec` 动作 C 把 `specs/` 更新好并 `check-spec-delta` 通过——它会随代码进同一个 PR。
3. 用本次变更的全部行为 label 运行 `ship-check`。
4. 提交：规范化 commit message。
5. push 分支。
6. 用 `gh` 开 PR，PR 描述包含：改了什么、绿测证据路径（`.codex/evidence/tdd/ledger.json`）、（如有）规格 delta 摘要、（如有）`dev-review` 评审结论。
7. 盯 GitHub Actions 必需检查（`gh pr checks`）；失败或缺失就停下报告。

## 外部服务策略（与主 skill 一致）

- 允许：GitHub / `gh` 的分支、push、PR、检查状态操作。
- 需用户确认：任何非 GitHub 的托管扫描/AI review SaaS、付费服务。

## 升链

`ship-check` 或 `guard-check` 暴露出敏感路径、或评审给出 `block` 时，这已经不是「小改动交付」——停下，把改动升级到完整 `codex-dev-loop`（standard/large）走全套评审与质量门。
