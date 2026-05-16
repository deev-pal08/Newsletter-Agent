"""Schedule installation for automated digest runs."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PLIST_NAME = "com.newsletter-agent.plist"

PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_dir}/newsletter-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/newsletter-stderr.log</string>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>
</dict>
</plist>
"""


def install_schedule(
    time_str: str = "08:00",
    config_path: str = "config.yaml",
) -> str:
    """Install a daily schedule. Returns description of what was installed."""
    hour, minute = _parse_time(time_str)

    if sys.platform == "darwin":
        return _install_launchd(hour, minute, config_path)
    if sys.platform == "win32":
        return _install_schtasks(hour, minute, config_path)
    return _install_cron(hour, minute, config_path)


def uninstall_schedule() -> bool:
    """Remove all installed schedules. Returns True if something was removed."""
    if sys.platform == "darwin":
        return _uninstall_launchd()
    if sys.platform == "win32":
        return _uninstall_schtasks()
    return _uninstall_cron()


def _parse_time(time_str: str) -> tuple[int, int]:
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str} (expected HH:MM)")
    return int(parts[0]), int(parts[1])


def _find_newsletter_bin() -> str:
    which = shutil.which("newsletter")
    if which:
        return which
    uv = shutil.which("uv")
    if uv:
        return f"{uv} run newsletter"
    raise FileNotFoundError(
        "Cannot find 'newsletter' or 'uv' binary. "
        "Make sure the package is installed."
    )


def _get_env() -> tuple[str, str, str]:
    """Return (working_dir, log_dir, path_env)."""
    working_dir = str(Path.cwd())
    log_dir = str(Path(working_dir) / "data" / "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    path_env = os.environ.get("PATH", "/usr/bin:/usr/local/bin")
    home = Path.home()
    for extra in [f"{home}/.local/bin", f"{home}/.cargo/bin", "/opt/homebrew/bin"]:
        if extra not in path_env:
            path_env = f"{extra}:{path_env}"

    return working_dir, log_dir, path_env


def _format_plist_args(args: list[str]) -> str:
    return "\n".join(f"        <string>{a}</string>" for a in args)


def _write_and_load_plist(name: str, content: str) -> str:
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / name

    if plist_path.exists():
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )

    plist_path.write_text(content)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    return str(plist_path)


def _unload_and_remove_plist(name: str) -> bool:
    plist_path = Path.home() / "Library" / "LaunchAgents" / name
    if not plist_path.exists():
        return False
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    plist_path.unlink()
    return True


# --- macOS (launchd) ---

def _install_launchd(hour: int, minute: int, config_path: str) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, path_env = _get_env()
    config_abs = str(Path(config_path).resolve())

    args = [newsletter_bin, "send", "--config", config_abs]
    content = PLIST_TEMPLATE.format(
        label="com.newsletter-agent",
        program_args=_format_plist_args(args),
        hour=hour,
        minute=minute,
        log_dir=log_dir,
        working_dir=working_dir,
        path_env=path_env,
    )

    # Clean up any legacy batch plists
    for legacy in ["com.newsletter-agent.submit.plist",
                    "com.newsletter-agent.collect.plist"]:
        _unload_and_remove_plist(legacy)

    path = _write_and_load_plist(PLIST_NAME, content)
    return path


# --- Linux (cron) ---

def _install_cron(hour: int, minute: int, config_path: str) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, _ = _get_env()
    config_abs = str(Path(config_path).resolve())
    log_path = f"{log_dir}/newsletter-cron.log"

    cron_line = (
        f"{minute} {hour} * * * "
        f"cd {working_dir} && {newsletter_bin} send -c {config_abs} "
        f">> {log_path} 2>&1"
    )

    _write_cron_lines([cron_line])
    return f"Cron entry: {cron_line}"


def _write_cron_lines(new_lines: list[str]) -> None:
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True,
    )
    existing = result.stdout if result.returncode == 0 else ""

    lines = [
        line for line in existing.splitlines()
        if "newsletter" not in line
    ]
    lines.extend(new_lines)

    new_crontab = "\n".join(lines) + "\n"
    subprocess.run(
        ["crontab", "-"], input=new_crontab, text=True, check=True,
    )


def _uninstall_launchd() -> bool:
    removed = False
    for name in [PLIST_NAME, "com.newsletter-agent.submit.plist",
                 "com.newsletter-agent.collect.plist"]:
        if _unload_and_remove_plist(name):
            removed = True
    return removed


def _uninstall_cron() -> bool:
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    lines = [
        line for line in result.stdout.splitlines()
        if "newsletter" not in line
    ]
    new_crontab = "\n".join(lines) + "\n" if lines else ""
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)
    return True


# --- Windows (Task Scheduler) ---

SCHTASK_NAME = "NewsletterAgent"


def _build_task_command(newsletter_bin: str, config_abs: str) -> str:
    return f"{newsletter_bin} send --config {config_abs}"


def _create_schtask(task_name: str, time_str: str, command: str,
                    working_dir: str, log_path: str) -> None:
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True,
    )
    subprocess.run(
        [
            "schtasks", "/Create",
            "/TN", task_name,
            "/TR", f'cmd /c "cd /d {working_dir} && {command} >> {log_path} 2>&1"',
            "/SC", "DAILY",
            "/ST", time_str,
            "/F",
        ],
        check=True,
    )


def _delete_schtask(task_name: str) -> bool:
    result = subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True,
    )
    return result.returncode == 0


def _install_schtasks(hour: int, minute: int, config_path: str) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, _ = _get_env()
    config_abs = str(Path(config_path).resolve())
    log_path = f"{log_dir}\\newsletter-send.log"
    time_str = f"{hour:02d}:{minute:02d}"

    command = _build_task_command(newsletter_bin, config_abs)

    # Clean up any legacy batch tasks
    for legacy in ["NewsletterAgent-Submit", "NewsletterAgent-Collect"]:
        _delete_schtask(legacy)

    _create_schtask(SCHTASK_NAME, time_str, command, working_dir, log_path)
    return f"Task: {SCHTASK_NAME} at {time_str}"


def _uninstall_schtasks() -> bool:
    removed = False
    for name in [SCHTASK_NAME, "NewsletterAgent-Submit",
                 "NewsletterAgent-Collect"]:
        if _delete_schtask(name):
            removed = True
    return removed
