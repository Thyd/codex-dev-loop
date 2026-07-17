from scripts.validate_skill_package import frontmatter_problem


def test_frontmatter_problem_accepts_crlf_line_endings(workspace_tmp_path):
    skill_file = workspace_tmp_path / "SKILL.md"
    skill_file.write_bytes(
        b"---\r\n"
        b"name: demo-skill\r\n"
        b"description: Demo skill.\r\n"
        b"---\r\n"
        b"# Demo Skill\r\n"
    )

    assert frontmatter_problem(skill_file) == ""
