#!/usr/bin/env python3
"""First-run configuration wizard for codex-dev-loop."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


DEFAULT_OUTPUT = Path.home() / ".codex" / "config" / "codex-dev-loop.json"
SCHEMA_VERSION = 1

QUESTIONS = {
    "automation_level": {
        "prompt": "1. 你希望自动化到哪一步？",
        "default": "pr_without_merge",
        "options": [
            ("pr_without_merge", "创建 PR 后停止", "自动规划、开发、测试、提交、推送、开 PR，但不自动合并。"),
            ("commit_only", "提交后停止", "自动开发和测试，但不推送、不创建 PR。"),
            ("planning_only", "只做规划", "只生成方案和评审，不写代码。"),
        ],
    },
    "source_types": {
        "prompt": "2. 需求来源主要是什么？",
        "default": "markdown_notion",
        "options": [
            ("markdown_notion", "Markdown + Notion", "同时支持本地 Markdown 和 Notion 页面。"),
            ("markdown", "只用 Markdown", "只从本地 Markdown 文档读取需求。"),
            ("notion", "只用 Notion", "只从 Notion 页面读取需求。"),
        ],
    },
    "quality_profile": {
        "prompt": "3. 质量门严格度选哪种？",
        "default": "standard",
        "options": [
            ("standard", "标准", "强制 lint、typecheck、test、ai-code-quality-gate、GitHub Actions、PR review。"),
            ("strict", "严格", "标准项 + Semgrep / CodeQL / Sonar / Qodana 可用时必须通过。"),
            ("light", "轻量", "只强制 test 和 ai-code-quality-gate。"),
        ],
    },
    "test_failure_limit": {
        "prompt": "4. 测试失败允许自动修复几次？",
        "default": "3",
        "options": [
            ("3", "3 次", "默认值，给自动修复留出空间。"),
            ("2", "2 次", "更快停止。"),
            ("1", "1 次", "非常保守。"),
            ("0", "失败就停止", "第一次失败就停下询问。"),
        ],
    },
    "risk_mode": {
        "prompt": "5. 遇到高风险情况时怎么处理？",
        "default": "stop_and_ask",
        "options": [
            ("stop_and_ask", "停止并询问", "需求不清、质量门失败、架构/安全/数据风险、缺 token、需要外部服务时都停下。"),
            ("serious_only", "只在严重风险时停止", "普通问题允许继续尝试修复。"),
            ("best_effort", "尽量自动推进", "仅在无法继续时停止。"),
        ],
    },
}

LABELS = {key: {value: label for value, label, _ in spec["options"]} for key, spec in QUESTIONS.items()}
SOURCE_MAP = {
    "markdown_notion": ["markdown", "notion"],
    "markdown": ["markdown"],
    "notion": ["notion"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure codex-dev-loop first-run preferences.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Config JSON path.")
    parser.add_argument("--non-interactive", action="store_true", help="Write defaults or supplied values without prompting.")
    parser.add_argument("--automation-level", choices=[value for value, _, _ in QUESTIONS["automation_level"]["options"]])
    parser.add_argument("--source-types", choices=[value for value, _, _ in QUESTIONS["source_types"]["options"]])
    parser.add_argument("--quality-profile", choices=[value for value, _, _ in QUESTIONS["quality_profile"]["options"]])
    parser.add_argument("--test-failure-limit", choices=[value for value, _, _ in QUESTIONS["test_failure_limit"]["options"]])
    parser.add_argument("--risk-mode", choices=[value for value, _, _ in QUESTIONS["risk_mode"]["options"]])
    return parser.parse_args()


def choose(key: str, supplied: str | None, non_interactive: bool) -> str:
    spec = QUESTIONS[key]
    if supplied:
        return supplied
    if non_interactive:
        return str(spec["default"])

    print()
    print(spec["prompt"])
    for index, (_value, label, description) in enumerate(spec["options"], start=1):
        suffix = "（默认）" if _value == spec["default"] else ""
        print(f"  {index}. {label}{suffix} - {description}")

    while True:
        raw = input("请选择序号，直接回车使用默认值：").strip()
        if not raw:
            return str(spec["default"])
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(spec["options"]):
                return str(spec["options"][index - 1][0])
        print("输入无效，请重新选择。")


def build_config(args: argparse.Namespace) -> dict:
    automation_level = choose("automation_level", args.automation_level, args.non_interactive)
    source_choice = choose("source_types", args.source_types, args.non_interactive)
    quality_profile = choose("quality_profile", args.quality_profile, args.non_interactive)
    test_failure_limit = choose("test_failure_limit", args.test_failure_limit, args.non_interactive)
    risk_mode = choose("risk_mode", args.risk_mode, args.non_interactive)
    return {
        "schema_version": SCHEMA_VERSION,
        "configured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "automation_level": automation_level,
        "source_types": SOURCE_MAP[source_choice],
        "quality_profile": quality_profile,
        "test_failure_limit": int(test_failure_limit),
        "risk_mode": risk_mode,
    }


def source_label(config: dict) -> str:
    source_types = config["source_types"]
    if source_types == ["markdown", "notion"]:
        return "Markdown + Notion"
    if source_types == ["markdown"]:
        return "只用 Markdown"
    if source_types == ["notion"]:
        return "只用 Notion"
    return ", ".join(source_types)


def print_summary(config: dict, output: Path) -> None:
    print()
    print("已完成 codex-dev-loop 初始配置。")
    print()
    print("当前设置：")
    print(f"- 自动化范围：{LABELS['automation_level'][config['automation_level']]}")
    print(f"- 需求来源：{source_label(config)}")
    print(f"- 质量门严格度：{LABELS['quality_profile'][config['quality_profile']]}")
    limit = config["test_failure_limit"]
    limit_label = "失败就停止" if limit == 0 else f"{limit} 次"
    print(f"- 测试失败自动修复次数：{limit_label}")
    print(f"- 高风险处理方式：{LABELS['risk_mode'][config['risk_mode']]}")
    print()
    print(f"配置文件：{output}")
    print(
        f"自动化范围当前的设置是“{LABELS['automation_level'][config['automation_level']]}”；"
        "如后续需要调整自动化范围、需求来源、质量门严格度、测试重试次数或风险处理方式，也请随时告知我。"
    )


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    config = build_config(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(config, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
