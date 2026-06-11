#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VIRTUALDJ LYRICS AI FIX - V5.3

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
    python3 VIRTUALDJ_LYRICS_AI_FIX_v5_3.py

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
    "alignment_mode": "smart",
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
            "VIRTUALDJ LYRICS AI FIX V5.3\n"
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


def words_and_line_end_flags_from_text(text):
    """
    Return:
    - words: flat list of words
    - line_end_flags: same length list, True when the word is the last word
      of a corrected-text line.

    This lets the screen/page separator logic avoid cutting a karaoke phrase
    in the middle of a user-provided corrected lyric line.

    Example corrected lines:
        Y courent partout
        Toujours et encore

    The preferred screen breaks become:
        after "partout"
        after "encore"
    and NOT after "Toujours".
    """
    text = clean_text_for_injection(text)
    words = []
    flags = []

    for line in text.splitlines():
        line_words = re.findall(r"\S+", line.strip())
        if not line_words:
            continue

        for i, word in enumerate(line_words):
            words.append(word)
            flags.append(i == len(line_words) - 1)

    return words, flags


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
            # V5.3 simple rule:
            # Added words stay on the same screen as the nearest similar/matched word.
            #
            # If words are inserted BEFORE an existing matched word, attach all of them
            # to the NEXT old index. This prevents cases like:
            #     "Y courent partout / Toujours et encore"
            # from putting "Toujours" alone on the previous screen.
            #
            # If insertion is at the end, attach to the previous old index.
            if i1 < len(old_items):
                oi = i1          # inserted before this existing word
            else:
                oi = len(old_items) - 1  # inserted after the last existing word

            for offset, word in enumerate(new_chunk):
                mapped.append({
                    "prefix": prefix_at_old_index(oi),
                    "word": word,
                    "source": "inserted_same_screen",
                    "old_index": oi,
                    "new_index": j1 + offset,
                })

        elif tag == "delete":
            continue

    return mapped


def split_old_items_into_screen_blocks(original_xml, old_items):
    """
    Split original VirtualDJ timed lyric words into screen/page blocks.
    A block break is detected when non-timestamp separator lines exist between
    two timestamped lyric lines.
    """
    lines = (original_xml or "").splitlines()

    if not old_items:
        return []

    blocks = []
    current = [0]

    for old_i in range(len(old_items) - 1):
        current_line_idx = old_items[old_i]["line_index"]
        next_line_idx = old_items[old_i + 1]["line_index"]

        has_separator = next_line_idx > current_line_idx + 1

        if has_separator:
            blocks.append(current)
            current = [old_i + 1]
        else:
            current.append(old_i + 1)

    if current:
        blocks.append(current)

    return blocks


def corrected_lines_as_word_groups(clean_text):
    """
    Keep corrected pasted line breaks as phrase groups.

    Useful when the original text is too wrong for word-level matching, such as
    heavily distorted AI recognition or minority languages.
    """
    text = clean_text_for_injection(clean_text)
    groups = []

    for line in text.splitlines():
        words = re.findall(r"\S+", line.strip())
        if words:
            groups.append(words)

    if not groups:
        words = words_from_plain_text(clean_text)
        if words:
            groups = [words]

    return groups


