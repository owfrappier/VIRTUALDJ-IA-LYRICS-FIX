<<<<<<< HEAD

=======
>>>>>>> 71029e1a1cdf06dae505fa855d5d95938e71f191
v5.3

- Added Robust Alignment mode for difficult lyrics
- Smart Alignment remains the default mode
- Improved preservation of original karaoke timing
- Automatic extra.db backup
- Windows and macOS support


Release v4.5
Stable screen-aware alignment


# VIRTUALDJ IA LYRICS FIX

A local web-based tool for correcting and realigning synchronized lyrics stored in VirtualDJ's `extra.db`.

This tool was created to help fix OCR-style or inaccurate lyrics while preserving VirtualDJ's existing word timing structure.

## What it does

- Runs as a local web interface.
- Lets you paste approximate/OCR lyrics.
- Finds the closest matching lyrics entries inside VirtualDJ's `extra.db`.
- Lets you manually choose the correct entry.
- Lets you paste corrected lyrics.
- Rebuilds the lyrics entry with smart word alignment.
- Preserves original VirtualDJ timestamp prefixes.
- Preserves internal VirtualDJ page/screen separators when possible.
- Creates an automatic backup before writing to `extra.db`.
- Can close VirtualDJ before reading/writing the database and reopen it afterward.

## Important safety notes

This tool modifies VirtualDJ's `extra.db`.

Before every write operation, the tool creates a timestamped backup in the same folder as `extra.db`.

Even with backups, you should keep your own copy of the VirtualDJ database before using this tool on an important library.

## Platform status

### macOS

Tested and validated on macOS with VirtualDJ using an external database path such as:

```text
/Volumes/SSD-D/VirtualDJ/extra.db
```

Tested features on macOS:

- Local Flask web interface
- VirtualDJ `extra.db` reading/writing
- Lyrics entry search
- Smart lyrics alignment
- Backup creation
- VirtualDJ close/reopen

### Windows

Windows support is implemented but has not yet been tested on a real Windows system.

Expected VirtualDJ database locations include:

```text
%LOCALAPPDATA%/VirtualDJ/extra.db
%LOCALAPPDATA%/VirtualDJ/database/extra.db
D:/VirtualDJ/extra.db
D:/VirtualDJ/database/extra.db
```

Windows support should be considered experimental for now.

Feedback and pull requests are welcome.

## Requirements

- Python 3.9 or newer
- Flask

Install dependencies:

```bash
pip install -r requirements.txt
```

## How to run

From the project folder:

```bash
python3 VIRTUALDJ_LYRICS_IA_FIX.py
```

On Windows, depending on your Python installation:

```bash
python VIRTUALDJ_LYRICS_IA_FIX.py
```

The browser should open automatically.

If it does not, open:

```text
http://127.0.0.1:5055
```

## Basic workflow

1. Start the script.
2. Select or confirm the `extra.db` path.
3. Paste approximate/OCR lyrics into the first text area.
4. Search entries.
5. Select the correct VirtualDJ lyrics entry.
6. Paste the corrected lyrics.
7. Preview the alignment.
8. Write the corrected lyrics back to `extra.db`.

## How alignment works

The tool compares the existing VirtualDJ timestamped lyrics with the corrected lyrics.

- Matching words keep their original timestamp prefix.
- Added or replaced words receive cloned timestamp prefixes from nearby existing words.
- The tool does not generate a new timestamp format.
- The tool tries to preserve internal non-timestamp separator lines used by VirtualDJ for lyric pages/screens.

## Database locations

VirtualDJ database locations may vary depending on version, OS, and whether the library is on an internal or external disk.

### macOS current internal location

```text
~/Library/Application Support/VirtualDJ/extra.db
~/Library/Application Support/VirtualDJ/database/extra.db
```

### macOS external disk examples

```text
/Volumes/<DriveName>/VirtualDJ/extra.db
/Volumes/<DriveName>/VirtualDJ/database/extra.db
```

### macOS legacy location

```text
~/Documents/VirtualDJ/extra.db
~/Documents/VirtualDJ/database/extra.db
```

### Windows current internal location

```text
%LOCALAPPDATA%/VirtualDJ/extra.db
%LOCALAPPDATA%/VirtualDJ/database/extra.db
```

### Windows external disk examples

```text
D:/VirtualDJ/extra.db
D:/VirtualDJ/database/extra.db
E:/VirtualDJ/extra.db
E:/VirtualDJ/database/extra.db
```

## Project file

Main script:

```text
VIRTUALDJ_LYRICS_IA_FIX_v4_1.py
```

## Disclaimer

This project is not affiliated with or endorsed by VirtualDJ or Atomix Productions.

Use at your own risk. Always keep backups of your VirtualDJ database.

## Author

Olivier W. Frappier
