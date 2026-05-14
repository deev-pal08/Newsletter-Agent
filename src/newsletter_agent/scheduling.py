"""Schedule installation for automated digest runs."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PLIST_NAME_SYNC = "com.newsletter-agent.plist"
PLIST_NAME_SUBMIT = "com.newsletter-agent.submit.plist"
PLIST_NAME_COLLECT = "com.newsletter-agent.collect.plist"

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
    <string>{log_dir}/newsletter-{log_suffix}-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/newsletter-{log_suffix}-stderr.log</string>
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
    use_batch: bool = False,
    submit_time_str: str = "23:00",
) -> str:
    """Install a daily schedule. Returns description of what was installed."""
    hour, minute = _parse_time(time_str)
    submit_hour, submit_minute = _parse_time(submit_time_str)

    if sys.platform == "darwin":
        if use_batch:
            return _install_launchd_batch(
                submit_hour, submit_minute, hour, minute, config_path,
            )
        return _install_launchd_sync(hour, minute, config_path)

    if sys.platform == "win32":
        if use_batch:
            return _install_schtasks_batch(
                submit_hour, submit_minute, hour, minute, config_path,
            )
        return _install_schtasks_sync(hour, minute, config_path)

    if use_batch:
        return _install_cron_batch(
            submit_hour, submit_minute, hour, minute, config_path,
        )
    return _install_cron_sync(hour, minute, config_path)


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


# --- Sync mode (single job) ---

def _install_launchd_sync(hour: int, minute: int, config_path: str) -> str:
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
        log_suffix="send",
        working_dir=working_dir,
        path_env=path_env,
    )

    path = _write_and_load_plist(PLIST_NAME_SYNC, content)
    return path


def _install_cron_sync(hour: int, minute: int, config_path: str) -> str:
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


# --- Batch mode (two jobs: submit + collect) ---

def _install_launchd_batch(
    submit_hour: int, submit_minute: int,
    collect_hour: int, collect_minute: int,
    config_path: str,
) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, path_env = _get_env()
    config_abs = str(Path(config_path).resolve())

    # Remove old sync plist if it exists
    _unload_and_remove_plist(PLIST_NAME_SYNC)

    # Submit job (runs at night)
    submit_args = [newsletter_bin, "batch-submit", "--config", config_abs]
    submit_content = PLIST_TEMPLATE.format(
        label="com.newsletter-agent.submit",
        program_args=_format_plist_args(submit_args),
        hour=submit_hour,
        minute=submit_minute,
        log_dir=log_dir,
        log_suffix="submit",
        working_dir=working_dir,
        path_env=path_env,
    )
    submit_path = _write_and_load_plist(PLIST_NAME_SUBMIT, submit_content)

    # Collect job (runs in the morning)
    collect_args = [
        newsletter_bin, "batch-collect", "--send-email", "--config", config_abs,
    ]
    collect_content = PLIST_TEMPLATE.format(
        label="com.newsletter-agent.collect",
        program_args=_format_plist_args(collect_args),
        hour=collect_hour,
        minute=collect_minute,
        log_dir=log_dir,
        log_suffix="collect",
        working_dir=working_dir,
        path_env=path_env,
    )
    collect_path = _write_and_load_plist(PLIST_NAME_COLLECT, collect_content)

    return f"Submit: {submit_path}\nCollect: {collect_path}"


def _install_cron_batch(
    submit_hour: int, submit_minute: int,
    collect_hour: int, collect_minute: int,
    config_path: str,
) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, _ = _get_env()
    config_abs = str(Path(config_path).resolve())

    submit_log = f"{log_dir}/newsletter-submit.log"
    collect_log = f"{log_dir}/newsletter-collect.log"

    submit_line = (
        f"{submit_minute} {submit_hour} * * * "
        f"cd {working_dir} && {newsletter_bin} batch-submit -c {config_abs} "
        f">> {submit_log} 2>&1"
    )
    collect_line = (
        f"{collect_minute} {collect_hour} * * * "
        f"cd {working_dir} && {newsletter_bin} batch-collect --send-email -c {config_abs} "
        f">> {collect_log} 2>&1"
    )

    _write_cron_lines([submit_line, collect_line])
    return f"Submit: {submit_line}\nCollect: {collect_line}"


# --- Cron helpers ---

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
    for name in [PLIST_NAME_SYNC, PLIST_NAME_SUBMIT, PLIST_NAME_COLLECT]:
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


# --- Windows Task Scheduler ---

SCHTASK_SYNC = "NewsletterAgent"
SCHTASK_SUBMIT = "NewsletterAgent-Submit"
SCHTASK_COLLECT = "NewsletterAgent-Collect"


def _build_task_command(newsletter_bin: str, subcommand: str, config_abs: str,
                        extra_args: list[str] | None = None) -> str:
    parts = [newsletter_bin, subcommand, "--config", config_abs]
    if extra_args:
        parts.extend(extra_args)
    return " ".join(parts)


def _create_schtask(task_name: str, time_str: str, command: str,
                    working_dir: str, log_path: str) -> None:
    # Delete existing task if present
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


def _install_schtasks_sync(hour: int, minute: int, config_path: str) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, _ = _get_env()
    config_abs = str(Path(config_path).resolve())
    log_path = f"{log_dir}\\newsletter-send.log"
    time_str = f"{hour:02d}:{minute:02d}"

    command = _build_task_command(newsletter_bin, "send", config_abs)

    # Remove batch tasks if they exist
    _delete_schtask(SCHTASK_SUBMIT)
    _delete_schtask(SCHTASK_COLLECT)

    _create_schtask(SCHTASK_SYNC, time_str, command, working_dir, log_path)
    return f"Task: {SCHTASK_SYNC} at {time_str}"


def _install_schtasks_batch(
    submit_hour: int, submit_minute: int,
    collect_hour: int, collect_minute: int,
    config_path: str,
) -> str:
    newsletter_bin = _find_newsletter_bin()
    working_dir, log_dir, _ = _get_env()
    config_abs = str(Path(config_path).resolve())

    # Remove sync task if it exists
    _delete_schtask(SCHTASK_SYNC)

    submit_time = f"{submit_hour:02d}:{submit_minute:02d}"
    submit_cmd = _build_task_command(newsletter_bin, "batch-submit", config_abs)
    submit_log = f"{log_dir}\\newsletter-submit.log"
    _create_schtask(SCHTASK_SUBMIT, submit_time, submit_cmd, working_dir, submit_log)

    collect_time = f"{collect_hour:02d}:{collect_minute:02d}"
    collect_cmd = _build_task_command(
        newsletter_bin, "batch-collect", config_abs, ["--send-email"],
    )
    collect_log = f"{log_dir}\\newsletter-collect.log"
    _create_schtask(SCHTASK_COLLECT, collect_time, collect_cmd, working_dir, collect_log)

    return (
        f"Submit: {SCHTASK_SUBMIT} at {submit_time}\n"
        f"Collect: {SCHTASK_COLLECT} at {collect_time}"
    )


def _uninstall_schtasks() -> bool:
    removed = False
    for name in [SCHTASK_SYNC, SCHTASK_SUBMIT, SCHTASK_COLLECT]:
        if _delete_schtask(name):
            removed = True
    return removed
