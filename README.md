# Codex Dev Loop · 从需求到 PR 的自动开发 loop

![Skill](https://img.shields.io/badge/Skill-Codex%20%7C%20Claude%20Code-111111?style=flat-square)
![Version](https://img.shields.io/badge/Version-v0.4.0-blue?style=flat-square)
![Quality Gate](https://img.shields.io/badge/Quality%20Gate-required-0A7CFF?style=flat-square)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-supported-2088FF?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

[中文](#中文) | [English](#english)

> 非官方社区 skill。本项目不隶属于 OpenAI 或 Anthropic，也未获得其赞助、背书或认可。

## 中文

你可以把 `codex-dev-loop` 理解成一条给 AI 编码代理用的自动开发流水线（支持 Codex 与 Claude Code）。

它做的事很直接：给它一份 Notion 页面、Markdown 需求，甚至只是一个模糊想法，它会先把需求聊清楚（记录澄清问答），和你确认任务规模（small / standard / large 三档闸门重量），再补齐技术方案、测试计划、风险分析、规格 delta 和开发计划；这些东西通过 Subagent 评审后，才开始写代码；每个开发单元先写失败测试再实现（TDD 红绿闸门，独立单元可在 git worktree 中并行）；实现后把规格 delta 合并进仓库的 `specs/` 规格基线，随同一个 PR 接受评审；最后必须跑测试、质量门、云端检查和 PR 级 review，才提交代码和创建 PR。

目标很明确：让 AI 自动推进开发，同时让澄清、TDD、评审、质量门、规格沉淀和 PR 检查持续拦住风险。

### 30 秒开始

安装到本地 Codex skills 目录（macOS / Linux）：

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.codex/skills/codex-dev-loop
```

Windows（PowerShell）：

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

如果已经安装过，用这条更新：

```bash
git -C ~/.codex/skills/codex-dev-loop pull
```

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-dev-loop" pull
```

初次使用前，运行 5 问配置：

```bash
python ~/.codex/skills/codex-dev-loop/scripts/configure_dev_loop.py
```

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

Claude Code 用户改装到 `~/.claude/skills/`，并用适配版 SKILL.md 覆盖根文件（详见 `adapters/claude-code/SKILL.md`）：

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.claude/skills/codex-dev-loop
cp ~/.claude/skills/codex-dev-loop/adapters/claude-code/SKILL.md ~/.claude/skills/codex-dev-loop/SKILL.md
```

安装后重启 Codex，然后把下面这段话发给 Codex：

```text
请使用 $codex-dev-loop 处理 docs/spec.md。
需求不清就先问我，确认任务规模后再规划。
先补齐技术方案、测试计划、风险分析、规格 delta 和开发计划。
规划产物通过 Subagent 评审后，按 TDD 红绿闸门逐单元实现。
实现完成后合并规格基线、自动跑测试、ai-code-quality-gate、GitHub Actions 和 PR review。
通过后创建新分支、提交代码并发起 PR。
```

如果你的需求在 Notion 里，或者只有一个模糊想法，也可以这样说：

```text
请使用 $codex-dev-loop 处理这个 Notion 页面。
如果信息不足，先停下来问我；不要直接开始写代码。
```

```text
请使用 $codex-dev-loop，我现在只有一个粗略想法：<你的想法>。
用 --draft 启动，先通过提问把目标和验收标准聊清楚，再走完整流程。
```

### 适合 / 不适合

适合：

- 有明确目标和验收标准的功能开发。
- 只有模糊想法也可以：用 `init --draft` 启动，intake 阶段会先通过提问把 `Goal` 和 `Acceptance Criteria` 聊清楚（问答留档在 `clarification-log.md`），聊不清楚就不放行。
- 希望 AI 自动写代码，但又不想绕过 TDD、lint、typecheck、test 和安全扫描。
- 希望每次开发都走新分支、提交、PR 和 GitHub Actions，规格变更随同一个 PR 沉淀进 `specs/` 基线。
- 希望在写代码前，让 Subagent 先审技术方案、测试计划、风险和规格 delta。
- 小修小补不想扛全套流程：选 `small` 档，harness 会在敏感路径（依赖、迁移、CI、安全文件）被改动时强制升档。
- 希望把自动开发过程留下记录，方便回溯。

不适合：

- 不允许 Codex 读写文件、运行命令或操作 git。建议先使用“只做规划”模式，等方案确认后再开放执行权限。
- 没有测试，也不准备补测试的仓库。TDD 闸门要求每个单元先有失败测试；完全不想写测试的仓库无法走通。
- 需要直接改生产环境、数据库或线上配置的任务。建议拆成设计评审和人工执行两步，先让 loop 输出风险和迁移方案。
- 需要绕过质量门、强行合并或“先上再说”的任务。建议降低任务范围或调整质量门配置，不建议关闭所有 gate。

### 它会帮你做什么

| 阶段 | 它会做的事 | 不通过时会怎样 |
|---|---|---|
| 需求澄清 | 读取 Markdown / Notion / 草稿，需求不清就提问，问答记入澄清日志 | Goal 或验收标准为空就不放行规划 |
| 规模确认 | 和你确认 small / standard / large 档位，决定闸门重量 | 敏感路径被改动时 small 强制升档 |
| 方案补齐 | 生成技术方案、文件范围、测试计划、风险分析、规格 delta、开发计划 | 发现架构风险就停止 |
| Subagent 评审 | 让 plan / implementation / risk 三类 reviewer 交叉检查 | 评审不通过就修改后重审 |
| TDD 开发 | 每个单元先记录失败的红测试，再实现到绿；独立单元可在 worktree 并行 | 没有红证据，绿测试不计入 |
| 测试门 | 每个单元都要跑测试，失败次数按初始配置控制 | 达到配置阈值就停止 |
| 规格沉淀 | 把规格 delta 合并进 `specs/` 基线并机械校验 | 基线与 delta 不一致就不放行评审 |
| 本地质量门 | 强制调用 `ai-code-quality-gate`（或内置 fallback），严格度按初始配置控制 | 质量门失败就停止 |
| PR 阶段 | 创建分支、提交、推送、开 PR | 缺权限或 token 就停止 |
| 云端检查 | 检查 GitHub Actions、PR review、Qodo PR-Agent 或 CodeRabbit | 检查失败或缺失就停止 |
| 归档 | complete 后把本次运行产物移入 `dev-loop-archive/` | 未归档就不允许直接 init 下一轮 |

### 一次完整流程

1. 你提供一个需求：Notion 页面、本地 Markdown，或只是一个想法（`--draft`）。
2. 初始化 `.codex/dev-loop/` 执行目录，loop 从 intake 阶段开始。
3. 需求不清就提问澄清，问答记入 `clarification-log.md`；和你确认任务规模（small / standard / large）。
4. 生成这些规划文件：
   - `technical-design.md`
   - `test-plan.md`
   - `risk-analysis.md`
   - `development-plan.md`（每个单元声明 TDD 模式和依赖）
   - `spec-delta.md`（本次变更的需求级 delta）
   - `decision-log.md`
5. Subagent 评审规划产物。
6. 主 agent 根据评审意见修改。
7. Subagent 再审，直到通过或发现必须停止的问题。
8. 按开发计划逐单元 TDD 实现：先记录失败的红测试，再实现到绿；无依赖的单元可由 unit-implementer Subagent 在独立 git worktree 中并行完成，证据由主 agent 串行记录。
9. 把 `spec-delta.md` 合并进仓库 `specs/` 规格基线，`record-spec-merge` 机械校验，然后 `verify-units` 在主工作区对最终代码树复验全部单元。
10. 本地运行 `ai-code-quality-gate`（未安装时用内置 fallback），覆盖 lint、typecheck、test、Semgrep、CodeQL、Sonar、Qodana 等可用检查。
11. 创建新分支并提交代码；如果是 `commit_only` 模式，记录 commit 后完成。
12. 如果自动化范围允许，推送到 GitHub、创建 PR（规格基线更新随同一个 PR 评审），并等待 GitHub Actions 和 PR 级 AI review。
13. 把过程记录写回 `.codex/dev-loop/`，complete 后归档到 `.codex/dev-loop-archive/`。

### 需要你准备什么

最少需要一份需求文档：

```markdown
## Goal

实现用户登录失败后的错误提示优化。

## Acceptance Criteria

- 密码错误时展示明确但不泄露安全细节的提示。
- 登录接口返回 401 时前端不崩溃。
- 现有登录测试继续通过。
- 新增覆盖 401 错误提示的测试。
```

更好的需求可以继续补：

- 背景和用户场景。
- 不允许改动的文件或模块。
- 需要兼容的浏览器、平台或 API 版本。
- 明确的性能、安全、数据迁移限制。
- 已知风险或历史坑。

### 安装

方式一：直接让 Codex 安装。

把这段话发给有 shell 权限的 Codex：

```text
请帮我安装 codex-dev-loop。
把 https://github.com/Thyd/codex-dev-loop.git 克隆到 ~/.codex/skills/codex-dev-loop。
安装后检查 SKILL.md、scripts/、references/ 和 agents/openai.yaml 是否存在。
```

方式二：手动命令安装。

macOS / Linux：

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.codex/skills/codex-dev-loop
```

Windows（PowerShell）：

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

方式三：更新到最新版。

```bash
git -C ~/.codex/skills/codex-dev-loop pull
```

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-dev-loop" pull
```

安装后重启 Codex，让 Codex 重新发现 skill。

### 初次配置

首次使用前，建议运行一次配置向导：

```bash
python ~/.codex/skills/codex-dev-loop/scripts/configure_dev_loop.py
```

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

它只问 5 个问题：

| 问题 | 默认值 | 影响 |
|---|---|---|
| 你希望自动化到哪一步？ | 创建 PR 后停止 | 决定是否只规划、只提交，还是开 PR 后停止 |
| 需求来源主要是什么？ | Markdown + Notion | 决定允许从哪些来源读取需求 |
| 质量门严格度选哪种？ | 标准 | 决定强制哪些本地质量门和云端检查 |
| 测试失败允许自动修复几次？ | 3 次 | 同一测试门连续失败超过重试次数后停止；通过一次即重置计数 |
| 遇到高风险情况时怎么处理？ | 停止并询问 | 决定需求不清、缺 token、外部服务、安全/数据风险时是否继续 |

配置会写入：

```text
~/.codex/config/codex-dev-loop.json
```

harness 会执行这些配置：不允许的来源类型会在 `init --source-type ...` 阶段被拒绝；`planning_only` 和 `commit_only` 会在各自完成点停止。

配置完成后会输出类似说明：

```text
自动化范围当前的设置是“创建 PR 后停止”；如后续需要调整自动化范围、需求来源、质量门严格度、测试重试次数或风险处理方式，也请随时告知我。
```

### 依赖环境

必需：

- 支持本地 skill 的 Codex。
- Python 3.10 或更高版本。
- Git。
- GitHub CLI `gh`，并且已经登录目标 GitHub 账号。
- 目标仓库有 push 权限。
- 已安装 companion skills：
  - `automated-dev-executor`
  - `ai-code-quality-gate`

完整质量门建议配置：

- GitHub Actions。
- lint 命令。
- typecheck 命令。
- test 命令。
- Semgrep。
- CodeQL。
- SonarQube 或 SonarCloud。
- Qodana。
- Qodo PR-Agent 或 CodeRabbit。

不是所有工具都必须同时存在。规则是：仓库已经配置了什么，loop 就必须认真执行什么；你明确要求必须执行什么，缺了就停下来。

### 触发方式

安装后，可以直接这样说：

```text
请使用 $codex-dev-loop 完成这个需求：docs/spec.md
```

也可以说得更完整：

```text
请使用 $codex-dev-loop 从 docs/spec.md 开始做完整自动开发。
要求：先出技术方案、测试计划、风险分析和开发计划；Subagent 评审通过后再实现；实现后跑测试和 ai-code-quality-gate；创建新分支、提交代码、推送并开 PR。
```

如果你只想让它先规划，不要写代码：

```text
请使用 $codex-dev-loop 只完成规划和 Subagent 评审，先不要改业务代码。
```

### 常见使用场景

| 任务 | 推荐说法 |
|---|---|
| 从需求文档开发一个功能 | `请使用 $codex-dev-loop 实现 docs/spec.md` |
| 从 Notion 页面开始 | `请使用 $codex-dev-loop 处理这个 Notion 页面` |
| 先审方案，不写代码 | `只做技术方案、测试计划、风险分析和 Subagent 评审` |
| 给已有 PR 补质量门 | `用 ai-code-quality-gate 检查当前分支，并补齐失败项` |
| 自动开发但严格停机 | `测试失败达到配置阈值、质量门失败、需求不清或缺 token 时停止` |

### Hook 和 gate 在哪里

这个 loop 里的“hook”不是 Git hook 那种 `pre-commit` 文件，而是由 harness 强制执行的阶段闸门。

关键闸门：

- 澄清闸门：`source.md` 的 Goal 和验收标准非空才允许进入规划；不清楚就留在 intake 阶段提问。
- 规划评审闸门：技术方案、测试计划、风险分析、规格 delta 必须通过 Subagent 评审。
- TDD 闸门：`- TDD: red` 单元没有失败的红测试证据，绿测试不予记录；`regression-only` 豁免必须写进计划并由 plan-reviewer 审批。
- 测试闸门：每个开发单元都要跑测试，结果写入记录；worktree 内的证据只是过程证据，合并后必须 `verify-units` 对最终代码树复验。
- 规格闸门：`record-spec-merge` 机械校验基线与 delta 一致（ADDED/MODIFIED 标题存在、REMOVED 标题消失），不一致不放行实现评审。
- 规模护栏：small 档跳过 risk_review 前，harness 检查变更集是否触及依赖清单、迁移、SQL、CI/CD、Docker、密钥或 auth/security 路径，命中即拒绝跳过。
- 质量闸门：调用 `ai-code-quality-gate`（未安装时用内置 fallback），已配置 profile gate 始终强制执行，`run-quality --require` 只能追加 gate。
- PR 闸门：检查 GitHub Actions 和 PR 级 AI review，并确认 PR 仓库与本地 `origin` 一致。
- 云端检查闸门：required check 用规范化后的精确名称匹配，或匹配已知扫描器别名（如 `SonarCloud Code Analysis` 可满足 `sonar`）；非必需的可选检查失败不会阻断。
- 指纹闸门：规划、评审、测试、规格合并和质量报告都绑定当前文件状态，防止复用旧报告。

### 为什么要这么麻烦

因为 AI 写代码最危险的地方不是“不会写”，而是：

- 看起来完成了，其实没有覆盖验收标准。
- 改了需求外的文件。
- 测试没跑，或者失败后继续推进。
- 静态检查、类型检查、安全扫描被跳过。
- PR 描述只说“done”，没有风险和验证证据。

`codex-dev-loop` 的设计思路是：让 Codex 可以自动推进，但每一步都留下证据；没有证据，就不能进入下一步。

### 目录结构

```text
codex-dev-loop/
  VERSION                          当前版本号
  SKILL.md                         skill 主文件（Codex）
  adapters/claude-code/SKILL.md    Claude Code 适配版 skill 文件
  agents/openai.yaml               Codex UI 展示信息
  scripts/
    configure_dev_loop.py          初次安装配置向导
    dev_loop_harness.py            状态机和阶段闸门
    test_gate.py                   内置测试闸门 fallback（未装 automated-dev-executor 时启用）
    quality_gate_fallback.py       内置质量闸门 fallback（未装 ai-code-quality-gate 时启用）
    self_test.py                   自测脚本（不依赖伴随 skill 即可全量运行）
    validate_dev_loop_artifacts.py 产物校验
  references/
    artifact-templates.md          规划产物模板
    git-pr-flow.md                 分支、提交、PR 流程
    github-actions-cloud.md        云端检查说明
    subagent-review-loop.md        Subagent 评审流程
    tdd-parallel-units.md          单元内 TDD 与 worktree 并行开发
    spec-baseline.md               规格基线与 delta 合并规则
  docs/sponsor.md                  赞助说明
  assets/wechat-pay-qr.jpg         赞助收款图片
```

### 权限说明

运行完整 loop 时，Codex 可能需要：

- 读取需求文档或 Notion 页面。
- 写入 `.codex/dev-loop/` 执行记录。
- 写入测试和质量门报告。
- 安装项目依赖。
- 创建 git 分支。
- 提交本地改动。
- 推送到 GitHub。
- 创建或更新 PR。
- 查询 GitHub Actions 检查状态。

遇到下面情况，loop 应该停下来问你：

- 需求不清。
- 测试失败达到配置阈值。
- 质量门失败。
- 发现架构、安全、数据迁移或兼容性风险。
- 缺少 GitHub token、服务 token 或 secret。
- 需要启用新的外部服务。
- 需要使用付费扫描服务。

### 第三方工具与引用说明

本仓库不内置或再分发以下工具，只在你已经安装或配置时进行协调调用：

- OpenAI Codex 和 Codex skills。
- GitHub、GitHub CLI、GitHub Actions。
- Notion。
- Semgrep。
- GitHub CodeQL。
- SonarQube 或 SonarCloud。
- JetBrains Qodana。
- Qodo PR-Agent。
- CodeRabbit。

README 的表达结构参考了 [op7418/guizang-ppt-skill](https://github.com/op7418/guizang-ppt-skill) 的公开文档风格，例如“30 秒开始”“适合 / 不适合”“示例请求”和“使用流程”。本项目未复用其代码、模板或图片资产。

所有产品名称、商标和 logo 均归其各自所有者所有。本文提及不代表获得背书或存在关联关系。

### 赞助

如果这个 skill 帮到了你的工作流，赞助会用于维护、示例、文档和兼容性更新。

查看：[赞助本项目](docs/sponsor.md)。

`assets/wechat-pay-qr.jpg` 是维护者提供的赞助收款资产，不在 MIT License 复用范围内。为降低合规风险，本项目不接受虚拟货币赞助。

### 许可证

除赞助收款资产另有说明外，代码和文档以 MIT License 发布。

## English

`codex-dev-loop` is an autonomous development loop for AI coding agents (Codex and Claude Code).

Give it a Notion page, a local Markdown spec, or just a rough idea. It first clarifies the requirement with you (Q&A recorded in a clarification log), agrees on a task scale (`small` / `standard` / `large` gate weight), then turns the input into a technical design, test plan, risk analysis, spec delta, and development plan. Subagents review those planning artifacts before implementation starts. Every unit is built test-first (red/green TDD gates; independent units can run in parallel git worktrees). After coding, the spec delta is merged into the repository's living `specs/` baseline on the same branch, and the loop runs tests, local quality gates, cloud checks, and PR-level review before the change is allowed to move forward.

The goal is straightforward: let the agent move development forward while clarification, TDD, reviews, quality gates, spec consolidation, and PR checks keep risk under control.

### 30-Second Start

Install into your local Codex skills directory (macOS / Linux):

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.codex/skills/codex-dev-loop
```

Windows (PowerShell):

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

Update an existing install:

```bash
git -C ~/.codex/skills/codex-dev-loop pull
```

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-dev-loop" pull
```

Before the first run, configure the five core preferences:

```bash
python ~/.codex/skills/codex-dev-loop/scripts/configure_dev_loop.py
```

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

Claude Code users install into `~/.claude/skills/` and swap in the adapter SKILL.md (see `adapters/claude-code/SKILL.md`):

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.claude/skills/codex-dev-loop
cp ~/.claude/skills/codex-dev-loop/adapters/claude-code/SKILL.md ~/.claude/skills/codex-dev-loop/SKILL.md
```

Restart Codex, then ask:

```text
Use $codex-dev-loop on docs/spec.md.
Ask me questions first if anything is unclear, and confirm the task scale before planning.
Create the technical design, test plan, risk analysis, spec delta, and development plan first.
Only implement after Subagent review passes, unit by unit, test-first (red then green).
After implementation, merge the spec baseline, run tests, ai-code-quality-gate, GitHub Actions, and PR review.
Then create a new branch, commit, push, and open a PR.
```

With only a rough idea:

```text
Use $codex-dev-loop with init --draft. I only have a rough idea: <your idea>.
Clarify the goal and acceptance criteria with me before planning anything.
```

### Good Fit / Bad Fit

Good fit:

- Feature work with a clear goal and acceptance criteria.
- Rough ideas too: start with `init --draft` and the intake phase interviews you until `Goal` and `Acceptance Criteria` are real (Q&A recorded in `clarification-log.md`); the harness refuses to plan before that.
- Repositories where AI-generated code must pass TDD, lint, typecheck, tests, and quality scans.
- Workflows that require a new branch, commit, PR, and GitHub Actions checks, with spec changes consolidated into the `specs/` baseline on the same PR.
- Teams that want design, test, risk, and spec-delta review before coding.
- Small fixes that should not carry the full pipeline: pick the `small` scale; the harness force-escalates when dependency, migration, CI, or security-sensitive paths change.
- Tasks where execution records matter.

Bad fit:

- Repositories where the agent cannot read files, write files, run commands, or use git. Start with planning-only mode.
- Codebases with no tests and no plan to add tests. The TDD gate requires a failing test per unit; a repo that refuses tests cannot pass the loop.
- Production config, database, or live infrastructure changes. Split the task into design review first, then human-controlled execution.
- Changes that must bypass quality gates. Reduce task scope or tune the gate profile instead of disabling all gates.

### What The Loop Does

| Stage | Action | Failure Behavior |
|---|---|---|
| Intake & clarification | Read Markdown / Notion / draft input; interview the user until goal and acceptance criteria are real | Planning refused while Goal or Acceptance Criteria are empty |
| Scale agreement | Confirm `small` / `standard` / `large` gate weight with the user | `small` force-escalates when sensitive paths change |
| Planning | Produce design, file scope, test plan, risk analysis, spec delta, and development plan | Stop on architecture risk |
| Subagent review | Cross-check plan, implementation approach, and risk | Revise and review again |
| TDD implementation | Record failing red evidence, then implement to green; independent units in parallel worktrees | Green runs are refused without red evidence |
| Test gate | Run tests for each unit; failure limit follows first-run config | Stop after the configured limit |
| Spec consolidation | Merge the spec delta into `specs/` and validate mechanically | Reviews blocked until baseline matches the delta |
| Local quality gate | Run `ai-code-quality-gate` (or the bundled fallback); strictness follows first-run config | Stop on quality failure |
| PR stage | Create branch, commit, push, and open PR | Stop if credentials are missing |
| Cloud checks | Verify GitHub Actions and PR-level AI review | Stop if checks fail or are missing |
| Archive | Move run records to `dev-loop-archive/` after completion | Next `init` refused until the previous run is archived |

### Full Workflow

1. Provide a Notion page, a local Markdown spec, or just an idea (`--draft`).
2. The agent initializes `.codex/dev-loop/`; the loop starts in the intake phase.
3. Unclear requirements trigger clarification questions (recorded in `clarification-log.md`); the task scale is agreed with you.
4. The agent creates planning artifacts:
   - `technical-design.md`
   - `test-plan.md`
   - `risk-analysis.md`
   - `development-plan.md` (each unit declares its TDD mode and dependencies)
   - `spec-delta.md` (requirement-level changes of this loop)
   - `decision-log.md`
5. Subagents review the planning artifacts.
6. The main agent revises the plan.
7. Subagents review again until the plan passes or a blocker is found.
8. Units are implemented test-first: failing red evidence, then green. Independent units can be built by unit-implementer Subagents in isolated git worktrees, with all evidence recorded serially by the orchestrator.
9. The spec delta is merged into the repository `specs/` baseline, validated by `record-spec-merge`, and `verify-units` re-runs every unit against the final tree.
10. The local `ai-code-quality-gate` (or the bundled fallback) runs lint, typecheck, tests, Semgrep, CodeQL, Sonar, Qodana, or the checks available in the target repository.
11. The agent creates a new branch and commits; in `commit_only` mode, it records the commit and completes.
12. When automation scope allows it, the agent pushes, opens a PR (spec baseline updates reviewed in the same PR), and waits for GitHub Actions plus PR-level AI review.
13. The loop writes execution records under `.codex/dev-loop/` and archives them to `.codex/dev-loop-archive/` after completion.

### Source Spec

Minimum spec:

```markdown
## Goal

Improve the error message shown after a failed login attempt.

## Acceptance Criteria

- Wrong-password responses show a clear but safe message.
- The frontend does not crash when the login API returns 401.
- Existing login tests still pass.
- A new test covers the 401 error message.
```

Better specs also include context, files out of scope, compatibility constraints, security constraints, migration constraints, and known risks.

### Installation

Ask Codex to install it:

```text
Install codex-dev-loop.
Clone https://github.com/Thyd/codex-dev-loop.git into ~/.codex/skills/codex-dev-loop.
After installation, verify SKILL.md, scripts/, references/, and agents/openai.yaml exist.
```

Or install manually (macOS / Linux, then Windows PowerShell):

```bash
git clone https://github.com/Thyd/codex-dev-loop.git ~/.codex/skills/codex-dev-loop
```

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

Restart Codex after installation.

### First-Run Configuration

Before the first run, start the setup wizard:

```bash
python ~/.codex/skills/codex-dev-loop/scripts/configure_dev_loop.py
```

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

It asks five questions:

| Question | Default | Impact |
|---|---|---|
| How far should automation go? | Stop after PR creation | Controls planning-only, commit-only, or PR flow |
| What source types do you use? | Markdown + Notion | Controls allowed requirement sources |
| How strict should quality gates be? | Standard | Controls required local and cloud gates |
| How many failed test attempts are allowed? | 3 | Controls when the loop stops on repeated test failures |
| What should happen on high risk? | Stop and ask | Controls unclear requirements, missing tokens, external services, security/data risk |

The config is written to:

```text
~/.codex/config/codex-dev-loop.json
```

The harness enforces these preferences: disabled source types are rejected during `init --source-type ...`, and `planning_only` / `commit_only` stop at their configured completion points.

The wizard ends with a note like:

```text
Automation scope is currently set to "Stop after PR creation"; tell me anytime if you want to adjust automation scope, source types, quality strictness, test retry count, or risk handling.
```

### Requirements

Required:

- Codex with local skill support.
- Python 3.10 or newer.
- Git.
- GitHub CLI `gh`, authenticated with the target GitHub account.
- Push access to the target repository.
- Installed companion skills:
  - `automated-dev-executor`
  - `ai-code-quality-gate`

Recommended for full quality enforcement:

- GitHub Actions.
- lint, typecheck, and test commands.
- Semgrep.
- CodeQL.
- SonarQube or SonarCloud.
- Qodana.
- Qodo PR-Agent or CodeRabbit.

Not every tool must exist in every repository. The rule is simple: if the repository has configured a check, the loop must run and respect it; if the user requires a check and it is missing, the loop stops.

### Example Requests

```text
Use $codex-dev-loop to implement docs/spec.md.
```

```text
Use $codex-dev-loop on this Notion page.
Stop and ask me if the requirement is unclear.
```

```text
Use $codex-dev-loop only for planning and Subagent review.
Do not edit product code yet.
```

### Hook And Gate Points

The loop does not rely on a Git `pre-commit` hook. Its hooks are harness-enforced stage gates:

- Clarification gate: planning is refused while `source.md` lacks a non-empty Goal and Acceptance Criteria; stay in intake and ask.
- Planning review gate (now including the spec delta).
- TDD gate: `- TDD: red` units need recorded failing red evidence before green counts; `regression-only` waivers must be in the plan and approved by plan review.
- Unit test gate; worktree evidence is interim, and `verify-units` must re-verify the merged tree.
- Spec gate: `record-spec-merge` mechanically checks the baseline against the delta (ADDED/MODIFIED titles present, REMOVED titles gone) before implementation review opens.
- Scale guard: the small-scale `risk_review` skip is refused when the change set touches dependency manifests, migrations, SQL, CI/CD, Docker, keys, or auth/security paths.
- Local quality gate through `ai-code-quality-gate` (bundled fallback when absent); configured profile gates always remain required, and `run-quality --require` can only add gates.
- PR and GitHub Actions gate; PR evidence must point to the same GitHub repository as local `origin`.
- Cloud check gate; required checks match by exact canonical name or known scanner aliases (for example `SonarCloud Code Analysis` satisfies `sonar`), while unrelated optional check failures do not block the loop.
- Fingerprint gate that prevents stale reports (plans, reviews, tests, spec merges, quality) from being reused.

### Repository Layout

```text
codex-dev-loop/
  VERSION
  SKILL.md
  adapters/claude-code/SKILL.md
  agents/openai.yaml
  scripts/
    configure_dev_loop.py
    dev_loop_harness.py
    test_gate.py
    quality_gate_fallback.py
    self_test.py
    validate_dev_loop_artifacts.py
  references/
    artifact-templates.md
    git-pr-flow.md
    github-actions-cloud.md
    subagent-review-loop.md
    tdd-parallel-units.md
    spec-baseline.md
  docs/sponsor.md
  assets/wechat-pay-qr.jpg
```

### Permissions

The loop may need to:

- Read a source Markdown file or Notion page.
- Write execution records under `.codex/dev-loop/`.
- Write test and quality reports.
- Install project dependencies.
- Create a git branch.
- Commit local changes.
- Push to GitHub.
- Create or update a PR.
- Query GitHub Actions checks.

It should stop before enabling new external services, using paid scanners, using missing tokens, accepting unclear requirements, continuing after repeated test failures, or accepting architecture/security/data risk outside scope.

### Third-Party Tools And References

This repository does not vendor or redistribute OpenAI Codex, GitHub, Notion, Semgrep, CodeQL, Sonar, Qodana, Qodo PR-Agent, or CodeRabbit. It coordinates those tools only when they are installed or configured by the user.

The README communication style is inspired by the public documentation structure of [op7418/guizang-ppt-skill](https://github.com/op7418/guizang-ppt-skill), such as quick start, fit/not-fit, example prompts, and workflow sections. No code, templates, or image assets from that project are reused here.

All product names, trademarks, and logos belong to their respective owners. Mentioning them here does not imply endorsement or affiliation.

### Sponsorship

If this skill helps your workflow, sponsorship supports maintenance, examples, documentation, and compatibility updates.

See [Sponsor this project](docs/sponsor.md).

The WeChat Pay QR image in `assets/wechat-pay-qr.jpg` is a maintainer-provided sponsorship asset. It is not licensed for reuse outside displaying sponsorship information for this repository. To reduce compliance risk, this project does not accept cryptocurrency sponsorships.

### License

Code and documentation are released under the MIT License, except where noted for sponsorship assets.
