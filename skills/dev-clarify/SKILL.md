---
name: dev-clarify
description: Turn a rough idea or vague request into a concrete, test-mappable spec with a non-empty Goal and Acceptance Criteria, by interviewing the user one focused round at a time and recording the Q&A. Produces a spec file any downstream skill can consume. Use when the user has an idea but no clear goal/acceptance criteria, when a request is ambiguous, or as the first step before planning or coding. Do NOT use when a clear spec already exists (go straight to planning/implementation), or when a full codex-dev-loop is already running (its own intake phase handles clarification).
---

# dev-clarify — 需求澄清（可组合子 skill）

`codex-dev-loop` 家族的独立子 skill：把「一个模糊想法」聊成「Goal + 验收标准齐全的 spec」。它是所有开发链的第 0 环，本身不写代码、不改状态机。

约定：`<core>` = codex-dev-loop 主 skill 目录下的 `scripts/dev_loop_harness.py`（Codex 默认 `~/.codex/skills/codex-dev-loop/scripts/dev_loop_harness.py`；Claude Code 为 `~/.claude/skills/codex-dev-loop/scripts/dev_loop_harness.py`）。

## 何时用 / 何时不用

- **用**：用户说「我想做个 X」但没有清晰目标和验收标准；请求含糊；任何规划/编码链启动前需要先对齐需求。
- **不用**：已有清晰 spec（直接进规划或实现）；已经在跑完整 `codex-dev-loop`（它的 intake 阶段自带澄清，此时交给编排器，不要另起 standalone）。

## 前置检查

如果工作区里已存在进行中的 loop（`.codex/dev-loop/loop-state.json` 且 phase ≠ complete），停止并提示用户走 loop 自身的 intake 阶段——本 skill 只在没有活动 loop 时独立工作。（harness 的 standalone 命令会自动拒绝，但你应提前判断避免无谓调用。）

## 流程

1. **一轮一问**：读用户已有的输入，找出缺失的关键信息（目标、验收标准、范围边界、约束、非目标）。每次只问最要紧的一两个问题；Claude Code 上用 AskUserQuestion，Codex 上直接在对话里问。
2. **留档**：把每个问题、用户回答、以及用户批准的假设，记进 `clarification-log.md`（可复用主 skill 的 `references/artifact-templates.md` 里的 `clarification-log.md` 模板）。
3. **写 spec**：把澄清后的目标和验收标准写进一个 spec 文件（默认 `spec.md`，用 `## Goal` 和 `## Acceptance Criteria` 两个二级标题）。好的 spec 还应包含 Context / Constraints / Non-Goals。
4. **过闸门**：

```bash
python <core> check-spec --file spec.md
```

`check-spec` 要求 Goal 和验收标准都非空——不达标就继续澄清，别放行。通过后这个 spec 可直接喂给 `dev-plan`、`dev-tdd` 或完整 `codex-dev-loop`。

## 停止条件

- 用户无法回答某个决定性问题（缺了它无法写出可测的验收标准）→ 停下说明缺什么，不要替用户编造需求。
- 需求实为多个独立任务 → 建议拆分，逐个澄清。

## 升链

当澄清中发现任务其实很大（多模块、涉及迁移或高风险），提示用户：这份 spec 更适合喂给完整 `codex-dev-loop`（standard/large 档），而不是走微链。
