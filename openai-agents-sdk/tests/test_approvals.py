from agent.approvals import command_needs_approval


class TestCommandNeedsApproval:
    def test_read_only_commands_run_freely(self):
        for cmd in ["ls -la", "cat README.md", "grep -r foo .", "rg -n foo", "wc -l x"]:
            assert command_needs_approval(cmd) is False, cmd

    def test_git_read_subcommands_run_freely(self):
        assert command_needs_approval("git status") is False
        assert command_needs_approval("git diff HEAD~1") is False

    def test_local_git_changes_run_freely(self):
        for cmd in [
            "git switch -c agent/fix",
            "git add -A",
            "git commit -m 'Fix the login test'",
            "git branch",
        ]:
            assert command_needs_approval(cmd) is False, cmd

    def test_git_that_publishes_or_discards_work_needs_approval(self):
        for cmd in [
            "git push origin main",
            "git reset --hard",
            "git checkout -- app.py",
            "git switch --discard-changes main",
            "git switch -f main",
            "git branch -D agent/old",
            "git branch -M main",
            "git clean -fd",
        ]:
            assert command_needs_approval(cmd) is True, cmd

    def test_git_options_before_the_subcommand_need_approval(self):
        assert command_needs_approval("git -c alias.x='!id' x") is True
        assert command_needs_approval("git -C /tmp status") is True

    def test_running_repo_code_needs_approval(self):
        for cmd in [
            "pytest -q",
            "python -c 'print(1)'",
            "npm test",
            "make",
            "pip install .",
        ]:
            assert command_needs_approval(cmd) is True, cmd

    def test_shell_syntax_after_a_read_only_command_needs_approval(self):
        for cmd in [
            "ls && rm -rf ~",
            "cat x | sh",
            "ls; rm -rf build",
            "cat README.md > /tmp/out",
            "ls $(rm -rf build)",
            "ls `rm -rf build`",
            "ls\nrm -rf build",
        ]:
            assert command_needs_approval(cmd) is True, cmd

    def test_options_that_run_or_write_need_approval(self):
        for cmd in [
            "find . -exec rm {} +",
            "find . -execdir rm {} +",
            "find . -delete",
            "rg --pre=./run foo",
            "tree -o out.txt",
            "git diff --output=/tmp/x",
        ]:
            assert command_needs_approval(cmd) is True, cmd

    def test_reading_outside_the_clone_needs_approval(self):
        for cmd in [
            "cat ~/.ssh/id_rsa",
            "cat /etc/passwd",
            "cat ../../.env",
            "find / -name '*.pem'",
            "grep -r SECRET ~",
            "grep -f/etc/passwd x",
            "rg --file=/etc/passwd x",
        ]:
            assert command_needs_approval(cmd) is True, cmd

    def test_reading_inside_the_clone_runs_freely(self):
        for cmd in [
            "cat src/app.py",
            "git diff HEAD~1",
            "ls ./tests",
            "grep -rn foo src",
        ]:
            assert command_needs_approval(cmd) is False, cmd

    def test_non_read_only_commands_need_approval(self):
        for cmd in ["rm -rf build", "curl http://example.com", "chmod +x x"]:
            assert command_needs_approval(cmd) is True, cmd

    def test_empty_or_unparseable_needs_approval(self):
        assert command_needs_approval("") is True
        assert command_needs_approval('echo "unbalanced') is True
