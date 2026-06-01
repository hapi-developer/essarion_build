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