def distribute_words_to_screen_blocks_by_original_weight(corrected_words, screen_blocks):
    """
    Difficult lyrics distribution V5.3.

    Previous V4.7 distributed corrected LINES across VirtualDJ screen blocks.
    That could create empty screens when VirtualDJ had more screens than the
    corrected pasted text had lines.

    V5.3 distributes corrected WORDS across screen blocks proportionally to the
    number of original timestamped words in each screen block.

    Guarantees:
    - every corrected word is assigned exactly once;
    - no corrected word is lost;
    - avoids empty middle screens when possible;
    - keeps the original VirtualDJ screen structure.
    """
    screen_count = len(screen_blocks)

    if screen_count <= 0:
        return []

    if not corrected_words:
        return [[] for _ in range(screen_count)]

    total_words = len(corrected_words)
    weights = [max(1, len(block)) for block in screen_blocks]
    total_weight = sum(weights)

    # Initial proportional allocation
    counts = []
    remaining = total_words

    for i, weight in enumerate(weights):
        if i == screen_count - 1:
            count = remaining
        else:
            count = round(total_words * weight / total_weight)
            count = max(0, min(count, remaining))
        counts.append(count)
        remaining -= count

    # If there are enough words, avoid empty blocks in the middle.
    if total_words >= screen_count:
        for i in range(screen_count):
            if counts[i] == 0:
                # Borrow from the largest block with more than 1 word.
                donor = None
                for j in sorted(range(screen_count), key=lambda x: counts[x], reverse=True):
                    if counts[j] > 1:
                        donor = j
                        break
                if donor is not None:
                    counts[donor] -= 1
                    counts[i] += 1

    # Fix rounding drift
    diff = total_words - sum(counts)
    while diff > 0:
        # Add to the currently largest-weight block
        target = max(range(screen_count), key=lambda i: weights[i])
        counts[target] += 1
        diff -= 1

    while diff < 0:
        donor = max(range(screen_count), key=lambda i: counts[i])
        if counts[donor] > 0:
            counts[donor] -= 1
            diff += 1
        else:
            break

    # Build assignment
    assigned = []
    cursor = 0

    for count in counts:
        assigned.append(corrected_words[cursor:cursor + count])
        cursor += count

    # Safety: append any remaining words to the last non-empty block.
    if cursor < total_words:
        target = screen_count - 1
        assigned[target].extend(corrected_words[cursor:])

    return assigned

SMALL_JOIN_WORDS = {
    "a", "à", "e", "è", "u", "i", "o",
    "di", "da", "de", "du", "lu", "la", "le", "li",
    "un", "une", "in", "ind", "ind'u", "d'u",
    "ci", "hè", "ne", "ùn", "un",
    "so", "sò", "ssu", "s'", "l'", "d'",
    "et", "à", "au", "aux", "en", "y",
}


def normalized_join_word(word):
    return norm_word(word).replace("’", "'")


def make_safe_difficult_chunks(words):
    """
    V5.3:
    In difficult mode, do not write very small connector words alone.

    Some languages, especially Corsican, contain many short words:
        è, di, u, ci, ne, la, ...
    When one of these lands alone on an isolated timestamp, VirtualDJ can display
    a very poor karaoke screen, sometimes looking like an empty/black transition.

    Strategy:
    - join small connector words with the following word when possible;
    - otherwise join them to the previous chunk;
    - keep meaningful words as their own chunks.
    """
    chunks = []
    i = 0

    while i < len(words):
        word = words[i]
        n = normalized_join_word(word)

        if n in SMALL_JOIN_WORDS:
            # Prefer attaching to the next word.
            if i + 1 < len(words):
                chunks.append(word + " " + words[i + 1])
                i += 2
                continue

            # Last tiny word: attach to previous chunk if possible.
            if chunks:
                chunks[-1] = chunks[-1] + " " + word
            else:
                chunks.append(word)
            i += 1
            continue

        chunks.append(word)
        i += 1

    # Second pass: avoid one-character chunks in all cases.
    safe = []
    for chunk in chunks:
        stripped = chunk.strip()
        if len(normalized_join_word(stripped)) <= 1 and safe:
            safe[-1] = safe[-1] + " " + stripped
        else:
            safe.append(stripped)

    return [c for c in safe if c]


def find_exact_monotonic_anchors_for_difficult_mode(old_words, new_chunks):
    """
    Find exact monotonic anchors using SequenceMatcher equal blocks.

    Works on chunks, not raw words, in V5.3.
    """
    old_norm = [norm_word(w) for w in old_words]
    new_norm = [norm_word(w) for w in new_chunks]

    sm = SequenceMatcher(None, old_norm, new_norm, autojunk=False)

    anchors = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for oi, nj in zip(range(i1, i2), range(j1, j2)):
                if old_norm[oi] and new_norm[nj]:
                    anchors.append((oi, nj, 1.0, "exact_anchor"))

    return anchors


