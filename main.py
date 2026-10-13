"""Legion Go Charge Limit - Decky Loader backend.

Toggles the Legion Go's firmware 80% charge limit through the ACPI WMI method
\\_SB.GZFD.WMAE (feature id 0x03010001) using the out-of-tree `acpi_call`
kernel module (/proc/acpi/call). The method and feature id were identified from
Handheld Daemon's src/adjustor/core/lenovo.py (hhd-dev/hhd).
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from collections import deque

try:
    import decky
except ImportError:  # older Decky Loader releases
    import decky_plugin as decky

ACPI_CALL = os.environ.get("CLC_ACPI_CALL", "/proc/acpi/call")
METHOD = r"\_SB.GZFD.WMAE"
FEATURE_ID = 0x03010001
REAPPLY_EVERY = 300  # seconds; re-assert the limit periodically while enabled
RESUME_GAP = 15      # seconds of suspend (wall clock vs monotonic) = "resumed"


# ---------------------------------------------------------------- helpers ---

def _buf(data: bytes) -> str:
    return "b" + data.hex()


def _get_cmd() -> str:
    return f"{METHOD} 0x0 0x11 {_buf(FEATURE_ID.to_bytes(4, 'little'))}"


def _set_cmd(enable: bool) -> str:
    payload = FEATURE_ID.to_bytes(4, "little") + int(bool(enable)).to_bytes(4, "little")
    return f"{METHOD} 0x0 0x12 {_buf(payload)}"


def _parse_enabled(out: str):
    """Best-effort parse of acpi_call output. Returns True/False/None."""
    nums = re.findall(r"0x[0-9a-fA-F]+", out or "")
    if not nums:
        return None
    return int(nums[0], 16) != 0


def _clean_env():
    """Decky is a PyInstaller bundle; its LD_LIBRARY_PATH breaks system tools
    like pacman/modprobe. Restore the original one."""
    env = dict(os.environ)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    env.pop("LD_LIBRARY_PATH", None)
    if orig is not None:
        env["LD_LIBRARY_PATH"] = orig
    env["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin"
    env["LC_ALL"] = "C"
    return env


def _ensure_module():
    if os.path.exists(ACPI_CALL):
        return
    try:
        subprocess.run(["modprobe", "acpi_call"], check=False, capture_output=True,
                       timeout=10, env=_clean_env())
    except Exception as e:  # noqa: BLE001
        decky.logger.warning(f"modprobe acpi_call failed: {e}")
    if not os.path.exists(ACPI_CALL):
        raise RuntimeError(
            "acpi_call kernel module not available (/proc/acpi/call missing)"
        )


def _acpi(cmd: str) -> str:
    """Blocking: run one ACPI call and return its raw output."""
    _ensure_module()
    with open(ACPI_CALL, "w") as f:
        f.write(cmd)
    with open(ACPI_CALL) as f:
        out = f.read().strip("\x00\n\r ")
    if not out or out.startswith("Error"):
        raise RuntimeError(f"ACPI call failed: {out or 'no output'}")
    return out


def _settings_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")


def _load_enabled():
    try:
        with open(_settings_path()) as f:
            v = json.load(f).get("enabled")
            return None if v is None else bool(v)
    except Exception:  # noqa: BLE001
        return None


def _save_enabled(enabled: bool):
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(_settings_path(), "w") as f:
        json.dump({"enabled": bool(enabled)}, f)


# ------------------------------------------------------------------ state ---
# Decky does not reliably call methods on a Plugin instance (self can be the
# class or something else entirely), so all state lives at module level and
# the Plugin methods never touch `self`.

class _S:
    enabled = None      # None = user never configured it; don't touch hardware
    last_error = None
    task = None
    lock = None


def _lock():
    if _S.lock is None:
        _S.lock = asyncio.Lock()
    return _S.lock


async def _run(cmd: str) -> str:
    async with _lock():
        return await asyncio.get_running_loop().run_in_executor(None, _acpi, cmd)


async def _apply(enabled: bool):
    decky.logger.info(f"Setting 80% charge limit -> {enabled}")
    await _run(_set_cmd(enabled))


async def _status(error=None):
    hw = None
    err = error
    if not _I.running:
        try:
            hw = _parse_enabled(await _run(_get_cmd()))
        except Exception as e:  # noqa: BLE001
            err = err or str(e)
    return {
        "enabled": bool(_S.enabled),
        "configured": _S.enabled is not None,
        "hardware": hw,
        "error": err,
        "module_missing": not os.path.exists(ACPI_CALL),
        "readonly": await asyncio.get_running_loop().run_in_executor(None, _readonly_state),
        "install": {
            "running": _I.running,
            "ok": _I.ok,
            "step": _I.step,
            "log": list(_I.log)[-12:],
        },
    }


def _extract_enabled(args, kwargs, key="enabled"):
    """Find the requested state however Decky passed it."""
    if key in kwargs:
        return bool(kwargs[key])
    for a in args:
        if isinstance(a, dict) and key in a:
            return bool(a[key])
    for a in args:
        if isinstance(a, bool):
            return a
    raise ValueError(f"no '{key}' value in call args={args!r} kwargs={kwargs!r}")


def _readonly_state():
    """True = system partition locked (read-only), False = unlocked, None = unknown."""
    try:
        r = subprocess.run(["steamos-readonly", "status"], capture_output=True,
                           text=True, timeout=10, env=_clean_env())
        out = (r.stdout + r.stderr).lower()
        if "disabled" in out:
            return False
        if "enabled" in out:
            return True
    except Exception as e:  # noqa: BLE001
        decky.logger.warning(f"steamos-readonly status failed: {e}")
    return None


def _set_readonly(locked: bool):
    r = subprocess.run(["steamos-readonly", "enable" if locked else "disable"],
                       capture_output=True, text=True, timeout=60, env=_clean_env())
    if r.returncode != 0:
        raise RuntimeError(f"steamos-readonly failed: {(r.stdout + r.stderr).strip()[:200]}")



# ------------------------------------------------------------- installer ---

class _I:
    running = False
    ok = None
    step = ""
    log = deque(maxlen=300)
    task = None


def _log(line: str):
    _I.log.append(line[:300])


async def _sh(*cmd, timeout=1200, check=True):
    _log("$ " + " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=_clean_env(), limit=2 ** 20,
    )

    async def reader():
        async for raw in proc.stdout:
            text = raw.decode(errors="replace").rstrip()
            if text:
                _log(text)

    try:
        await asyncio.wait_for(asyncio.gather(reader(), proc.wait()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{cmd[0]} timed out")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited with code {proc.returncode}")
    return proc.returncode


async def _find_headers_pkg(rel: str) -> str:
    m = re.search(r"neptune-(\d+)", rel)
    if not m:
        raise RuntimeError(f"Kernel '{rel}' doesn't look like a SteamOS neptune kernel")
    num = m.group(1)
    guess = f"linux-neptune-{num}-headers"
    if await _sh("pacman", "-Si", guess, check=False) == 0:
        return guess
    out = subprocess.run(["pacman", "-Ssq", "headers"], capture_output=True, text=True,
                         env=_clean_env()).stdout.split()
    cands = [p for p in out if "neptune" in p and num in p]
    if len(cands) == 1:
        return cands[0]
    raise RuntimeError(f"Could not determine kernel headers package for {rel} (candidates: {cands})")


async def _install():
    _I.running, _I.ok = True, None
    unlocked = False
    try:
        if os.geteuid() != 0:
            raise RuntimeError("Plugin is not running as root")
        rel = os.uname().release
        free = shutil.disk_usage("/").free
        _log(f"kernel {rel}; {free // 2**20} MiB free on /")
        if free < 300 * 2 ** 20:
            raise RuntimeError("Less than 300 MiB free on the system partition")

        _I.step = "Unlocking system partition"
        await _sh("steamos-readonly", "disable", check=False)
        unlocked = True

        _I.step = "Preparing package keys"
        await _sh("pacman-key", "--init")
        await _sh("pacman-key", "--populate", "archlinux", "holo", check=False)

        _I.step = "Syncing package databases"
        await _sh("pacman", "-Sy", "--noconfirm")

        _I.step = "Finding kernel headers"
        headers = await _find_headers_pkg(rel)
        _log(f"headers package: {headers}")

        _I.step = "Installing build tools + acpi_call (this takes a while)"
        await _sh("pacman", "-S", "--needed", "--noconfirm", "dkms", "gcc", "make",
                  headers, "acpi_call-dkms")

        if not os.path.exists(f"/usr/lib/modules/{rel}/build"):
            raise RuntimeError(
                f"Installed headers don't match the running kernel ({rel}). "
                "Update SteamOS and reboot, then try again.")

        _I.step = "Building module"
        await _sh("dkms", "autoinstall", "-k", rel, check=False)
        await _sh("depmod", "-a", rel, check=False)
        await _sh("modprobe", "acpi_call", check=False)

        if not os.path.exists(ACPI_CALL):
            raise RuntimeError("acpi_call still not loaded after install; see log")
        _I.ok = True
        _I.step = "Done"
        _log("acpi_call installed and loaded.")
        if _S.enabled is not None:
            await _apply(_S.enabled)
    except Exception as e:  # noqa: BLE001
        _I.ok = False
        _I.step = f"Failed: {e}"
        _log(f"ERROR: {e}")
        decky.logger.error(f"install failed: {e}")
    finally:
        if unlocked:
            await _sh("steamos-readonly", "enable", check=False)
        _I.running = False
        try:
            os.makedirs(decky.DECKY_PLUGIN_LOG_DIR, exist_ok=True)
            with open(os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "install.log"), "w") as f:
                f.write("\n".join(_I.log))
        except Exception:  # noqa: BLE001
            pass


async def _watch():
    last_wall, last_mono = time.time(), time.monotonic()
    last_apply = 0.0
    first = True
    while True:
        try:
            if _S.enabled is not None:
                now_wall, now_mono = time.time(), time.monotonic()
                resumed = (now_wall - last_wall) - (now_mono - last_mono) > RESUME_GAP
                periodic = _S.enabled and (now_mono - last_apply) > REAPPLY_EVERY
                if first or resumed or periodic:
                    if resumed:
                        await asyncio.sleep(3)  # let firmware/ACPI settle
                    await _apply(_S.enabled)
                    _S.last_error = None
                    last_apply = time.monotonic()
                    first = False
        except Exception as e:  # noqa: BLE001
            _S.last_error = str(e)
            decky.logger.error(f"watcher: {e}")
            last_apply = time.monotonic()  # don't hammer on failure
            first = False
        last_wall, last_mono = time.time(), time.monotonic()
        await asyncio.sleep(5)


# ----------------------------------------------------------------- plugin ---

class Plugin:
    # exposed to the frontend

    async def get_status(self, *args, **kwargs):
        return await _status(_S.last_error)

    async def set_limit(self, *args, **kwargs):
        try:
            # `self` itself is included in the search in case Decky shifted args
            enabled = _extract_enabled((self,) + args, kwargs)
            await _apply(enabled)
            _S.enabled = enabled
            _save_enabled(enabled)
            _S.last_error = None
            return await _status()
        except Exception as e:  # noqa: BLE001
            decky.logger.error(f"set_limit failed: {e}")
            _S.last_error = str(e)
            return await _status(str(e))

    async def set_unlocked(self, *args, **kwargs):
        try:
            if _I.running:
                raise RuntimeError("Wait for the install to finish first")
            unlocked = _extract_enabled((self,) + args, kwargs, "unlocked")
            await asyncio.get_running_loop().run_in_executor(None, _set_readonly, not unlocked)
            return await _status(_S.last_error)
        except Exception as e:  # noqa: BLE001
            decky.logger.error(f"set_unlocked failed: {e}")
            return await _status(str(e))

    async def start_install(self, *args, **kwargs):
        if not _I.running and not os.path.exists(ACPI_CALL):
            _I.log.clear()
            _I.task = asyncio.create_task(_install())
            await asyncio.sleep(0)
        return await _status(_S.last_error)

    # lifecycle

    async def _main(self, *args, **kwargs):
        _S.enabled = _load_enabled()
        decky.logger.info(f"Legion Go Charge Limit started (saved state: {_S.enabled})")
        _S.task = asyncio.create_task(_watch())

    async def _unload(self, *args, **kwargs):
        if _S.task:
            _S.task.cancel()
        decky.logger.info("Legion Go Charge Limit unloaded")
