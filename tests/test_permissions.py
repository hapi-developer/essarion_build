"""Permission policy: allow / ask / deny for the autonomous executor."""

from __future__ import annotations

from essarion_build.agent._permissions import ALLOW, ASK, DENY, PermissionPolicy


def test_reads_and_normal_actions_allowed() -> None:
    p = PermissionPolicy()
    assert p.decide("read_file", {"path": "x"})[0] == ALLOW
    assert p.decide("list_dir", {"path": "."})[0] == ALLOW
    assert p.decide("write_file", {"path": "a", "content": "x"})[0] == ALLOW
    assert p.decide("run_shell", {"cmd": "ls -l"})[0] == ALLOW
    assert p.decide("run_shell", {"cmd": "npm test"})[0] == ALLOW


def test_catastrophic_always_denied_even_with_yolo() -> None:
    p = PermissionPolicy()
    for cmd in ["rm -rf /", "rm -rf ~", "rm -rf / --no-preserve-root",
                ":(){ :|:& };:", "mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/sda"]:
        assert p.decide("run_shell", {"cmd": cmd}, yolo=True)[0] == DENY, cmd


def test_risky_asks_and_yolo_downgrades_to_allow() -> None:
    p = PermissionPolicy()
    assert p.decide("run_shell", {"cmd": "sudo apt update"})[0] == ASK
    assert p.decide("run_shell", {"cmd": "git push --force origin main"})[0] == ASK
    assert p.decide("run_shell", {"cmd": "rm -rf build/"})[0] == ASK
    # /yolo turns risky 'ask' into 'allow' (but not catastrophic — see above).
    assert p.decide("run_shell", {"cmd": "sudo apt update"}, yolo=True)[0] == ALLOW


def test_from_config_overrides() -> None:
    p = PermissionPolicy.from_config({
        "shell": "ask",
        "allow": [r"\bls\b"],
        "deny": [r"\bterraform\s+destroy\b"],
    })
    assert p.decide("run_shell", {"cmd": "ls -l"})[0] == ALLOW       # allow pattern wins
    assert p.decide("run_shell", {"cmd": "cat file"})[0] == ASK       # shell default → ask
    assert p.decide("run_shell", {"cmd": "terraform destroy"})[0] == DENY
    assert p.decide("read_file", {"path": "x"})[0] == ALLOW           # reads still free


def test_explicit_shell_deny_is_not_downgraded_for_risky_commands() -> None:
    """A configured `shell = "deny"` must block EVERY shell command, including
    the risky ones — the risk heuristics must not relax an explicit deny down to
    ask/allow (even under /yolo)."""
    p = PermissionPolicy.from_config({"shell": "deny"})
    for cmd in ["ls -l", "sudo apt update", "git push --force origin main", "rm -rf build/"]:
        assert p.decide("run_shell", {"cmd": cmd})[0] == DENY, cmd
        assert p.decide("run_shell", {"cmd": cmd}, yolo=True)[0] == DENY, cmd


def test_explicit_deny_still_yields_to_a_specific_allow_pattern() -> None:
    """An explicit allow-pattern is more specific than the blanket shell deny, so
    it still wins (only the risk-heuristic downgrade is forbidden)."""
    p = PermissionPolicy.from_config({"shell": "deny", "allow": [r"\bnpm test\b"]})
    assert p.decide("run_shell", {"cmd": "npm test"})[0] == ALLOW
    assert p.decide("run_shell", {"cmd": "npm publish"})[0] == DENY
