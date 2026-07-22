"""
Unit tests for the OS Capability Knowledge Engine (OCKE).

Tests are deterministic — they do not call any LLM.
Each test exercises one layer of the pipeline.
"""

import pytest
from src.knowledge.command_registry import CommandRegistry, intents_from_text
from src.knowledge.environment_detector import (
    EnvironmentProfile,
    _extract_windows_major,
    _normalize_distro,
    detect,
)
from src.knowledge.knowledge_loader import (
    KnowledgeEntry,
    _entry_matches_profile,
    forbidden_platform_tags,
    load_for_profile,
)
from src.knowledge.knowledge_validator import KnowledgeValidator, validate_command
from src.knowledge.ocke import OCKE

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _win_profile(**kw) -> EnvironmentProfile:
    defaults = dict(
        os_name="windows",
        os_version="10.0.19045",
        os_major=10,
        shell="powershell",
        package_managers=["pip", "winget"],
        capabilities=["python", "pip", "git"],
        architecture="x86_64",
    )
    defaults.update(kw)
    return EnvironmentProfile(**defaults)


def _linux_profile(distro="ubuntu", **kw) -> EnvironmentProfile:
    defaults = dict(
        os_name="linux",
        os_version="5.15.0",
        os_major=5,
        distro=distro,
        shell="bash",
        package_managers=["pip", "apt"],
        capabilities=["python3", "pip", "git", "apt"],
        architecture="x86_64",
    )
    defaults.update(kw)
    return EnvironmentProfile(**defaults)


def _macos_profile(**kw) -> EnvironmentProfile:
    defaults = dict(
        os_name="darwin",
        os_version="14.1.0",
        os_major=14,
        shell="zsh",
        package_managers=["pip", "brew"],
        capabilities=["python3", "pip3", "git", "brew"],
        architecture="arm64",
    )
    defaults.update(kw)
    return EnvironmentProfile(**defaults)


# ── EnvironmentProfile tests ──────────────────────────────────────────────────


class TestEnvironmentProfile:
    def test_windows_major_from_build_number(self):
        assert _extract_windows_major("10.0.22000") == 11
        assert _extract_windows_major("10.0.19045") == 10
        assert _extract_windows_major("10.0.21999") == 10
        assert _extract_windows_major("bad") == 0

    def test_distro_normalization(self):
        assert _normalize_distro("ubuntu") == "ubuntu"
        assert _normalize_distro("linuxmint") == "mint"
        assert _normalize_distro("pop_os_something") == "pop_os"
        assert _normalize_distro("unknowndistro") == "unknowndistro"

    def test_windows_forbidden_shells(self):
        p = _win_profile(shell="powershell")
        forbidden = p.forbidden_shells
        assert "bash" in forbidden
        assert "zsh" in forbidden
        assert "powershell" not in forbidden

    def test_linux_active_shells(self):
        p = _linux_profile()
        assert "bash" in p.active_shells

    def test_has_capability(self):
        p = _win_profile(capabilities=["python", "git"])
        assert p.has_capability("python")
        assert p.has_capability("Python")  # case-insensitive
        assert not p.has_capability("docker")

    def test_has_package_manager(self):
        p = _win_profile(package_managers=["pip", "winget"])
        assert p.has_package_manager("pip")
        assert not p.has_package_manager("apt")

    def test_detect_returns_profile(self):
        p = detect(force=True)
        assert p.os_name in ("windows", "linux", "darwin")
        assert p.shell
        assert isinstance(p.package_managers, list)


# ── Knowledge Loader tests ─────────────────────────────────────────────────────


