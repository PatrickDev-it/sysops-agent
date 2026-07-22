"""
Per-OS command dialect helpers.

Families must emit commands that are correct for the target OS's shell and tooling.
Centralising the dialect here keeps families OS-agnostic in structure while the
concrete command strings stay faithful (systemctl vs launchctl vs Get-Service,
`ss -ltnp` vs `lsof` vs `Get-NetTCPConnection`, and so on).

These are REPRESENTATIVE correct commands used to populate `expected_commands`,
`reference_solution` and read-only `probe`s in success checks. The benchmark scores
OUTCOME (post-state), so these strings are anchors for humans/validators, not the
sole accepted answer.
"""

from __future__ import annotations


def who_listens(os: str, port: int) -> str:
    return {
        "linux": f"ss -ltnp 'sport = :{port}'",
        "macos": f"lsof -nP -iTCP:{port} -sTCP:LISTEN",
        "windows": f"Get-NetTCPConnection -LocalPort {port} -State Listen | Select OwningProcess",
    }[os]


def kill_pid(os: str, what: str = "<PID>") -> str:
    return {
        "linux": f"kill -TERM {what}",
        "macos": f"kill -TERM {what}",
        "windows": f"Stop-Process -Id {what} -Force",
    }[os]


def svc_status(os: str, s: str) -> str:
    return {
        "linux": f"systemctl status {s} --no-pager",
        "macos": f"launchctl print system/{s}",
        "windows": f"Get-Service '{s}' | Format-List *",
    }[os]


def svc_start(os: str, s: str) -> str:
    return {
        "linux": f"systemctl start {s}",
        "macos": f"launchctl kickstart -k system/{s}",
        "windows": f"Start-Service '{s}'",
    }[os]


def svc_restart(os: str, s: str) -> str:
    return {
        "linux": f"systemctl restart {s}",
        "macos": f"launchctl kickstart -k system/{s}",
        "windows": f"Restart-Service '{s}'",
    }[os]


def svc_logs(os: str, s: str) -> str:
    return {
        "linux": f"journalctl -u {s} -n 120 --no-pager",
        "macos": f"log show --predicate 'process == \"{s}\"' --last 30m",
        "windows": f"Get-WinEvent -LogName System -MaxEvents 120 | Where-Object Message -match '{s}'",
    }[os]


def disk_usage(os: str) -> str:
    return {
        "linux": "df -h && df -i",
        "macos": "df -h",
        "windows": "Get-PSDrive -PSProvider FileSystem",
    }[os]


def find_open_deleted(os: str) -> str:
    return {
        "linux": "lsof +L1 | sort -k7 -n | tail",
        "macos": "lsof +L1 | sort -k7 -n | tail",
        "windows": "# handle64.exe -nobanner | Sort-Object; (Sysinternals handle)",
    }[os]


def edit_hint(os: str, path: str) -> str:
    return {
        "linux": f"$EDITOR {path}   # or: sed -i to apply the fix non-interactively",
        "macos": f"$EDITOR {path}",
        "windows": f"notepad {path}   # or Set-Content / (Get-Content) -replace",
    }[os]


def check_perm(os: str, path: str) -> str:
    return {
        "linux": f"ls -l {path} && namei -l {path}",
        "macos": f"ls -le {path}",
        "windows": f"Get-Acl '{path}' | Format-List",
    }[os]


def fix_owner(os: str, path: str, owner: str) -> str:
    return {
        "linux": f"chown {owner} {path}",
        "macos": f"chown {owner} {path}",
        "windows": f"icacls '{path}' /grant '{owner}:(RX)'",
    }[os]


def top_cpu(os: str) -> str:
    return {
        "linux": "top -b -n1 -o %CPU | head -20",
        "macos": "top -l 1 -o cpu -n 15",
        "windows": "Get-Process | Sort-Object CPU -Descending | Select -First 15",
    }[os]


def top_mem(os: str) -> str:
    return {
        "linux": "free -h && ps -eo pid,rss,comm --sort=-rss | head",
        "macos": "vm_stat && ps -eo pid,rss,comm -r | head",
        "windows": "Get-Process | Sort-Object WS -Descending | Select -First 15",
    }[os]


def dns_query(os: str, host: str = "example.internal") -> str:
    return {
        "linux": f"resolvectl query {host} || dig +short {host}",
        "macos": f"dscacheutil -q host -a name {host}; dig +short {host}",
        "windows": f"Resolve-DnsName {host}",
    }[os]


def flush_dns(os: str) -> str:
    return {
        "linux": "resolvectl flush-caches",
        "macos": "dscacheutil -flushcache; killall -HUP mDNSResponder",
        "windows": "Clear-DnsClientCache",
    }[os]


def hosts_file(os: str) -> str:
    return {
        "linux": "/etc/hosts",
        "macos": "/etc/hosts",
        "windows": r"C:\Windows\System32\drivers\etc\hosts",
    }[os]
