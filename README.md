# Codex Dev Loop

[中文](#中文) | [English](#english)

## 中文

非官方 Codex 社区 skill。本项目不隶属于 OpenAI，也未获得 OpenAI 赞助、背书或认可。

`codex-dev-loop` 是一个带保护闸门的自动化开发 loop。它把 Notion 页面或本地 Markdown 需求，从目标和验收标准推进到技术方案、Subagent 评审、代码实现、测试、质量门、git 分支、Pull Request 和 GitHub Actions 检查。

### 功能

- 支持本地 Markdown 需求，或复制到 `.codex/dev-loop/source.md` 的 Notion 页面内容。
- 编码前生成规划产物：
  - 技术方案
  - 文件和模块范围
  - 测试计划
  - 风险分析
  - 按可独立测试单元拆分的开发计划
- 三类 Subagent 评审：
  - `plan-reviewer`
  - `implementation-reviewer`
  - `risk-reviewer`
- 使用指纹校验，防止计划、测试、评审、质量报告、PR 记录或云端检查记录在改动后被复用。
- 通过 `automated-dev-executor` 强制执行单元测试门。
- 通过 `ai-code-quality-gate` 强制执行本地质量门。
- 覆盖 git 分支、提交、推送、PR 和 GitHub Actions 阶段。
- 要求 PR 级 AI review 检查，例如 Qodo PR-Agent、CodeRabbit 或其他已配置 AI review check。
- 默认 fail closed：需求不清、测试连续失败、质量门失败、架构/安全/数据风险、缺 token、云端检查失败或缺失都会停止。

### 仓库结构

```text
codex-dev-loop/
  SKILL.md
  agents/openai.yaml
  scripts/
    dev_loop_harness.py
    self_test.py
    validate_dev_loop_artifacts.py
  references/
    artifact-templates.md
    git-pr-flow.md
    github-actions-cloud.md
    subagent-review-loop.md
  docs/sponsor.md
  assets/
    wechat-pay-qr.jpg
    bitcoin-wallet-qr.jpg
```

### 安装方式

克隆仓库，并把 skill 目录复制到 Codex skills 目录：

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git
Copy-Item -Recurse -Force .\codex-dev-loop "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

安装后重启 Codex，让 Codex 重新发现 skill。

harness 会固定查找以下 companion skills：

```text
~/.codex/skills/automated-dev-executor
~/.codex/skills/ai-code-quality-gate
```

这是有意设计：质量门不应被任务目录里的假脚本替换。

### 依赖环境

必需：

- 支持本地 skill 的 Codex。
- Python 3.10 或更高版本。
- Git。
- GitHub CLI `gh`，并且已登录目标仓库有权限的账号。
- 已安装 companion skills：
  - `automated-dev-executor`
  - `ai-code-quality-gate`

完整 PR/云端门禁还需要：

- 有 push 权限的 GitHub 仓库。
- 启用 GitHub Actions。
- 可使用 `gh pr view` 和 `gh pr checks` 查询 PR 与检查状态。

可选，取决于目标仓库配置：

- Semgrep CLI。
- CodeQL CLI 或 GitHub CodeQL workflow。
- SonarQube 或 SonarCloud 配置。
- Qodana CLI 或 Qodana workflow。
- Qodo PR-Agent 或 CodeRabbit 作为 PR 级 review 工具。
- Notion connector，用于从 Notion 页面读取需求。

### 基本使用方式

准备一个至少包含以下内容的需求文档：

```markdown
## Goal

...

## Acceptance Criteria

- ...
```

初始化 loop 状态：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop init --source path/to/source.md
```

创建或更新必要规划产物：

```text
.codex/dev-loop/technical-design.md
.codex/dev-loop/test-plan.md
.codex/dev-loop/risk-analysis.md
.codex/dev-loop/development-plan.md
.codex/dev-loop/decision-log.md
```

请求 Subagent 评审前，先获取当前证据指纹：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop fingerprint
```

只能通过 harness 推进阶段：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop set-phase plan_review
```

运行单元测试门：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop run-test --unit dev-001 --command "npm test"
```

运行本地质量门：

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop run-quality
```

日常使用时，建议直接让 Codex 对 Notion 页面或 Markdown 需求使用 `$codex-dev-loop`。

### 权限说明

loop 可能需要：

- 读取源 Markdown 文件或 Notion 页面内容。
- 写入 `.codex/dev-loop/` 下的本地执行记录。
- 写入 `.codex/` 下的测试和质量门产物。
- 创建新的 git 分支。
- 提交本地改动。
- 推送到 GitHub。
- 创建或更新 GitHub Pull Request。
- 通过 `gh` 查询 GitHub Actions 检查状态。
- 安装运行测试或本地门禁所需的项目依赖。

遇到以下情况应停止并询问用户：

- 启用或调用尚未配置的非 GitHub 外部托管服务。
- 使用付费扫描服务。
- 需要缺失的 token 或 secret。
- 接受超出已批准范围的架构、安全、迁移、数据丢失或兼容性风险。

### 质量和安全模型

此 skill 默认 fail closed：

- 没有目标和验收标准的需求会被阻塞。
- 规划产物必须先通过评审，才能开始实现。
- 每个计划单元都必须有最新的 `passed` 测试状态。
- 每个单元最多允许 3 次失败测试尝试。
- 评审和测试都绑定到 plan/workspace 指纹。
- `run-quality` 直接调用已安装的 `ai-code-quality-gate`，并拒绝复用旧输出目录。
- 正常使用时，PR 和 GitHub Actions 证据通过 GitHub CLI 校验。

### 第三方工具与引用说明

本仓库不内置或再分发以下工具，只在用户已安装或已配置时进行协调或引用：

- OpenAI Codex 和 Codex skills。
- GitHub、GitHub CLI、GitHub Actions。
- Notion。
- Semgrep。
- GitHub CodeQL。
- SonarQube 或 SonarCloud。
- JetBrains Qodana。
- Qodo PR-Agent。
- CodeRabbit。

所有产品名称、商标和 logo 均归其各自所有者所有。本文提及不代表获得背书或存在关联关系。

### 赞助

如果这个 skill 帮到了你的工作流，赞助会用于维护、示例、文档和兼容性更新。

查看：[赞助本项目](docs/sponsor.md)。

`assets/wechat-pay-qr.jpg` 和 `assets/bitcoin-wallet-qr.jpg` 是维护者提供的赞助收款资产，不在 MIT License 复用范围内。

### 许可证

除赞助收款资产另有说明外，代码和文档以 MIT License 发布。

## English

Unofficial community skill for Codex. This project is not affiliated with, sponsored by, or endorsed by OpenAI.

`codex-dev-loop` is a guarded autonomous development loop for taking a Notion page or local Markdown spec from goal and acceptance criteria to technical design, Subagent review, implementation, tests, quality gates, a git branch, a pull request, and GitHub Actions verification.

### Features

- Intake from a local Markdown spec or a Notion page copied into `.codex/dev-loop/source.md`.
- Planning artifacts before coding:
  - technical design
  - file and module scope
  - test plan
  - risk analysis
  - unit-by-unit development plan
- Three-reviewer Subagent loop:
  - `plan-reviewer`
  - `implementation-reviewer`
  - `risk-reviewer`
- Fingerprint checks to prevent stale plans, tests, reviews, quality reports, PR records, or cloud-check records from being reused after changes.
- Forced unit test execution through `automated-dev-executor`.
- Required local quality gate through `ai-code-quality-gate`.
- Git branch, commit, push, PR, and GitHub Actions stages.
- GitHub PR-level review check requirement for Qodo PR-Agent, CodeRabbit, or another configured AI review check.
- Fail-closed blockers for unclear requirements, repeated test failures, quality failures, architecture/security/data risk, missing tokens, and failed or missing cloud checks.

### Repository Layout

```text
codex-dev-loop/
  SKILL.md
  agents/openai.yaml
  scripts/
    dev_loop_harness.py
    self_test.py
    validate_dev_loop_artifacts.py
  references/
    artifact-templates.md
    git-pr-flow.md
    github-actions-cloud.md
    subagent-review-loop.md
  docs/sponsor.md
  assets/
    wechat-pay-qr.jpg
    bitcoin-wallet-qr.jpg
```

### Installation

Clone this repository and copy the skill folder into your Codex skills directory:

```powershell
git clone https://github.com/Thyd/codex-dev-loop.git
Copy-Item -Recurse -Force .\codex-dev-loop "$env:USERPROFILE\.codex\skills\codex-dev-loop"
```

Restart Codex after installation so it can discover the new skill.

The harness intentionally expects companion skills under:

```text
~/.codex/skills/automated-dev-executor
~/.codex/skills/ai-code-quality-gate
```

This fixed lookup is deliberate: the quality gate should not be replaceable by a task-local fake script.

### Dependencies

Required:

- Codex with local skill support.
- Python 3.10 or newer.
- Git.
- GitHub CLI `gh`, authenticated with access to the target repository.
- Installed companion skills:
  - `automated-dev-executor`
  - `ai-code-quality-gate`

Required for full PR/cloud enforcement:

- GitHub repository with push access.
- GitHub Actions enabled.
- `gh pr view` and `gh pr checks` access.

Optional, depending on repository configuration:

- Semgrep CLI.
- CodeQL CLI or GitHub CodeQL workflow.
- SonarQube or SonarCloud configuration.
- Qodana CLI or Qodana workflow.
- Qodo PR-Agent or CodeRabbit as PR-level review tooling.
- Notion connector, when the source spec is a Notion page.

### Basic Usage

Prepare a source spec with at least:

```markdown
## Goal

...

## Acceptance Criteria

- ...
```

Initialize loop state:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop init --source path/to/source.md
```

Create or update the required planning artifacts:

```text
.codex/dev-loop/technical-design.md
.codex/dev-loop/test-plan.md
.codex/dev-loop/risk-analysis.md
.codex/dev-loop/development-plan.md
.codex/dev-loop/decision-log.md
```

Capture fingerprints before asking Subagents to review:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop fingerprint
```

Move through phases only with the harness:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop set-phase plan_review
```

Run a unit test gate:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop run-test --unit dev-001 --command "npm test"
```

Run the local quality gate:

```powershell
python "$env:USERPROFILE\.codex\skills\codex-dev-loop\scripts\dev_loop_harness.py" --root .codex/dev-loop run-quality
```

The normal workflow is best triggered by asking Codex to use `$codex-dev-loop` on a Notion page or Markdown spec.

### Permissions

The loop may need these permissions:

- Read the source Markdown file or Notion page content.
- Write local execution records under `.codex/dev-loop/`.
- Write local quality/test artifacts under `.codex/`.
- Create a new git branch.
- Commit local changes.
- Push to GitHub.
- Create or update a GitHub pull request.
- Query GitHub Actions checks through `gh`.
- Install local project dependencies required by tests or configured local gates.

The loop should stop and ask before:

- Enabling or calling non-GitHub external hosted services that are not already configured.
- Using paid scanner services.
- Using missing tokens or secrets.
- Accepting architecture, security, migration, data-loss, or compatibility risk outside the approved scope.

### Quality And Safety Model

This skill is designed to fail closed:

- Requirements without a goal and acceptance criteria are blocked.
- Planning artifacts must be reviewed before implementation.
- Every planned unit must have the latest test status `passed`.
- Tests are limited to three failed attempts per unit.
- Reviews and tests are bound to plan/workspace fingerprints.
- `run-quality` calls the installed `ai-code-quality-gate` script directly and refuses stale output directories.
- PR and GitHub Actions evidence is verified through GitHub CLI in normal use.

### Third-Party Tools And References

This repository does not vendor or redistribute the following tools. It coordinates or references them when they are installed or configured by the user:

- OpenAI Codex and Codex skills.
- GitHub, GitHub CLI, and GitHub Actions.
- Notion, when used as a spec source.
- Semgrep.
- GitHub CodeQL.
- SonarQube or SonarCloud.
- JetBrains Qodana.
- Qodo PR-Agent.
- CodeRabbit.

All product names, trademarks, and logos belong to their respective owners. Mentioning them here does not imply endorsement or affiliation.

### Sponsorship

If this skill helps your workflow, sponsorship supports maintenance, examples, documentation, and compatibility updates.

See [Sponsor this project](docs/sponsor.md).

The WeChat Pay QR image in `assets/wechat-pay-qr.jpg` and the Bitcoin wallet QR image in `assets/bitcoin-wallet-qr.jpg` are maintainer-provided sponsorship assets. They are not licensed for reuse outside displaying sponsorship information for this repository.

### License

Code and documentation are released under the MIT License, except where noted for sponsorship assets.
