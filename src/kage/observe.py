from __future__ import annotations
import json, os, time, threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional
import logging
from kage import runtime

try:
    from AppKit import NSWorkspace as _NSWorkspace
except ImportError:
    _NSWorkspace = None

logger = logging.getLogger(__name__)

_AFK_THRESHOLD = 180.0
_PULSE_TIME    = 30.0
_POLL_INTERVAL = 10.0
_MIN_GAP       = 0.5
_last_event: Optional[dict] = None

class CaptureTrigger(str, Enum):
    APP_SWITCH    = "app_switch"
    WINDOW_FOCUS  = "window_focus"
    TYPING_PAUSE  = "typing_pause"
    SCROLL_STOP   = "scroll_stop"
    VISUAL_CHANGE = "visual_change"
    IDLE          = "idle"


@dataclass
class ObserveEvent:
    ts: float
    app: str
    bundle: str
    window: str
    ax_text: str
    trigger: str
    duration: float
    project: str
    identity: str

    def to_dict(self) -> dict:
        return asdict(self)


def _pii_strip(text: str) -> str:
    from kage.pii import _gate_text
    return _gate_text(text)


def _heartbeat_merge(last: dict, new: dict, pulsetime: float) -> bool:
    if last.get("app") == new.get("app") and last.get("window") == new.get("window"):
        if new["ts"] <= last["ts"] + last["duration"] + pulsetime:
            new_dur = (new["ts"] - last["ts"]) + new["duration"]
            last["duration"] = max(last["duration"], new_dur)
            return True
    return False


def _seconds_since_input() -> float:
    try:
        from Quartz.CoreGraphics import (
            CGEventSourceSecondsSinceLastEventType,
            kCGEventSourceStateHIDSystemState, kCGAnyInputEventType,
        )
        return CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateHIDSystemState, kCGAnyInputEventType)
    except Exception:
        return float("inf")


def _enable_electron_ax(pid: int) -> None:
    try:
        from ApplicationServices import AXUIElementCreateApplication, AXUIElementSetAttributeValue
        AXUIElementSetAttributeValue(AXUIElementCreateApplication(pid), "AXEnhancedUserInterface", True)
        time.sleep(0.2)
    except Exception:
        pass