def add_safe_fuzzy_anchors(old_words, new_chunks, existing_anchors):
    """
    Add fuzzy anchors only inside gaps between exact anchors.

    Works on chunks in V5.3. For multi-word chunks, the normalized chunk may not
    match exactly, so fuzzy anchors are conservative.
    """
    anchors = list(existing_anchors)
    old_norm = [norm_word(w) for w in old_words]
    new_norm = [norm_word(w) for w in new_chunks]

    sorted_exact = sorted(existing_anchors, key=lambda x: x[1])
    boundaries = [(-1, -1)] + [(oi, nj) for oi, nj, _, _ in sorted_exact] + [(len(old_words), len(new_chunks))]

    used_old = {oi for oi, _, _, _ in anchors}
    used_new = {nj for _, nj, _, _ in anchors}

    for b in range(len(boundaries) - 1):
        old_start, new_start = boundaries[b]
        old_end, new_end = boundaries[b + 1]

        old_range = range(old_start + 1, old_end)
        new_range = range(new_start + 1, new_end)

        candidates = []

        for nj in new_range:
            nw = new_norm[nj]
            if not nw or len(nw) < 5 or nj in used_new:
                continue

            for oi in old_range:
                ow = old_norm[oi]
                if not ow or len(ow) < 5 or oi in used_old:
                    continue

                score = SequenceMatcher(None, ow, nw).ratio()

                if score >= 0.90:
                    candidates.append((score, oi, nj))

        candidates.sort(key=lambda x: (-x[0], x[1], x[2]))

        chosen_local = []
        for score, oi, nj in candidates:
            if oi in used_old or nj in used_new:
                continue

            crosses = False
            for _, coi, cnj in chosen_local:
                if (coi < oi and cnj > nj) or (coi > oi and cnj < nj):
                    crosses = True
                    break

            if crosses:
                continue

            chosen_local.append((score, oi, nj))
            used_old.add(oi)
            used_new.add(nj)
            anchors.append((oi, nj, score, "fuzzy_anchor"))

    anchors.sort(key=lambda x: x[1])
    return anchors


