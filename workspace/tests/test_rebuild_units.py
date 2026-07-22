"""Unit tests for the platform-rebuild core components (no LLM)."""

from src.state import SystemState
from src.tools.safety_gate import DESTRUCTIVE, _deterministic
from src.tools.template_guard import TemplateLeakDetector as T


def test_template_leaks():
    assert T.scan("<RESOLVED CONTENT>") == ["<RESOLVED CONTENT>"]
    assert T.scan("Docker installed: <RESULT>") == ["<RESULT>"]
    assert T.scan("Diag: {DIAGNOSIS}") == ["{DIAGNOSIS}"]
    assert T.scan("fix: <FIX_COMMAND>") == ["<FIX_COMMAND>"]
    # unexpanded shell variables (fileops writes literally — never interpolated)
    assert T.scan("$shell|$os|$listCmd") == ["$shell", "$os", "$listCmd"]
    # mixed: standalone $var plus a bare word — the $var is still a leak
    assert T.scan("$git_path\n|python_path") == ["$git_path"]
    assert T.scan("OS: $os") == ["$os"]
    assert T.scan("$(Get-CimInstance Win32_OperatingSystem)") == [
        "$(Get-CimInstance Win32_OperatingSystem)"
    ]
    assert T.scan("%USERPROFILE%") == ["%USERPROFILE%"]
    # lowercase / soft placeholders (the T010 leak that slipped through)
    assert T.scan("# Git\n<git_directory>\n# Python\n<python_directory>") == [
        "<git_directory>",
        "<python_directory>",
    ]
    assert T.scan("OS: <path>") == ["<path>"]
    assert T.scan("name: <your value here>") == ["<your value here>"]
    # clean content must NOT be flagged
    assert T.scan("<html><body><div>hi</div></body></html>") == []
    assert T.scan("<section><header>Title</header></section>") == []
    assert T.scan("Use <Enter> to continue") == []  # single word, not a placeholder keyword
    assert T.scan("OS: Windows 10\nHome: C:/Users/x") == []
    assert T.scan("def f(x): return x  # ok") == []
    assert T.scan("shared line\nversion A\nversion B") == []
    # legitimate content that merely CONTAINS a $ is allowed
    assert T.scan("API_KEY=$SECRET\nPORT=8080") == []
    assert T.scan("Price is $5 per unit") == []
    assert T.scan("export PATH=$PATH:/usr/local/bin") == []


def test_safety_deterministic():
    danger = "rm -" + "rf /"
    assert _deterministic(danger) == DESTRUCTIVE
    assert _deterministic("delete everything and reinstall the whole system") == DESTRUCTIVE
    assert _deterministic("format c:") == DESTRUCTIVE
    assert _deterministic("install numpy") is None
    assert _deterministic("delete node_modules") is None


def test_resolve_placeholders():
    facts = [
        "git.exe -> C:\\Program Files\\Git\\cmd\\git.exe\ndirectory: C:\\Program Files\\Git\\cmd",
        "python.exe -> C:\\Py\\python.exe\ndirectory: C:\\Py",
    ]
    content = "# Git\n<git_directory>\n# Python\n<python_directory>"
    resolved, unresolved = T.resolve(content, facts)
    assert unresolved == [], unresolved
    assert "C:\\Program Files\\Git\\cmd" in resolved
    assert "C:\\Py" in resolved
    assert "<git_directory>" not in resolved
    # path aspect
    r2, u2 = T.resolve("git at <git_path>", facts)
    assert u2 == [] and "git.exe" in r2
    # unresolvable placeholder stays unresolved
    r3, u3 = T.resolve("<unknown_thing>", facts)
    assert u3 == ["<unknown_thing>"]
    # dict facts: resolve by KEY match (environment facts)
    env_facts = {
        "os_name": "Windows",
        "os_version": "10.0.19045",
        "home_directory": "C:\\Users\\ExampleUser",
        "user": "ExampleUser",
    }
    content = "OS: <os_name>\nVersion: <os_version>\nHome: <home_directory>"
    resolved, unresolved = T.resolve(content, env_facts)
    assert unresolved == [], unresolved
    assert (
        "Windows" in resolved and "10.0.19045" in resolved and "C:\\Users\\ExampleUser" in resolved
    )


def test_locate():
    from pathlib import Path

    from src.tools.fileops import dispatch

    ok, out = dispatch("locate", ["python"], Path("."))
    assert ok and "python" in out.lower() and "directory:" in out, out
    ok2, out2 = dispatch("locate", ["definitely_not_a_real_tool_xyz"], Path("."))
    assert not ok2 and "not found" in out2.lower()


def test_strip_error_noise():
    from src.tools.observer import _strip_error_noise as s

    # error-only output → empty (discovery did not really succeed)
    assert s("Select-Object : Property cannot be found\nAt line:1 char:74\n+ ... foo") == ""
    assert s("openssl : The term 'openssl' is not recognized") == ""
    # real data survives
    assert s("C:/Program Files/Git/cmd/git.exe") == "C:/Program Files/Git/cmd/git.exe"
    # mixed: keep the data line, drop the error line
    mixed = s("C:/Program Files/Git/cmd/git.exe\nSelect-Object : Property cannot be found")
    assert "git.exe" in mixed
    assert "cannot be found" not in mixed


def test_system_state():
    s = SystemState(".")
    s.observe_capability("openssl --version", 1, "openssl : The term 'openssl' is not recognized")
    s.observe_capability("certutil -v", 0, "ok")
    assert s.is_available("openssl") is False
    assert s.is_available("certutil") is True
    assert "certutil" in s.available_tools()
    assert "openssl" in s.unavailable_tools()
    s.add_discovery("find git", "C:/Program Files/Git/cmd/git.exe")
    assert "git" in s.facts_summary()


if __name__ == "__main__":
    test_template_leaks()
    print("TemplateLeakDetector OK")
    test_safety_deterministic()
    print("safety deterministic OK")
    test_resolve_placeholders()
    print("resolve_placeholders OK")
    test_strip_error_noise()
    print("strip_error_noise OK")
    test_locate()
    print("locate OK")
    test_system_state()
    print("SystemState OK")
    print("ALL REBUILD UNITS PASS")
