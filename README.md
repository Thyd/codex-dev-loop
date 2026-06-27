# Codex Dev Loop · 从需求到 PR 的自动开发 loop

![Skill](https://img.shields.io/badge/Skill-Codex-111111?style=flat-square)
![Version](https://img.shields.io/badge/Version-v0.2.2-blue?style=flat-square)
![Quality Gate](https://img.shields.io/badge/Quality%20Gate-required-0A7CFF?style=flat-square)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-supported-2088FF?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

[中文](#中文) | [English](#english)

> 非官方 Codex 社区 skill。本项目不隶属于 OpenAI，也未获得 OpenAI 赞助、背书或认可。

## 中文

你可以把 `codex-dev-loop` 理解成一条给 Codex 用的自动开发流水线。

它做的事很直接：给它一份 Notion 页面或 Markdown 需求，它会先补齐技术方案、测试计划、风险分析和开发计划；这些东西通过 Subagent 评审后，才开始写代码；写完后必须跑测试、质量门、云端检查和 PR 级 review，最后再提交代码和创建 PR。

目标很明确：让 Codex 自动推进开发，同时让测试、评审、质量门和 PR 检查持续拦住风险。

### 30 秒开始

安装到本地 Codex skills 目录：

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

如果已经安装过，用这条更新：

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-dev-loop" pull
```

初次使用前，运行 5 问配置：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

安装后重启 Codex，然后把下面这段话发给 Codex：

```text
请使用 $codex-dev-loop 处理 docs/spec.md。
从目标和验收标准开始，先补齐技术方案、测试计划、风险分析和开发计划。
规划产物通过 Subagent 评审后再实现。
实现完成后自动跑测试、ai-code-quality-gate、GitHub Actions 和 PR review。
通过后创建新分支、提交代码并发起 PR。
```

如果你的需求在 Notion 里，也可以这样说：

```text
请使用 $codex-dev-loop 处理这个 Notion 页面。
如果信息不足，先停下来问我；不要直接开始写代码。
```

### 适合 / 不适合

适合：

- 有明确目标和验收标准的功能开发。
- 希望 AI 自动写代码，但又不想绕过 lint、typecheck、test 和安全扫描。
- 希望每次开发都走新分支、提交、PR 和 GitHub Actions。
- 希望在写代码前，让 Subagent 先审技术方案、测试计划和风险。
- 希望把自动开发过程留下记录，方便回溯。

不适合：

- 只有一句模糊想法，没有目标和验收标准。建议先补一版 `Goal` 和 `Acceptance Criteria`，再启动 loop。
- 不允许 Codex 读写文件、运行命令或操作 git。建议先使用“只做规划”模式，等方案确认后再开放执行权限。
- 没有测试，也不准备补测试的仓库。建议先补最小 smoke test 或关键路径测试，否则自动开发没有可靠刹车。
- 需要直接改生产环境、数据库或线上配置的任务。建议拆成设计评审和人工执行两步，先让 loop 输出风险和迁移方案。
- 需要绕过质量门、强行合并或“先上再说”的任务。建议降低任务范围或调整质量门配置，不建议关闭所有 gate。

### 它会帮你做什么

| 阶段 | 它会做的事 | 不通过时会怎样 |
|---|---|---|
| 需求读取 | 读取 Markdown 或 Notion 页面，检查目标和验收标准 | 需求不清就停止 |
| 方案补齐 | 生成技术方案、文件范围、测试计划、风险分析、开发计划 | 发现架构风险就停止 |
| Subagent 评审 | 让 plan / implementation / risk 三类 reviewer 交叉检查 | 评审不通过就修改后重审 |
| 自动开发 | 按可独立测试的单元逐步实现 | 不跳步 |
| 测试门 | 每个单元都要跑测试，失败次数按初始配置控制 | 达到配置阈值就停止 |
| 本地质量门 | 强制调用 `ai-code-quality-gate`，严格度按初始配置控制 | 质量门失败就停止 |
| PR 阶段 | 创建分支、提交、推送、开 PR | 缺权限或 token 就停止 |
| 云端检查 | 检查 GitHub Actions、PR review、Qodo PR-Agent 或 CodeRabbit | 检查失败或缺失就停止 |

### 一次完整流程

1. 你提供一个需求：Notion 页面或本地 Markdown。
2. Codex 初始化 `.codex/dev-loop/` 执行目录。
3. Codex 生成这些规划文件：
   - `technical-design.md`
   - `test-plan.md`
   - `risk-analysis.md`
   - `development-plan.md`
   - `decision-log.md`
4. Subagent 评审规划产物。
5. 主 agent 根据评审意见修改。
6. Subagent 再审，直到通过或发现必须停止的问题。
7. Codex 按开发计划一小步一小步写代码。
8. 每个开发单元都必须跑对应测试。
9. 本地运行 `ai-code-quality-gate`，覆盖 lint、typecheck、test、Semgrep、CodeQL、Sonar、Qodana 等可用检查。
10. 创建新分支并提交代码；如果是 `commit_only` 模式，记录 commit 后完成。
11. 如果自动化范围允许，推送到 GitHub、创建 PR，并等待 GitHub Actions 和 PR 级 AI review。
12. 把过程记录写回 `.codex/dev-loop/`。

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

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

方式三：更新到最新版。

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-dev-loop" pull
```

安装后重启 Codex，让 Codex 重新发现 skill。

### 初次配置

首次使用前，建议运行一次配置向导：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

它只问 5 个问题：

| 问题 | 默认值 | 影响 |
|---|---|---|
| 你希望自动化到哪一步？ | 创建 PR 后停止 | 决定是否只规划、只提交，还是开 PR 后停止 |
| 需求来源主要是什么？ | Markdown + Notion | 决定允许从哪些来源读取需求 |
| 质量门严格度选哪种？ | 标准 | 决定强制哪些本地质量门和云端检查 |
| 测试失败允许自动修复几次？ | 3 次 | 决定同一测试门失败几次后停止 |
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

- 规划评审闸门：技术方案、测试计划、风险分析必须通过 Subagent 评审。
- 测试闸门：每个开发单元都要跑测试，结果写入记录。
- 质量闸门：调用 `ai-code-quality-gate`，已配置 profile gate 始终强制执行，`run-quality --require` 只能追加 gate。
- PR 闸门：检查 GitHub Actions 和 PR 级 AI review，并确认 PR 仓库与本地 `origin` 一致。
- 云端检查闸门：required check 用规范化后的精确名称匹配；非必需的可选检查失败不会阻断。
- 指纹闸门：规划、评审、测试和质量报告都绑定当前文件状态，防止复用旧报告。

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
  SKILL.md                         skill 主文件
  agents/openai.yaml               Codex UI 展示信息
  scripts/
    configure_dev_loop.py          初次安装配置向导
    dev_loop_harness.py            状态机和阶段闸门
    self_test.py                   自测脚本
    validate_dev_loop_artifacts.py 产物校验
  references/
    artifact-templates.md          规划产物模板
    git-pr-flow.md                 分支、提交、PR 流程
    github-actions-cloud.md        云端检查说明
    subagent-review-loop.md        Subagent 评审流程
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

`codex-dev-loop` is an autonomous development loop for Codex.

Give it a Notion page or a local Markdown spec. It turns that input into a technical design, test plan, risk analysis, and development plan. Subagents review those planning artifacts before implementation starts. After coding, the loop runs tests, local quality gates, cloud checks, and PR-level review before the change is allowed to move forward.

The goal is straightforward: let Codex move development forward while tests, reviews, quality gates, and PR checks keep risk under control.

### 30-Second Start

Install into your local Codex skills directory:

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

Update an existing install:

```powershell
git -C "$env:USERPROFILE\.codex\skills\codex-dev-loop" pull
```

Before the first run, configure the five core preferences:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\configure_dev_loop.py"
```

Restart Codex, then ask:

```text
Use $codex-dev-loop on docs/spec.md.
Start from the goal and acceptance criteria.
Create the technical design, test plan, risk analysis, and development plan first.
Only implement after Subagent review passes.
After implementation, run tests, ai-code-quality-gate, GitHub Actions, and PR review.
Then create a new branch, commit, push, and open a PR.
```

### Good Fit / Bad Fit

Good fit:

- Feature work with a clear goal and acceptance criteria.
- Repositories where AI-generated code must pass lint, typecheck, tests, and quality scans.
- Workflows that require a new branch, commit, PR, and GitHub Actions checks.
- Teams that want design, test, and risk review before coding.
- Tasks where execution records matter.

Bad fit:

- Vague ideas without acceptance criteria. First write a small `Goal` and `Acceptance Criteria` section.
- Repositories where Codex cannot read files, write files, run commands, or use git. Start with planning-only mode.
- Codebases with no tests and no plan to add tests. Add a smoke test or critical-path test first.
- Production config, database, or live infrastructure changes. Split the task into design review first, then human-controlled execution.
- Changes that must bypass quality gates. Reduce task scope or tune the gate profile instead of disabling all gates.

### What The Loop Does

| Stage | Action | Failure Behavior |
|---|---|---|
| Intake | Read Markdown or Notion input and check goal plus acceptance criteria | Stop if unclear |
| Planning | Produce design, file scope, test plan, risk analysis, and development plan | Stop on architecture risk |
| Subagent review | Cross-check plan, implementation approach, and risk | Revise and review again |
| Implementation | Build one independently testable unit at a time | Do not skip units |
| Test gate | Run tests for each unit; failure limit follows first-run config | Stop after the configured limit |
| Local quality gate | Run `ai-code-quality-gate`; strictness follows first-run config | Stop on quality failure |
| PR stage | Create branch, commit, push, and open PR | Stop if credentials are missing |
| Cloud checks | Verify GitHub Actions and PR-level AI review | Stop if checks fail or are missing |

### Full Workflow

1. Provide a Notion page or local Markdown spec.
2. Codex initializes `.codex/dev-loop/`.
3. Codex creates planning artifacts:
   - `technical-design.md`
   - `test-plan.md`
   - `risk-analysis.md`
   - `development-plan.md`
   - `decision-log.md`
4. Subagents review the planning artifacts.
5. The main agent revises the plan.
6. Subagents review again until the plan passes or a blocker is found.
7. Codex implements the development plan unit by unit.
8. Each unit must pass its tests.
9. The local `ai-code-quality-gate` runs lint, typecheck, tests, Semgrep, CodeQL, Sonar, Qodana, or the checks available in the target repository.
10. Codex creates a new branch and commits; in `commit_only` mode, it records the commit and completes.
11. When automation scope allows it, Codex pushes, opens a PR, and waits for GitHub Actions plus PR-level AI review.
12. The loop writes execution records under `.codex/dev-loop/`.

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

Or install manually:

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

Restart Codex after installation.

### First-Run Configuration

Before the first run, start the setup wizard:

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

- Planning review gate.
- Unit test gate.
- Local quality gate through `ai-code-quality-gate`; configured profile gates always remain required, and `run-quality --require` can only add gates.
- PR and GitHub Actions gate; PR evidence must point to the same GitHub repository as local `origin`.
- Cloud check gate; required checks use exact canonical-name matching, while unrelated optional check failures do not block the loop.
- Fingerprint gate that prevents stale reports from being reused.

### Repository Layout

```text
codex-dev-loop/
  VERSION
  SKILL.md
  agents/openai.yaml
  scripts/
    configure_dev_loop.py
    dev_loop_harness.py
    self_test.py
    validate_dev_loop_artifacts.py
  references/
    artifact-templates.md
    git-pr-flow.md
    github-actions-cloud.md
    subagent-review-loop.md
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