def map_corrected_text_by_screen_blocks(original_xml, old_items, clean_text):
    """
    Difficult lyrics mode V5.3.

    Hybrid fallback for very distorted lyrics:
    - do not reuse internal clear-screen separators;
    - keep all corrected text;
    - group tiny connector words with neighbours;
    - lock exact/fuzzy anchor chunks;
    - distribute text chunks between anchors.

    This avoids bad isolated fragments such as a single "è" on its own karaoke
    screen/timestamp.
    """
    corrected_words = words_from_plain_text(clean_text)
    corrected_chunks = make_safe_difficult_chunks(corrected_words)

    if not old_items or not corrected_chunks:
        return []

    old_words = [x["word"] for x in old_items]
    old_count = len(old_items)
    new_count = len(corrected_chunks)

    exact_anchors = find_exact_monotonic_anchors_for_difficult_mode(old_words, corrected_chunks)
    anchors = add_safe_fuzzy_anchors(old_words, corrected_chunks, exact_anchors)

    def prefix_at_old_index(i):
        i = max(0, min(i, old_count - 1))
        return old_items[i]["prefix"]

    if not anchors:
        mapped = []
        for j, chunk in enumerate(corrected_chunks):
            if new_count <= 1:
                old_i = 0
            else:
                old_i = round(j * (old_count - 1) / (new_count - 1))

            mapped.append({
                "prefix": prefix_at_old_index(old_i),
                "word": chunk,
                "source": "difficult_chunk_linear",
                "old_index": old_i,
                "new_index": j,
                "screen_index": None,
            })
        return mapped

    anchor_by_new = {nj: (oi, score, source) for oi, nj, score, source in anchors}

    boundaries = [(-1, -1, 1.0, "virtual_start")] + anchors + [(old_count, new_count, 1.0, "virtual_end")]

    mapped = []

    for seg in range(len(boundaries) - 1):
        old_a, new_a, _, _ = boundaries[seg]
        old_b, new_b, _, _ = boundaries[seg + 1]

        if new_a >= 0:
            chunk = corrected_chunks[new_a]
            oi, score, source = anchor_by_new[new_a]
            mapped.append({
                "prefix": prefix_at_old_index(oi),
                "word": chunk,
                "source": source,
                "old_index": oi,
                "new_index": new_a,
                "screen_index": None,
            })

        inner_new_start = new_a + 1
        inner_new_end = new_b
        inner_indexes = list(range(inner_new_start, inner_new_end))
        inner_count = len(inner_indexes)

        if inner_count <= 0:
            continue

        old_start = old_a + 1
        old_end = old_b - 1

        for k, nj in enumerate(inner_indexes):
            chunk = corrected_chunks[nj]

            if old_end >= old_start:
                if inner_count <= 1:
                    old_i = round((old_start + old_end) / 2)
                else:
                    old_i = round(old_start + k * (old_end - old_start) / max(1, inner_count - 1))
            else:
                if old_b < old_count:
                    old_i = old_b
                elif old_a >= 0:
                    old_i = old_a
                else:
                    old_i = 0

            mapped.append({
                "prefix": prefix_at_old_index(old_i),
                "word": chunk,
                "source": "between_locked_anchors_chunk",
                "old_index": old_i,
                "new_index": nj,
                "screen_index": None,
            })

    if anchors:
        last_anchor_new = anchors[-1][1]
        if not any(item["new_index"] == last_anchor_new for item in mapped):
            oi, score, source = anchor_by_new[last_anchor_new]
            mapped.append({
                "prefix": prefix_at_old_index(oi),
                "word": corrected_chunks[last_anchor_new],
                "source": source,
                "old_index": oi,
                "new_index": last_anchor_new,
                "screen_index": None,
            })

    mapped.sort(key=lambda x: x["new_index"])

    seen = {item["new_index"] for item in mapped}
    missing = [j for j in range(new_count) if j not in seen]

    for j in missing:
        if new_count <= 1:
            old_i = 0
        else:
            old_i = round(j * (old_count - 1) / (new_count - 1))

        mapped.append({
            "prefix": prefix_at_old_index(old_i),
            "word": corrected_chunks[j],
            "source": "missing_safety_chunk",
            "old_index": old_i,
            "new_index": j,
            "screen_index": None,
        })

    mapped.sort(key=lambda x: x["new_index"])
    return mapped

def rebuild_xml_screen_mode_no_empty_screens(original_xml, old_items, mapped_items):
    """
    Rebuild XML for Difficult Lyrics mode.

    V5.3 fix:
    In difficult mode, do NOT reuse original internal separator lines at all.

    Reason:
    Some VirtualDJ separator lines can behave like screen-clear/page-clear markers.
    When reused at the wrong moment after heavy text correction, they may create
    black/empty karaoke screens.

    Safer strategy for difficult lyrics:
    - keep header/footer XML lines around the timed block;
    - write only timestamped lyric lines;
    - keep all corrected words;
    - clone original timestamp prefixes;
    - do not insert any internal non-timestamp separator.
    """
    lines = (original_xml or "").splitlines()
    timed_indices = [item["line_index"] for item in old_items]

    new_timed_lines = []

    for item in mapped_items:
        word = re.sub(r"^\[[^\]]+\]\s*", "", item["word"]).strip()
        if not word:
            continue
        new_timed_lines.append(item["prefix"] + word)

    if not timed_indices:
        return "\n".join(new_timed_lines)

    first = timed_indices[0]
    last = timed_indices[-1]

    before = lines[:first]
    after = lines[last + 1:]

    return "\n".join(before + new_timed_lines + after)