class TestKnowledgeLoader:
    def _make_entry(
        self, platform="windows", shell=None, distros=None, requires=None, forbidden_shells=None
    ) -> KnowledgeEntry:
        return KnowledgeEntry(
            id="test_entry",
            platform=[platform] if isinstance(platform, str) else platform,
            shell=shell or [],
            intent=["install_global"],
            command="pip install $PACKAGE",
            forbidden_shells=forbidden_shells or [],
            distros=distros or [],
            requires=requires or [],
        )

    def test_platform_match_windows(self):
        e = self._make_entry(platform="windows")
        assert _entry_matches_profile(e, _win_profile())

    def test_platform_reject_linux_on_windows(self):
        e = self._make_entry(platform="linux")
        assert not _entry_matches_profile(e, _win_profile())

    def test_shell_forbidden_blocks(self):
        e = self._make_entry(platform="windows", forbidden_shells=["powershell"])
        assert not _entry_matches_profile(e, _win_profile(shell="powershell"))

    def test_shell_allowlist_filters(self):
        e = self._make_entry(platform="windows", shell=["cmd"])
        assert not _entry_matches_profile(e, _win_profile(shell="powershell"))

    def test_distro_filter_ubuntu_only(self):
        e = self._make_entry(platform="linux", distros=["ubuntu"])
        assert _entry_matches_profile(e, _linux_profile(distro="ubuntu"))
        assert not _entry_matches_profile(e, _linux_profile(distro="arch"))

    def test_requires_filter_missing_tool(self):
        e = self._make_entry(platform="windows", requires=["winget"])
        # pip only — winget not available
        p = _win_profile(package_managers=["pip"], capabilities=["python", "pip"])
        assert not _entry_matches_profile(e, p)

    def test_requires_filter_tool_in_capabilities(self):
        e = self._make_entry(platform="windows", requires=["pip"])
        p = _win_profile(capabilities=["python", "pip", "git"])
        assert _entry_matches_profile(e, p)

    def test_cross_platform_list(self):
        e = self._make_entry(platform=["windows", "linux", "darwin"])
        assert _entry_matches_profile(e, _win_profile())
        assert _entry_matches_profile(e, _linux_profile())
        assert _entry_matches_profile(e, _macos_profile())

    def test_forbidden_tags_windows(self):
        p = _win_profile()
        forbidden = forbidden_platform_tags(p)
        assert "apt" in forbidden
        assert "brew" in forbidden
        assert "linux" in forbidden
        assert "pip" not in forbidden  # pip IS available on this profile

    def test_load_for_profile_returns_windows_only(self):
        p = _win_profile(package_managers=["pip", "winget"], capabilities=["python", "pip", "git"])
        entries = load_for_profile(p)
        for e in entries:
            # Cross-platform entries (windows+linux+darwin) are allowed;
            # Linux-only entries must not appear.
            if e.platform:
                assert "windows" in e.platform, (
                    f"Entry {e.id} has platform {e.platform} — "
                    "must include 'windows' to be loaded for a windows profile"
                )
            # No entry may have powershell in forbidden_shells
            assert "powershell" not in e.forbidden_shells


# ── CommandRegistry tests ─────────────────────────────────────────────────────


class TestCommandRegistry:
    def test_build_windows(self):
        p = _win_profile(package_managers=["pip", "winget"], capabilities=["python", "pip", "git"])
        reg = CommandRegistry.build(p)
        assert len(reg.all_entries()) > 0

    def test_resolve_install_global(self):
        p = _win_profile(package_managers=["pip"], capabilities=["python", "pip", "git"])
        reg = CommandRegistry.build(p)
        entries = reg.resolve("install_global")
        assert len(entries) > 0
        for e in entries:
            assert "install_global" in e.intent

    def test_no_linux_only_entries_on_windows(self):
        p = _win_profile()
        reg = CommandRegistry.build(p)
        for e in reg.all_entries():
            # Cross-platform entries include linux in their list — that's fine.
            # Purely linux-only entries must not appear in a windows registry.
            if e.platform and "windows" not in e.platform:
                pytest.fail(
                    f"Entry {e.id} with platform {e.platform} should not be in windows registry"
                )

    def test_intents_from_text(self):
        intents = intents_from_text("install yt-dlp globally so it can be called from anywhere")
        assert "install_global" in intents

    def test_intents_from_text_path(self):
        intents = intents_from_text("add Scripts directory to PATH permanently")
        assert "add_to_path" in intents
        assert "path_permanent" in intents

    def test_intents_from_text_empty(self):
        assert intents_from_text("") == []

    def test_preferred_package_manager_pip_only(self):
        p = _win_profile(package_managers=["pip"], capabilities=["python", "pip"])
        reg = CommandRegistry.build(p)
        pm = reg.preferred_package_manager()
        assert pm in ("pip", "")


