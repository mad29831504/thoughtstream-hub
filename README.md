# ThoughtStream Hub

**Desktop client for the ThoughtStream API by SoulTechLabs**

ThoughtStream Hub is a desktop app for compressing memory files, AI conversations, notes, logs, and long-form text through the ThoughtStream API.

ThoughtStream reduces text size while preserving meaning, structure, and recoverable context. It is built for AI memory workflows, long conversations, agent systems, and users who want cleaner, smaller context without manually managing compression through the terminal.

---

## What ThoughtStream Does

ThoughtStream is a linguistic compression engine designed for AI-readable memory.

It converts normal text into compressed kernels that reduce token load while preserving the important relationships inside the text.

The Hub gives you a simple interface to:

- Compress text files, memory logs, and AI conversations
- Run single-file conversions
- Batch compress entire folders
- Choose compression mode
- Generate blooms, reports, and backups
- Track local usage
- Review output before replacing memory files

---

## Compression Modes

ThoughtStream Hub supports three compression modes:

| Mode | Best For | Description |
|------|----------|-------------|
| Conservative | Human-readable memory | Light compression. Keeps words mostly readable while applying semantic operators. Best for memory replacement and review. |
| Balanced | AI-native memory kernels | Stronger compression. Uses phonological reduction and operators for denser AI-readable memory. |
| Aggressive | Cold archive / experimental | Reserved for future sub-operator compression. Not recommended for important memory yet. |

For most users:

- Use **Conservative** for memory files you want to read or review.
- Use **Balanced** for AI memory packets and deeper archive storage.
- Avoid **Aggressive** unless intentionally testing experimental compression behavior.

---

## Expected Compression

Typical compression varies depending on file type, writing style, mode, and content density.

General range:

- Conservative: lighter compression, higher readability
- Balanced: stronger compression, AI-native kernel output
- Aggressive: future experimental compression layer

ThoughtStream commonly reduces text by **30–50%**, with some files compressing more or less depending on structure.

---

## Getting Started

### Option A — Run From Source

**Requirements:** Python 3.10+

Install requirements:

```bash
pip install -r requirements.txt
```

Run the Hub:

```bash
python thoughtstream_hub.py
```

### Option B — Windows .exe

Download `ThoughtStreamHub.exe` from the [Releases](../../releases) page.

Double-click to run.

No Python setup required.

---

## API Key

You need a ThoughtStream API key to use the Hub.

Get your key at: **https://soultechlabs.net**

Then:

1. Open ThoughtStream Hub
2. Go to the **Settings** tab
3. Paste your API key
4. Choose your Memory Folder
5. Save settings
6. Test the connection

---

## Memory Folder

ThoughtStream Hub saves outputs into your selected Memory Folder.

The Hub creates these subfolders automatically:

| Folder | Purpose |
|--------|---------|
| `raw_backup/` | Original source copies before any replacement |
| `blooms/` | Compressed Bloom output ready for review |
| `reports/` | Conversion reports for each run |

---

## Single File Conversion

Use the **Convert** tab to compress one file at a time.

Basic flow:

1. Select a file
2. Choose compression mode
3. Optionally run Organizer first
4. Run preview
5. Review the output
6. Save or replace only when ready

The original file is not overwritten unless replacement is explicitly selected.

---

## Paste-to-Convert

You can also paste text directly into the Convert tab.

This allows you to:

- Copy text from anywhere
- Paste it into the Hub
- Compress it without selecting a file
- Save the Bloom output

This is useful for quick tests, prompt compression, memory snippets, and live text experiments.

---

## Batch Conversion

Use the **Batch** tab to compress multiple files at once.

Basic flow:

1. Select a folder
2. Choose file types
3. Choose compression mode
4. Run batch

Batch mode is useful for memory folders, archive cleanup, long AI conversation logs, and agent memory preparation.

> **Note:** Batch conversion can use a large number of tokens. Review your usage before running large folders.

---

## Usage Tracking

The **Usage** tab tracks local estimated usage, including:

- API requests
- Input processed
- Output produced
- Estimated tokens saved
- Compression ratio
- Remaining token budget

The local counter is an estimate. Server-side usage is authoritative.

---

## Plans

| Plan | Monthly Compression |
|------|-------------------|
| Basic | ~900k characters |
| Plus | ~1.6M characters |
| Pro | ~4M characters |

Plan limits may change during beta as the system is tested and improved.

---

## Safety Notes

ThoughtStream Hub is designed to protect memory workflows.

Important safety behavior:

- Originals are backed up before replacement when backup is enabled
- Batch conversion does not overwrite originals by default
- Replacement must be explicitly selected
- Reports are generated so conversions can be reviewed
- Blooms should be checked before replacing important memory

Recommended:

- Keep backups enabled
- Review Bloom output before replacement
- Use Conservative mode for important human-readable memory
- Use Balanced mode for AI-native archive kernels
- Avoid double-compressing files unless intentionally testing

---

## Persistent Memory Safety

ThoughtStream is more than shorthand.

Small personal experiments with compression are fine. However, using an unsupported or unchecked DIY compression system for persistent AI memory can create silent drift over time.

If two meanings collapse into one token, or if names, numbers, dates, URLs, emails, or negation terms are not protected correctly, an agent may reload corrupted memory without throwing an obvious error.

This is why ThoughtStream uses a managed compression environment rather than simple word replacement.

For long-term agent memory, use the full ThoughtStream pipeline and keep backups enabled.

---

## DIY Compression Warning

ThoughtStream does not discourage experimentation.

You can experiment with your own shorthand or compression ideas for casual use.

But for persistent AI agents, production memory, or important long-term archives, unchecked DIY compression is risky.

Common risks include:

- Word collisions
- Lost negation
- Changed numbers or units
- Corrupted names, URLs, or emails
- Meaning drift across sessions
- Memory degradation without visible errors
- Agents reloading bad memory repeatedly

A compression layer may appear to work at small scale, then quietly degrade as the memory grows.

ThoughtStream is built to reduce that risk through collision management, protected literals, validation, and reviewable Bloom output.

---

## Double Compression

Do not double-compress files by default.

Compressing an already compressed Bloom may create small additional savings, but it can also reduce readability or introduce artifacts.

Recommended rule:

- Compress original or organized source once
- Use Bloom output for review and archive
- Avoid second-pass compression unless intentionally testing

---

## What Gets Sent to the API

Your local files are not stored on SoulTechLabs servers.

Only the text you choose to compress is sent to the ThoughtStream API for processing.

The Hub is the desktop client. The compression engine runs server-side.

---

## What ThoughtStream Is Not

ThoughtStream is not:

- A chatbot
- A replacement for your AI model
- A general file storage service
- A guarantee that every compressed file is safe to overwrite without review
- A simple find-and-replace shorthand system

ThoughtStream is a compression and memory-preparation layer designed to help AI systems carry more meaning with less text.

---

## Best Practices

For safest results:

- Start with Conservative mode
- Review Bloom output before replacing anything
- Keep backups enabled
- Use Balanced mode for AI-native archive kernels
- Run batch jobs on small folders first
- Avoid replacing originals until you trust the output
- Do not use unchecked DIY compression for persistent agent memory

---

## About SoulTechLabs

ThoughtStream was built by SoulTechLabs — built from long-form AI memory work, agent continuity experiments, and practical compression testing.

Current system highlights:

- 18 months of development
- 15,000+ collision-managed vocabulary entries
- Organizer-first pipeline
- Protected literal handling
- Health-check focused workflow
- Bloom output with backup and report generation
- Desktop Hub for local file workflows

Built to preserve meaning, structure, and recoverable context under compression.

---

## Contact

- **Website:** https://soultechlabs.net
- **Email:** soultechlabs@gmail.com
- **X:** @SoulTechLabs

---

## Beta Notice

ThoughtStream Hub is currently in beta.

Features, pricing, limits, and compression behavior may change as the system improves. We'll communicate changes clearly.

Use backups. Review outputs. Test carefully before replacing important memory files.