def rebuild_xml_with_cloned_prefixes(original_xml, old_items, mapped_items):
    """
    Rebuild the XML while preserving VirtualDJ screen/page separators.

    Normal smart mode:
    - preserve the original screen separators attached to their original old word index;
    - added words inherit the old_index of the nearest matched/similar word;
    - added words stay on the same VirtualDJ screen as that word.

    Difficult lyrics mode:
    - mapped items contain screen_index;
    - screens are rebuilt by screen_index;
    - separators are inserted only between non-empty screens;
    - this avoids accidental black/empty karaoke screens.
    """
    if any("screen_index" in item for item in mapped_items):
        return rebuild_xml_screen_mode_no_empty_screens(original_xml, old_items, mapped_items)

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

    separators_after_old = {i: [] for i in range(len(old_items))}

    for old_i in range(len(old_items) - 1):
        a = old_items[old_i]["line_index"]
        b = old_items[old_i + 1]["line_index"]
        if b > a + 1:
            separators_after_old[old_i].extend(lines[a + 1:b])

    output = []

    for pos, item in enumerate(mapped_items):
        word = re.sub(r"^\[[^\]]+\]\s*", "", item["word"]).strip()
        output.append(item["prefix"] + word)

        current_old = item.get("old_index")
        next_old = mapped_items[pos + 1].get("old_index") if pos + 1 < len(mapped_items) else None

        if current_old is not None and current_old != next_old:
            output.extend(separators_after_old.get(current_old, []))

    return "\n".join(before + output + after)

def write_lyrics_to_db(lid_hex, new_xml):
    db = get_db_path()
    if not db:
        raise RuntimeError("No extra.db path selected.")

    backup = db.with_name(
        f"extra.backup-before-lyrics-ai-fix-v53-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
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
    return page("VIRTUALDJ LYRICS AI FIX V5.3", f"""
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
        alignment_mode = request.form.get("alignment_mode", "smart")
        old_items = extract_timed_lines_from_vdj_xml(selected["xml"])
        new_words = words_from_plain_text(clean)

        if alignment_mode == "screen":
            mapped = map_corrected_text_by_screen_blocks(selected["xml"], old_items, clean)
        else:
            mapped = map_new_words_to_original_prefixes(old_items, new_words)

        STATE["old_items"] = old_items
        STATE["new_words"] = new_words
        STATE["mapped_items"] = mapped
        STATE["alignment_mode"] = alignment_mode
        return redirect(url_for("preview"))

    return page("Corrected lyrics", f"""
<div class="card">
<h2>2. Paste clean / corrected lyrics</h2>
<form method="post">
<textarea name="clean_text"></textarea>
<br><br>
<h3>Alignment mode</h3>
<label>
<input type="radio" name="alignment_mode" value="smart" checked>
Smart word mode — best for normal cases
</label>
<br>
<label>
<input type="radio" name="alignment_mode" value="screen">
Difficult lyrics mode — locked anchors + connector grouping
</label>
<p class="small">
Use difficult lyrics mode when the original text is extremely wrong and word matching or screen distribution creates large offsets
(for example Corsican or heavily distorted AI recognition).
</p>
<br>
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
<p>Alignment mode: <strong>{STATE.get("alignment_mode", "smart")}</strong><br>
Original timestamped words: <strong>{len(old_items)}</strong><br>
Corrected words: <strong>{len(new_words)}</strong><br>
Written lines: <strong>{len(mapped)}</strong></p>
<ul>{count_html}</ul>
<p class="small">No timestamp is generated or reformatted. Smart mode keeps added words near matched words. Difficult lyrics mode locks anchors, groups tiny connector words with neighbours, and removes internal clear-screen separators.</p>
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