# ── CommandRanker tests ───────────────────────────────────────────────────────


class TestKnowledgeValidator:
    def _val(self, profile=None) -> KnowledgeValidator:
        return KnowledgeValidator(profile or _win_profile())

    def test_pip_ok_on_windows(self):
        v = self._val()
        r = v.validate("pip install yt-dlp --user")
        assert r.ok

    def test_apt_blocked_on_windows(self):
        v = self._val()
        r = v.validate("apt-get install yt-dlp")
        assert not r.ok
        assert r.severity == "HARD"
        assert "apt" in r.reason.lower() or "apt-get" in r.reason.lower()

    def test_sudo_blocked_on_windows(self):
        v = self._val()
        r = v.validate("sudo pip install yt-dlp")
        assert not r.ok
        assert "sudo" in r.reason.lower()

    def test_brew_blocked_on_windows(self):
        v = self._val()
        r = v.validate("brew install yt-dlp")
        assert not r.ok

    def test_powershell_ok_on_windows(self):
        v = self._val()
        r = v.validate('[Environment]::SetEnvironmentVariable("PATH","C:\\foo","User")')
        assert r.ok

    def test_export_blocked_on_powershell(self):
        v = self._val(profile=_win_profile(shell="powershell"))
        r = v.validate("export PATH=$PATH:/usr/local/bin")
        assert not r.ok

    def test_unix_path_blocked_on_windows(self):
        v = self._val()
        r = v.validate("cat /usr/bin/python3")
        assert not r.ok

    def test_windows_path_blocked_on_linux(self):
        v = self._val(profile=_linux_profile())
        r = v.validate("C:\\Program Files\\Python\\python.exe script.py")
        assert not r.ok

    def test_apt_ok_on_linux(self):
        v = self._val(profile=_linux_profile())
        r = v.validate("sudo apt-get install yt-dlp")
        assert r.ok

    def test_brew_blocked_on_linux(self):
        v = self._val(profile=_linux_profile())
        r = v.validate("brew install yt-dlp")
        assert not r.ok

    def test_filter_plan_blocks_bad_step(self):
        v = self._val()
        plan = [
            {"objective": "install pip", "launcher": "pip install yt-dlp"},
            {"objective": "install apt", "launcher": "sudo apt-get install yt-dlp"},
        ]
        filtered, rejections = v.filter_plan(plan)
        assert len(filtered) == 2
        assert len(rejections) == 1
        assert filtered[1].get("_ocke_blocked")

    def test_convenience_function(self):
        r = validate_command("pip install yt-dlp", _win_profile())
        assert r.ok


# ── OCKE integration tests ────────────────────────────────────────────────────


class TestOCKE:
    def _ocke(self) -> OCKE:
        return OCKE(
            profile=_win_profile(
                package_managers=["pip", "winget"],
                capabilities=["python", "pip", "git"],
            )
        )

    def test_build_and_summary(self):
        ocke = self._ocke()
        s = ocke.summary()
        assert "windows" in s.lower()

    def test_prompt_block_contains_os(self):
        ocke = self._ocke()
        block = ocke.prompt_block()
        assert "windows" in block.lower()
        assert "FORBIDDEN_COMMANDS" in block

    def test_validate_command_blocks_apt(self):
        ocke = self._ocke()
        r = ocke.validate_command("sudo apt install yt-dlp")
        assert not r.ok

    def test_filter_plan_integration(self):
        ocke = self._ocke()
        plan = [
            {"objective": "good step", "launcher": "pip install yt-dlp --user"},
            {"objective": "bad step", "launcher": "apt-get install yt-dlp"},
        ]
        filtered, rejections = ocke.filter_plan(plan)
        assert len(rejections) == 1
        assert "_ocke_blocked" in filtered[1]

    def test_context_for_prompt(self):
        ocke = self._ocke()
        ctx = ocke._context_for_prompt()
        # OCKEContext carries profile_summary, not os_name directly
        assert "windows" in ctx.profile_summary.lower()
        assert "pip" in ctx.package_managers
        # Prompt block should be non-empty and contain forbidden tag info
        block = ctx.to_prompt_block()
        assert "FORBIDDEN_COMMANDS" in block
        assert "ACTIVE_PACKAGE_MANAGERS" in block
