#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VIRTUALDJ LYRICS AI FIX - V4.1

Clean cross-platform local web app for fixing VirtualDJ synced lyrics.

Key design choices:
- No automatic deep disk scan at startup.
- No automatic browser launch.
- No large Terminal paste.
- The database path is selected in the web interface.
- macOS default/preferred path:
    /Volumes/SSD-D/VirtualDJ/extra.db
- New official internal locations are also suggested:
    macOS:   ~/Library/Application Support/VirtualDJ/extra.db
    Windows: %LOCALAPPDATA%/VirtualDJ/extra.db
- Smart alignment keeps all new words while cloning existing VirtualDJ timestamp prefixes.
- No timestamp format is generated or reformatted.
- Internal non-timestamp separator lines are preserved.

Requirements:
    pip install flask

Run:
    python3 VIRTUALDJ_LYRICS_AI_FIX_v4_1.py

Open manually:
    http://127.0.0.1:5055
"""

import os
import platform
import re
import shutil
import sqlite3
import subprocess
import time
import threading
import webbrowser
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for


HOST = "127.0.0.1"
PORT = 5055
VDJ_APP_NAME = "VirtualDJ"
LOG = Path.home() / "Desktop" / "virtualdj_lyrics_ai_fix_log.txt"

PREFERRED_MAC_EXTERNAL_DB = Path("/Volumes/SSD-D/VirtualDJ/extra.db")

app = Flask(__name__)

STATE = {
    "db_path": "",
    "message": "",
    "rough_text": "",
    "results": [],
    "selected": None,
    "old_items": [],
    "new_words": [],
    "mapped_items": [],
}


# ---------------------------
# Logging
# ---------------------------

def log(msg=""):
    text = str(msg)
    print(text, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass


def reset_log():
    try:
        LOG.write_text(
            "VIRTUALDJ LYRICS AI FIX V4.1\n"
            f"Start: {datetime.now()}\n"
            + "-" * 70 + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


# ---------------------------
# Database path helpers
# ---------------------------

def suggested_db_paths():
    system = platform.system().lower()
    home = Path.home()
    paths = []

    if system == "darwin":
        paths.extend([
            PREFERRED_MAC_EXTERNAL_DB,
            Path("/Volumes/SSD-D/VirtualDJ/database/extra.db"),
            home / "Library" / "Application Support" / "VirtualDJ" / "extra.db",
            home / "Library" / "Application Support" / "VirtualDJ" / "database" / "extra.db",
            home / "Documents" / "VirtualDJ" / "extra.db",
            home / "Documents" / "VirtualDJ" / "database" / "extra.db",
        ])

        # Shallow external-drive suggestions only, no deep glob at startup.
        volumes = Path("/Volumes")
        if volumes.exists():
            try:
                for vol in volumes.iterdir():
                    if not vol.is_dir():
                        continue
                    paths.extend([
                        vol / "VirtualDJ" / "extra.db",
                        vol / "VirtualDJ" / "database" / "extra.db",
                    ])
            except Exception:
                pass

    elif system == "windows":
        localapp = os.environ.get("LOCALAPPDATA")
        if localapp:
            la = Path(localapp)
            paths.extend([
                la / "VirtualDJ" / "extra.db",
                la / "VirtualDJ" / "database" / "extra.db",
            ])

        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            up = Path(userprofile)
            paths.extend([
                up / "Documents" / "VirtualDJ" / "extra.db",
                up / "Documents" / "VirtualDJ" / "database" / "extra.db",
                up / "OneDrive" / "Documents" / "VirtualDJ" / "extra.db",
                up / "OneDrive" / "Documents" / "VirtualDJ" / "database" / "extra.db",
            ])

        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:/")
            if root.exists():
                paths.extend([
                    root / "VirtualDJ" / "extra.db",
                    root / "VirtualDJ" / "database" / "extra.db",
                ])

    else:
        paths.extend([
            home / "VirtualDJ" / "extra.db",
            home / "VirtualDJ" / "database" / "extra.db",
        ])

    # Deduplicate, preserve order
    seen = set()
    out = []
    for p in paths:
        s = str(p)
        if s not in seen:
            out.append(p)
            seen.add(s)
    return out


def path_status(path):
    p = Path(path).expanduser()
    exists = p.exists() and p.is_file()
    valid = False
    error = ""

    if exists:
        try:
            con = sqlite3.connect(p, timeout=3)
            cur = con.cursor()
            row = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='lyrics'"
            ).fetchone()
            con.close()
            valid = row is not None
            if not valid:
                error = "File exists but no lyrics table was found."
        except Exception as e:
            error = str(e)

    else:
        error = "File not found."

    return exists, valid, error


def get_db_path():
    raw = STATE.get("db_path", "")
    if not raw:
        return None
    return Path(raw).expanduser()


# ---------------------------
# VirtualDJ process control
# ---------------------------

def run_osascript(script):
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 999, "", repr(e)


def is_virtualdj_running():
    system = platform.system().lower()

    if system == "darwin":
        code, out, err = run_osascript(
            'tell application "System Events" to return exists process "VirtualDJ"'
        )
        return out.strip().lower() == "true"

    if system == "windows":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq virtualdj.exe"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "virtualdj.exe" in r.stdout.lower()
        except Exception:
            return False

    return False


def close_virtualdj():
    system = platform.system().lower()

    if not is_virtualdj_running():
        return True, "VirtualDJ was not running."

    if system == "darwin":
        code, out, err = run_osascript('tell application "VirtualDJ" to quit')
        if code != 0:
            code2, out2, err2 = run_osascript(
                'tell application "System Events" to if exists process "VirtualDJ" then keystroke "q" using command down'
            )
            if code2 != 0:
                return False, f"Could not close VirtualDJ: {err} / {err2}"

    elif system == "windows":
        try:
            subprocess.run(
                ["taskkill", "/IM", "virtualdj.exe"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as e:
            return False, f"Could not close VirtualDJ: {e}"

    deadline = time.time() + 20
    while time.time() < deadline:
        if not is_virtualdj_running():
            time.sleep(2)
            return True, "VirtualDJ closed."
        time.sleep(0.5)

    return False, "VirtualDJ still appears to be running."


def reopen_virtualdj():
    system = platform.system().lower()

    if system == "darwin":
        code, out, err = run_osascript('tell application "VirtualDJ" to activate')
        if code != 0:
            try:
                r = subprocess.run(
                    ["open", "-a", "VirtualDJ"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if r.returncode != 0:
                    return False, r.stderr.strip()
            except Exception as e:
                return False, repr(e)

    elif system == "windows":
        possible = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "VirtualDJ" / "virtualdj.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "VirtualDJ" / "virtualdj.exe",
        ]

        for p in possible:
            if p.exists():
                subprocess.Popen([str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
                return True, "VirtualDJ reopened."

        try:
            subprocess.Popen(["virtualdj.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return False, f"Could not reopen VirtualDJ: {e}"

    else:
        return False, "Automatic reopen is only supported on macOS and Windows."

    time.sleep(2)
    return True, "VirtualDJ reopened."


# ---------------------------
# Lyrics logic
# ---------------------------

def normalize(s):
    s = "" if s is None else str(s)
    s = s.lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\[[^\]]+\]", " ", s)
    s = re.sub(r"[^a-z0-9œæàâçéèêëîïôûùüÿñ' ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm_word(w):
    return normalize(w).replace("'", "")


def clean_text_for_injection(text):
    text = "" if text is None else str(text)
    cleaned = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"\[[^\]]+\]", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def words_from_plain_text(text):
    text = clean_text_for_injection(text).replace("\n", " ")
    return re.findall(r"\S+", text)


def text_similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def extract_timed_lines_from_vdj_xml(xml):
    timed = []
    for idx, line in enumerate((xml or "").splitlines()):
        m = re.match(r"^(\[[^\]]+\]\s*)(.*)$", line)
        if not m:
            continue
        timed.append({
            "line_index": idx,
            "prefix": m.group(1),
            "word": (m.group(2) or "").strip(),
            "line": line,
        })
    return timed


def extract_words_from_vdj_xml(xml):
    return " ".join(item["word"] for item in extract_timed_lines_from_vdj_xml(xml) if item["word"])


def search_lyrics_entries(rough_text):
    db = get_db_path()
    if not db:
        raise RuntimeError("No extra.db path selected.")

    con = sqlite3.connect(db, timeout=30)
    cur = con.cursor()
    rows = cur.execute("SELECT hex(lid), xml FROM lyrics").fetchall()
    con.close()

    scored = []
    for lid_hex, xml in rows:
        vdj_text = extract_words_from_vdj_xml(xml)
        scored.append({
            "score": text_similarity(rough_text, vdj_text),
            "lid_hex": lid_hex,
            "xml": xml,
            "preview": vdj_text[:450],
            "timed_count": len(extract_timed_lines_from_vdj_xml(xml)),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]


def map_new_words_to_original_prefixes(old_items, new_words):
    old_words = [x["word"] for x in old_items]
    old_norm = [norm_word(w) for w in old_words]
    new_norm = [norm_word(w) for w in new_words]
    sm = SequenceMatcher(None, old_norm, new_norm, autojunk=False)

    mapped = []

    def prefix_at_old_index(i):
        i = max(0, min(i, len(old_items) - 1))
        return old_items[i]["prefix"]

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        new_chunk = new_words[j1:j2]
        old_count = i2 - i1
        new_count = j2 - j1

        if tag == "equal":
            for offset, word in enumerate(new_chunk):
                oi = i1 + offset
                mapped.append({
                    "prefix": prefix_at_old_index(oi),
                    "word": word,
                    "source": "kept",
                    "old_index": oi,
                    "new_index": j1 + offset,
                })

        elif tag == "replace":
            if old_count == new_count and old_count > 0:
                for offset, word in enumerate(new_chunk):
                    oi = i1 + offset
                    mapped.append({
                        "prefix": prefix_at_old_index(oi),
                        "word": word,
                        "source": "replaced",
                        "old_index": oi,
                        "new_index": j1 + offset,
                    })
            elif old_count > 0:
                for offset, word in enumerate(new_chunk):
                    rel = int(offset * old_count / max(1, new_count))
                    oi = min(i1 + rel, i2 - 1)
                    mapped.append({
                        "prefix": prefix_at_old_index(oi),
                        "word": word,
                        "source": "replaced_distributed",
                        "old_index": oi,
                        "new_index": j1 + offset,
                    })
            else:
                base = i1 - 1 if i1 > 0 else i1
                for offset, word in enumerate(new_chunk):
                    mapped.append({
                        "prefix": prefix_at_old_index(base),
                        "word": word,
                        "source": "inserted_clone",
                        "old_index": base,
                        "new_index": j1 + offset,
                    })

        elif tag == "insert":
            prev_i = i1 - 1
            next_i = i1
            for offset, word in enumerate(new_chunk):
                if i1 <= 0:
                    oi = 0
                elif i1 >= len(old_items):
                    oi = len(old_items) - 1
                else:
                    oi = prev_i if offset < new_count / 2 else next_i
                mapped.append({
                    "prefix": prefix_at_old_index(oi),
                    "word": word,
                    "source": "inserted_clone",
                    "old_index": oi,
                    "new_index": j1 + offset,
                })

        elif tag == "delete":
            continue

    return mapped


def rebuild_xml_with_cloned_prefixes(original_xml, old_items, mapped_items):
    lines = (original_xml or "").splitlines()
    timed_indices = [item["line_index"] for item in old_items]

    if not timed_indices:
        return "\n".join(
            item["prefix"] + re.sub(r"^\[[^\]]+\]\s*", "", item["word"]).strip()
            for item in mapped_items
        )

    first = timed_indices[0]
    last = timed_indices[-1]
    before = lines[:first]
    after = lines[last + 1:]

    separators_after = {i: [] for i in range(len(old_items))}
    for old_i in range(len(old_items) - 1):
        a = old_items[old_i]["line_index"]
        b = old_items[old_i + 1]["line_index"]
        if b > a + 1:
            separators_after[old_i].extend(lines[a + 1:b])

    output = []
    for pos, item in enumerate(mapped_items):
        word = re.sub(r"^\[[^\]]+\]\s*", "", item["word"]).strip()
        output.append(item["prefix"] + word)

        current_old = item.get("old_index")
        next_old = mapped_items[pos + 1].get("old_index") if pos + 1 < len(mapped_items) else None
        if current_old is not None and current_old != next_old:
            output.extend(separators_after.get(current_old, []))

    return "\n".join(before + output + after)


def write_lyrics_to_db(lid_hex, new_xml):
    db = get_db_path()
    if not db:
        raise RuntimeError("No extra.db path selected.")

    backup = db.with_name(
        f"extra.backup-before-lyrics-ai-fix-v41-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    )
    shutil.copy2(db, backup)

    con = sqlite3.connect(db, timeout=30)
    cur = con.cursor()
    cur.execute("UPDATE lyrics SET xml=? WHERE lid=?", (new_xml, bytes.fromhex(lid_hex)))
    con.commit()
    con.close()
    return backup


# ---------------------------
# Web UI
# ---------------------------

CSS = """
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; background: #f7f7f7; color: #111; }
.card { background: white; padding: 18px; border-radius: 12px; box-shadow: 0 1px 8px rgba(0,0,0,.08); margin-bottom: 18px; }
textarea { width: 100%; min-height: 240px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 14px; padding: 12px; box-sizing: border-box; }
input[type=text] { width: 100%; padding: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; box-sizing: border-box; }
input[type=submit], .button { padding: 10px 16px; border: 0; border-radius: 8px; background: #111; color: white; font-size: 15px; cursor: pointer; text-decoration: none; display: inline-block; }
.button.secondary { background: #ddd; color: #111; }
.result { border: 1px solid #ddd; border-radius: 10px; padding: 12px; margin: 10px 0; background: #fafafa; }
.preview { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; color: #333; }
.small { color: #666; font-size: 13px; }
.badge { display: inline-block; background: #eee; padding: 3px 7px; border-radius: 999px; font-size: 12px; }
.msg { background: #fff6d7; padding: 12px; border-radius: 8px; margin-bottom: 16px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
td, th { border-bottom: 1px solid #eee; padding: 6px; text-align: left; }
</style>
"""


def page(title, body):
    db = STATE.get("db_path") or "No database selected"
    return render_template_string(f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
{CSS}
</head>
<body>
<h1>{title}</h1>
<div class="small">Database: {db}</div>
<br>
{body}
</body>
</html>
""")


@app.route("/", methods=["GET", "POST"])
def index():
    if not STATE.get("db_path"):
        return redirect(url_for("select_db"))

    if request.method == "POST":
        rough = request.form.get("rough_text", "")
        close_before_read = request.form.get("close_before_read") == "on"
        STATE["rough_text"] = rough

        try:
            if close_before_read:
                ok, msg = close_virtualdj()
                if not ok:
                    STATE["message"] = "Could not close VirtualDJ: " + msg
                    return redirect(url_for("index"))

            STATE["results"] = search_lyrics_entries(rough)
            STATE["message"] = ""
            return redirect(url_for("results"))
        except Exception as e:
            STATE["message"] = f"Error: {e}"

    msg = f'<div class="msg">{STATE["message"]}</div>' if STATE.get("message") else ""
    return page("VIRTUALDJ LYRICS AI FIX V4.1", f"""
{msg}
<div class="card">
<form method="post">
<h2>1. Paste approximate / OCR lyrics</h2>
<textarea name="rough_text">{STATE.get("rough_text", "")}</textarea>
<br><br>
<label><input type="checkbox" name="close_before_read" checked> Close VirtualDJ before reading extra.db</label>
<br><br>
<input type="submit" value="Search lyrics entries">
<a class="button secondary" href="/select-db">Change database</a>
</form>
</div>
""")


@app.route("/select-db", methods=["GET", "POST"])
def select_db():
    if request.method == "POST":
        path = request.form.get("db_path", "").strip()
        p = Path(path).expanduser()

        exists, valid, error = path_status(p)
        if exists:
            STATE["db_path"] = str(p.resolve())
            STATE["message"] = "Database selected." if valid else f"Database selected, but validation warning: {error}"
            return redirect(url_for("index"))

        STATE["message"] = f"File not found: {p}"

    msg = f'<div class="msg">{STATE["message"]}</div>' if STATE.get("message") else ""

    suggestions_html = ""
    for p in suggested_db_paths():
        exists, valid, error = path_status(p)
        status = "valid" if valid else ("exists" if exists else "missing")
        suggestions_html += f"""
<div class="result">
<form method="post">
<input type="hidden" name="db_path" value="{p}">
<strong>{p}</strong><br>
<span class="badge">{status}</span>
<input type="submit" value="Use this path">
</form>
</div>
"""

    default_path = STATE.get("db_path") or str(PREFERRED_MAC_EXTERNAL_DB)

    return page("Select extra.db", f"""
{msg}
<div class="card">
<h2>Manual database path</h2>
<form method="post">
<input type="text" name="db_path" value="{default_path}">
<br><br>
<input type="submit" value="Use database">
</form>
</div>

<div class="card">
<h2>Suggested locations</h2>
{suggestions_html}
</div>
""")


@app.route("/results", methods=["GET", "POST"])
def results():
    results = STATE.get("results", [])
    if request.method == "POST":
        idx = int(request.form.get("choice", "0"))
        if 0 <= idx < len(results):
            STATE["selected"] = results[idx]
            return redirect(url_for("corrected"))

    items = ""
    for i, r in enumerate(results):
        items += f"""
<div class="result">
<label><input type="radio" name="choice" value="{i}" {'checked' if i == 0 else ''}> <strong>Entry {i+1}</strong></label><br>
<span class="badge">score {r['score']:.3f}</span>
<span class="badge">timestamps {r['timed_count']}</span>
<span class="badge">lid {r['lid_hex']}</span>
<div class="preview">{r['preview']}</div>
</div>
"""
    return page("Choose lyrics entry", f"""
<div class="card">
<form method="post">
{items}
<input type="submit" value="Use selected entry">
<a class="button secondary" href="/">Back</a>
</form>
</div>
""")


@app.route("/corrected", methods=["GET", "POST"])
def corrected():
    selected = STATE.get("selected")
    if not selected:
        return redirect(url_for("index"))

    if request.method == "POST":
        clean = request.form.get("clean_text", "")
        old_items = extract_timed_lines_from_vdj_xml(selected["xml"])
        new_words = words_from_plain_text(clean)
        mapped = map_new_words_to_original_prefixes(old_items, new_words)
        STATE["old_items"] = old_items
        STATE["new_words"] = new_words
        STATE["mapped_items"] = mapped
        return redirect(url_for("preview"))

    return page("Corrected lyrics", f"""
<div class="card">
<h2>2. Paste clean / corrected lyrics</h2>
<form method="post">
<textarea name="clean_text"></textarea>
<br><br>
<input type="submit" value="Preview alignment">
<a class="button secondary" href="/results">Back</a>
</form>
</div>
""")


@app.route("/preview", methods=["GET", "POST"])
def preview():
    selected = STATE.get("selected")
    old_items = STATE.get("old_items", [])
    new_words = STATE.get("new_words", [])
    mapped = STATE.get("mapped_items", [])

    if not selected:
        return redirect(url_for("index"))

    if request.method == "POST":
        close_vdj = request.form.get("close_vdj") == "on"
        reopen_vdj = request.form.get("reopen_vdj") == "on"
        messages = []

        if close_vdj:
            ok, msg = close_virtualdj()
            messages.append(msg)
            if not ok:
                STATE["message"] = "Could not close VirtualDJ: " + msg
                return redirect(url_for("preview"))

        try:
            new_xml = rebuild_xml_with_cloned_prefixes(selected["xml"], old_items, mapped)
            backup = write_lyrics_to_db(selected["lid_hex"], new_xml)
            messages.append(f"Backup created: {backup}")
            messages.append(f"Correction complete. Words written: {len(mapped)}")

            if close_vdj and reopen_vdj:
                ok, msg = reopen_virtualdj()
                messages.append(msg)

            STATE["message"] = "<br>".join(messages)
            return redirect(url_for("done"))
        except Exception as e:
            STATE["message"] = f"Write error: {e}"

    counts = {}
    for item in mapped:
        counts[item["source"]] = counts.get(item["source"], 0) + 1

    count_html = "".join(f"<li>{k}: {v}</li>" for k, v in sorted(counts.items()))
    rows = ""
    for i, item in enumerate(mapped[:250], 1):
        old_display = "" if item["old_index"] is None else str(item["old_index"] + 1)
        rows += f"""
<tr>
<td>{i}</td>
<td>{item['source']}</td>
<td>{old_display}</td>
<td><code>{item['prefix'].strip()}</code></td>
<td>{item['word']}</td>
</tr>
"""

    msg = f'<div class="msg">{STATE["message"]}</div>' if STATE.get("message") else ""
    return page("Preview alignment", f"""
{msg}
<div class="card">
<h2>3. Preview alignment</h2>
<p>Original timestamped words: <strong>{len(old_items)}</strong><br>
Corrected words: <strong>{len(new_words)}</strong><br>
Written lines: <strong>{len(mapped)}</strong></p>
<ul>{count_html}</ul>
<p class="small">No timestamp is generated or reformatted. Internal VirtualDJ separators are preserved.</p>
</div>

<div class="card">
<table>
<tr><th>#</th><th>source</th><th>old#</th><th>original prefix</th><th>written word</th></tr>
{rows}
</table>
</div>

<div class="card">
<form method="post">
<label><input type="checkbox" name="close_vdj" checked> Close VirtualDJ before writing</label><br>
<label><input type="checkbox" name="reopen_vdj" checked> Reopen VirtualDJ after writing</label><br><br>
<input type="submit" value="Write to extra.db">
<a class="button secondary" href="/corrected">Back</a>
</form>
</div>
""")


@app.route("/done")
def done():
    msg = STATE.get("message", "Done.")
    return page("Done", f"""
<div class="card">
<div class="msg">{msg}</div>
<a class="button" href="/">New correction</a>
<a class="button secondary" href="/select-db">Change database</a>
</div>
""")


if __name__ == "__main__":
    reset_log()
    # Preselect the preferred macOS external path if it exists.
    if PREFERRED_MAC_EXTERNAL_DB.exists():
        STATE["db_path"] = str(PREFERRED_MAC_EXTERNAL_DB.resolve())
        log(f"Preselected database: {STATE['db_path']}")

    url = f"http://{HOST}:{PORT}"
    log(f"Starting web interface: {url}")
    log("The browser should open automatically. If not, open this URL manually.")

    def open_browser_later():
        time.sleep(1.5)
        try:
            webbrowser.open_new_tab(url)
        except Exception as e:
            log(f"Browser launch failed: {e}")

    threading.Thread(target=open_browser_later, daemon=True).start()

    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