def _read_ax_focused() -> tuple[str, str]:
    try:
        from ApplicationServices import (
            AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue,
            kAXFocusedUIElementAttribute, kAXValueAttribute, kAXTitleAttribute,
            kAXRoleAttribute, kAXRoleDescriptionAttribute,
        )
        ax_system = AXUIElementCreateSystemWide()
        err, focused = AXUIElementCopyAttributeValue(ax_system, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return ("", "")
        _, role = AXUIElementCopyAttributeValue(focused, kAXRoleAttribute, None)
        _, role_desc = AXUIElementCopyAttributeValue(focused, kAXRoleDescriptionAttribute, None)
        if (role or "") == "AXSecureTextField" or "secure" in (role_desc or "").lower():
            return ("", "")
        _, ax_text = AXUIElementCopyAttributeValue(focused, kAXValueAttribute, None)
        _, window_title = AXUIElementCopyAttributeValue(focused, kAXTitleAttribute, None)
        return (ax_text or "", window_title or "")
    except Exception:
        return ("", "")


def _get_browser_url(app_name: str) -> Optional[str]:
    # ponytail: stub — ScriptingBridge bundle IDs + tab URL path need live validation
    return None


def _write_event(event: ObserveEvent) -> None:
    global _last_event
    new_dict = event.to_dict()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        kage_dir = Path.home() / ".kage" / "observe"
        kage_dir.mkdir(parents=True, exist_ok=True)
        file_path = kage_dir / f"{today}.jsonl"
        if file_path.exists():
            lines = file_path.read_text().splitlines(keepends=True)
            if lines:
                try:
                    last_line = json.loads(lines[-1])
                    if _heartbeat_merge(last_line, new_dict, _PULSE_TIME):
                        lines[-1] = json.dumps(last_line) + "\n"
                        file_path.write_text("".join(lines))
                        _last_event = last_line
                        return
                except Exception:
                    pass
        with open(file_path, "a") as f:
            f.write(json.dumps(new_dict) + "\n")
        _last_event = new_dict
    except Exception as e:
        logger.error(f"observe _write_event: {e}")


def _observe_loop() -> None:
    while True:
        time.sleep(_POLL_INTERVAL)
        if _seconds_since_input() > _AFK_THRESHOLD:
            continue
        ax_text, window = _read_ax_focused()
        project, identity = "", "personal"
        try:
            conn = runtime.store.connect()
            row = conn.execute(
                "SELECT project, identity FROM sessions ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                project, identity = row[0] or "", row[1] or "personal"
            conn.close()
        except Exception:
            pass
        try:
            fi = _NSWorkspace.sharedWorkspace().frontmostApplication()
            app_name = fi.localizedName() or ""
            bundle   = fi.bundleIdentifier() or ""
        except Exception:
            app_name, bundle = "", ""
        ev = ObserveEvent(
            ts=time.time(), app=app_name, bundle=bundle,
            window=_pii_strip(window), ax_text=_pii_strip(ax_text),
            trigger=CaptureTrigger.IDLE.value, duration=0.0,
            project=project, identity=identity,
        )
        _write_event(ev)


def read_observe_log(hours: float = 1.0) -> list[dict]:
    try:
        cutoff = time.time() - hours * 3600
        kage_dir = Path.home() / ".kage" / "observe"
        days_back = int(hours / 24) + 1
        files = [
            kage_dir / f"{(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')}.jsonl"
            for i in range(days_back)
        ]
        result = []
        for fp in files:
            if not fp.exists():
                continue
            for line in fp.read_text().splitlines():
                try:
                    event = json.loads(line)
                    if event.get("ts", 0) >= cutoff:
                        result.append(event)
                except Exception:
                    continue
        return result
    except Exception:
        return []


def start_observer() -> None:
    try:
        from AppKit import (
            NSWorkspace, NSWorkspaceDidActivateApplicationNotification,
            NSWorkspaceApplicationKey, NSObject,
        )
        from PyObjCTools import AppHelper
        from ApplicationServices import AXIsProcessTrusted
    except ImportError as e:
        logger.error(f"kage observe: PyObjC not installed — {e}")
        return

    if not AXIsProcessTrusted():
        logger.warning("kage observe: Accessibility permission not granted. App-switch events only.")

    class _AppSwitchObserver(NSObject):
        def handle_(self, notification):
            try:
                app_info = notification.userInfo()[NSWorkspaceApplicationKey]
                name = app_info.localizedName() or ""
                bundle = app_info.bundleIdentifier() or ""
                pid = app_info.processIdentifier()
                if "electron" in bundle.lower() or name in ("Code", "Notion", "Slack", "Antigravity"):
                    _enable_electron_ax(pid)
                ax_text, window = _read_ax_focused()
                if not ax_text and not window:
                    window = name
                project, identity = "", "personal"
                try:
                    conn = runtime.store.connect()
                    row = conn.execute(
                        "SELECT project, identity FROM sessions ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                    if row:
                        project, identity = row[0] or "", row[1] or "personal"
                    conn.close()
                except Exception:
                    pass
                ev = ObserveEvent(
                    ts=time.time(), app=name, bundle=bundle,
                    window=_pii_strip(window), ax_text=_pii_strip(ax_text),
                    trigger=CaptureTrigger.APP_SWITCH.value, duration=0.0,
                    project=project, identity=identity,
                )
                _write_event(ev)
            except Exception as e:
                logger.error(f"AppSwitchObserver error: {e}")

    center = NSWorkspace.sharedWorkspace().notificationCenter()
    obs = _AppSwitchObserver.new()
    center.addObserver_selector_name_object_(
        obs, "handle:", NSWorkspaceDidActivateApplicationNotification, None
    )
    threading.Thread(target=_observe_loop, daemon=True).start()
    AppHelper.runConsoleEventLoop(installInterrupt=True)
