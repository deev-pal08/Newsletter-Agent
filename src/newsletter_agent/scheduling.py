"""Schedule installation for automated digest runs."""

from __future__ import annotations

import logging
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
    <string>com.newsletter-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{newsletter_bin}</string>
        <string>send</string>
        <string>--config</string>
        <string>{config_path}</string>
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
    """Install a daily schedule. Returns the path to the installed schedule."""
    hour, minute = _parse_time(time_str)

    if sys.platform == "darwin":
        return _install_launchd(hour, minute, config_path)
    return _install_cron(hour, minute, config_path)


def uninstall_schedule() -> bool:
    """Remove the installed schedule. Returns True if something was removed."""
    if sys.platform == "darwin":
        return _uninstall_launchd()
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
    # Fall back to uv run
    uv = shutil.which("uv")
    if uv:
        return f"{uv} run newsletter"
    raise FileNotFoundError(
        "Cannot find 'newsletter' or 'uv' binary. "
        "Make sure the package is installed."
    )


def _install_launchd(hour: int, minute: int, config_path: str) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir = str(Path.cwd())
    log_dir = str(Path(working_dir) / "data" / "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    import os
    path_env = os.environ.get("PATH", "/usr/bin:/usr/local/bin")
    home = Path.home()
    # Add common bin paths
    for extra in [f"{home}/.local/bin", f"{home}/.cargo/bin", "/opt/homebrew/bin"]:
        if extra not in path_env:
            path_env = f"{extra}:{path_env}"

    config_abs = str(Path(config_path).resolve())

    plist_content = PLIST_TEMPLATE.format(
        newsletter_bin=newsletter_bin,
        config_path=config_abs,
        hour=hour,
        minute=minute,
        log_dir=log_dir,
        working_dir=working_dir,
        path_env=path_env,
    )

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / PLIST_NAME

    # Unload if already loaded
    if plist_path.exists():
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )

    plist_path.write_text(plist_content)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)

    return str(plist_path)


def _uninstall_launchd() -> bool:
    plist_path = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
    if not plist_path.exists():
        return False
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    plist_path.unlink()
    return True


def _install_cron(hour: int, minute: int, config_path: str) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir = Path.cwd()
    config_abs = str(Path(config_path).resolve())
    log_path = working_dir / "data" / "logs" / "newsletter-cron.log"
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    cron_line = (
        f"{minute} {hour} * * * "
        f"cd {working_dir} && {newsletter_bin} send -c {config_abs} "
        f">> {log_path} 2>&1"
    )

    # Read existing crontab
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True,
    )
    existing = result.stdout if result.returncode == 0 else ""

    # Remove old newsletter entries
    lines = [
        line for line in existing.splitlines()
        if "newsletter" not in line
    ]
    lines.append(cron_line)

    new_crontab = "\n".join(lines) + "\n"
    subprocess.run(
        ["crontab", "-"], input=new_crontab, text=True, check=True,
    )

    return f"Cron entry: {cron_line}"


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
