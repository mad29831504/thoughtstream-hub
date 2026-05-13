# -*- coding: utf-8 -*-
"""
ThoughtStream Hub v0.2.3
SoulTechLabs -- Desktop client for the ThoughtStream API
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox
import json
import os
import re
import sys
import shutil
import tempfile
import requests
from datetime import datetime
from pathlib import Path
import threading
import hashlib
import webbrowser

# ---------------------------------------------------------------------------
# Organizer pre-pass (local, no API needed)
# ---------------------------------------------------------------------------
# Optional: place literal_protector.py and preparser.py alongside this script
TS_LOCAL = Path(__file__).parent

def _try_load_local_pipeline():
    try:
        if str(TS_LOCAL) not in sys.path:
            sys.path.insert(0, str(TS_LOCAL))
        from literal_protector import protect_literals, restore_literals
        from preparser import preparse
        return protect_literals, restore_literals, preparse
    except Exception:
        return None, None, None

_protect_literals, _restore_literals, _preparse = _try_load_local_pipeline()
LOCAL_PIPELINE_AVAILABLE = _protect_literals is not None

# Markdown / artifact cleanup patterns
_MD_PATTERNS = [
    (re.compile(r'^#{1,6}\s*', re.MULTILINE), ''),
    (re.compile(r'\*{1,3}([^*\n]+)\*{1,3}'), r'\1'),
    (re.compile(r'^>\s?', re.MULTILINE), ''),
    (re.compile(r'^-{3,}\s*$', re.MULTILINE), ''),
    (re.compile(r'^\|.*\|.*$', re.MULTILINE), ''),
    (re.compile(r'[┌┐└┘├┤┬┴┼─│╔╗╚╝╠╣╦╩╬═║]+'), ' '),
    (re.compile(r'`{1,3}[^`\n]*`{1,3}'), ''),
    (re.compile(r'\n{3,}'), '\n\n'),
]

_CAMEL_RE = re.compile(r'([a-z])([A-Z])')


def organizer_prepass(text: str):
    """Pre-process text before API call. Returns (cleaned_text, warnings)."""
    warnings = []
    original_len = len(text)

    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)

    stripped = original_len - len(text)
    if stripped > 20:
        warnings.append(f"Stripped ~{stripped} chars of markdown artifacts")

    camel_count = len(_CAMEL_RE.findall(text))
    text = _CAMEL_RE.sub(r'\1 \2', text)
    if camel_count:
        warnings.append(f"Split {camel_count} camelCase token(s)")

    if LOCAL_PIPELINE_AVAILABLE:
        try:
            protected, lit_map = _protect_literals(text)
            preparsed = _preparse(protected)
            text = preparsed
            warnings.append("Local preparser applied (glue words protected)")
        except Exception as e:
            warnings.append(f"Local preparser skipped: {e}")

    return text.strip(), warnings


def post_compression_score(original: str, compressed: str, mode: str, warnings: list) -> dict:
    """Quick quality/readability score after compression."""
    md_artifacts = sum(1 for p, _ in _MD_PATTERNS[:5] if p.search(compressed))
    tion_raw  = len(re.findall(r'(?:tion|sion|cion)(?:\b|\.)', compressed))
    tion_op   = len(re.findall(r'\u22c8', compressed))   # Unicode join operator
    tion_mixed = tion_raw > 0 and tion_op > 0
    orig_len = len(original)
    comp_len = len(compressed)
    ratio    = round((1 - comp_len / orig_len) * 100, 1) if orig_len else 0
    memory_safe = (md_artifacts == 0 and not tion_mixed and mode == "conservative")
    return {
        "compression_ratio": ratio,
        "md_artifacts":      md_artifacts,
        "tion_mixed":        tion_mixed,
        "tion_raw_count":    tion_raw,
        "tion_op_count":     tion_op,
        "archive_pass":      ratio > 5,
        "memory_safe":       memory_safe,
        "prepass_warnings":  warnings,
        "mode":              mode,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APP_VERSION = "0.2.3"
CONFIG_DIR  = Path.home() / ".thoughtstream"
CONFIG_FILE = CONFIG_DIR / "config.json"
USAGE_FILE  = CONFIG_DIR / "usage.json"

DEFAULT_CONFIG = {
    "api_key":       "",
    "api_endpoint":  "https://api.soultechlabs.net",
    "memory_folder": "",
    "default_mode":  "balanced",
}

DEFAULT_USAGE = {
    "total_requests":        0,
    "total_chars_in":        0,
    "total_chars_out":       0,
    "total_saved":           0,
    "total_tokens_in":       0,
    "total_tokens_out":      0,
    "token_limit":           100000,
    "skip_replace_warning":  False,
}

CHARS_PER_TOKEN = 4

# Plan -> token limit map (tokens = server chars / 4)
# Server tracks characters: Basic=900k, Plus=1.6M, Pro=4M chars
# Hub tracks tokens (chars / 4), so divide accordingly
PLAN_LIMITS = {
    "Basic":   225000,   # 900,000 chars / 4
    "Plus":    400000,   # 1,600,000 chars / 4
    "Pro":    1000000,   # 4,000,000 chars / 4
}

# Mode labels
MODE_LABELS = [
    "Conservative  --  human-readable, light operators",
    "Balanced       --  AI-native, hybrid kernel",
    "Aggressive     --  deep compression, experimental",
]
MODE_API = {
    MODE_LABELS[0]: "conservative",
    MODE_LABELS[1]: "balanced",
    MODE_LABELS[2]: "balanced",   # Aggressive not yet available -- maps to balanced
}
# Manual map: "balanced" -> Balanced label (not Aggressive, which also maps to balanced)
MODE_FROM_API = {
    "conservative": MODE_LABELS[0],
    "balanced":     MODE_LABELS[1],
    "aggressive":   MODE_LABELS[2],
}

MODE_REPLACE_STYLE = {
    "conservative": ("#1f6a1f", "#155015",
                     "Safe to replace memory files."),
    "balanced":     ("#7a5500", "#5c3f00",
                     "AI-readable. Review output before replacing."),
    "aggressive":   ("#7a1f1f", "#5c1818",
                     "Experimental -- archive only. Do not replace memory."),
}


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def load_config():
    CONFIG_DIR.mkdir(exist_ok=True)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = v
        return cfg
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_usage():
    CONFIG_DIR.mkdir(exist_ok=True)
    if USAGE_FILE.exists():
        with open(USAGE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_USAGE.copy()


def save_usage(usage):
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(usage, f, indent=2)


def ensure_memory_folders(base):
    base = Path(base)
    # kernels/ organized/ batch_summaries/ removed -- blooms/ is the single output folder
    for sub in ["raw_backup", "blooms", "reports"]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def parse_ratio(val):
    if isinstance(val, str):
        return float(val.replace("%", "").strip())
    return float(val) if val else 0.0


def compress_text(api_key, endpoint, text, mode="balanced", run_organizer=False):
    url     = f"{endpoint}/api/v1/compress"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    payload = {"text": text, "mode": mode, "run_organizer": run_organizer}
    resp    = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    r = resp.json()
    if "kernel" in r and "compressed" not in r:
        r["compressed"] = r["kernel"]
    return r


def detect_already_compressed(text: str) -> bool:
    """
    Heuristic: if text has high TS operator density it's likely already a bloom.
    Checks for common TS operators: . chains, single-word dot patterns, TS shorthand.
    """
    if not text or len(text) < 100:
        return False
    # Count dot-joined word patterns (e.g. "word.word.word")
    dot_chains = re.findall(r'\b\w+\.\w+(?:\.\w+)+', text)
    # Count TS shorthand patterns (e.g. "cre.8", "ilmn.8", "acr.8")
    ts_shortcuts = re.findall(r'\b\w{2,6}\.\d\b', text)
    # Ratio of dots-as-connectors vs text length
    total_signals = len(dot_chains) + len(ts_shortcuts) * 2
    density = total_signals / (len(text) / 100)
    return density > 1.5   # threshold tuned to catch blooms, not normal prose


def chunk_and_compress(api_key, endpoint, text, mode="balanced", chunk_size=3000, run_organizer=False):
    if len(text) <= chunk_size:
        r = compress_text(api_key, endpoint, text, mode, run_organizer=run_organizer)
        r.setdefault("chunks", 1)
        r["compression_ratio"] = parse_ratio(r.get("compression_ratio", 0))
        return r

    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    parts, total_in, total_out = [], 0, 0
    for chunk in chunks:
        r = compress_text(api_key, endpoint, chunk, mode, run_organizer=run_organizer)
        parts.append(r.get("compressed", chunk))
        total_in  += len(chunk)
        total_out += len(r.get("compressed", chunk))

    combined = "\n".join(parts)
    ratio    = round((1 - total_out / total_in) * 100, 1) if total_in else 0
    return {
        "compressed":        combined,
        "original_length":   total_in,
        "compressed_length": total_out,
        "compression_ratio": ratio,
        "chunks":            len(chunks),
    }


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ThoughtStreamHub(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title(f"ThoughtStream Hub  v{APP_VERSION}")
        self.geometry("1380x1200")
        self.minsize(1100, 900)

        self.cfg   = load_config()
        self.usage = load_usage()

        self.current_file        = None
        self.current_original    = None
        self.current_compressed  = None
        self.current_result      = None
        self.current_score       = None
        self.batch_folder        = None
        self.last_registered_hash = None   # dedup: only count usage once per unique file+content
        self._settings_dirty     = False   # unsaved changes flag

        self._build_ui()

    # -----------------------------------------------------------------------
    # UI scaffold
    # -----------------------------------------------------------------------
    def _build_ui(self):
        hdr = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color="#1a1a2e")
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="ThoughtStream Hub",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#6eb5ff").pack(side="left", padx=20, pady=14)

        self.lbl_status = ctk.CTkLabel(hdr, text="Not connected",
                                        text_color="#666666",
                                        font=ctk.CTkFont(size=12))
        self.lbl_status.pack(side="right", padx=20)
        ctk.CTkLabel(hdr, text=f"v{APP_VERSION}",
                     text_color="#444466", font=ctk.CTkFont(size=11)).pack(side="right")

        lbl_site = ctk.CTkLabel(hdr, text="soultechlabs.net",
                                 text_color="#6eb5ff",
                                 font=ctk.CTkFont(size=12, underline=True),
                                 cursor="hand2")
        lbl_site.pack(side="right", padx=(0, 16))
        lbl_site.bind("<Button-1>", lambda e: webbrowser.open("https://soultechlabs.net"))

        self.tabs = ctk.CTkTabview(self, corner_radius=8)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(8, 14))

        for name in ["Settings", "Connect", "Convert", "Batch", "Usage"]:
            self.tabs.add(name)

        self.tabs.configure(command=self._on_tab_change)
        self._build_settings()
        self._build_connect()
        self._build_convert()
        self._build_batch()
        self._build_usage()

        self.tabs.set("Settings" if not self.cfg.get("api_key") else "Convert")

    # -----------------------------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------------------------
    def _build_settings(self):
        t = self.tabs.tab("Settings")
        s = ctk.CTkScrollableFrame(t)
        s.pack(fill="both", expand=True, padx=8, pady=8)

        def section(text):
            ctk.CTkLabel(s, text=text,
                         font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", pady=(16, 4))

        def hint(text, color="#888888"):
            ctk.CTkLabel(s, text=text, text_color=color,
                         font=ctk.CTkFont(size=12)).pack(anchor="w")

        section("API Configuration")
        hint("API Key  (paste with Ctrl+V or right-click)")
        self.e_apikey = ctk.CTkEntry(s, width=520, show="*",
                                      placeholder_text="Paste your API key here (Ctrl+V)...")
        self.e_apikey.pack(anchor="w", pady=(2, 10))
        self.e_apikey.bind("<Button-3>", lambda e: self.e_apikey.event_generate("<<Paste>>"))
        self.e_apikey.bind("<KeyRelease>", lambda e: self._mark_settings_dirty())
        if self.cfg.get("api_key"):
            self.e_apikey.insert(0, self.cfg["api_key"])

        hint("API Endpoint")
        self.e_endpoint = ctk.CTkEntry(s, width=520,
                                        placeholder_text="https://api.soultechlabs.net")
        self.e_endpoint.pack(anchor="w", pady=(2, 10))
        self.e_endpoint.insert(0, self.cfg.get("api_endpoint", "https://api.soultechlabs.net"))
        self.e_endpoint.bind("<KeyRelease>", lambda e: self._mark_settings_dirty())

        hint("Default Compression Mode")
        self.om_mode = ctk.CTkOptionMenu(s, values=MODE_LABELS, width=500)
        self.om_mode.pack(anchor="w", pady=(2, 4))
        self.om_mode.set(MODE_FROM_API.get(self.cfg.get("default_mode", "balanced"), MODE_LABELS[1]))
        hint("Conservative = human memory  |  Balanced = AI kernel  |  Aggressive = coming soon (runs as Balanced)")

        section("Memory Folder")
        hint("Where Hub saves conversions, backups, and reports.")
        row = ctk.CTkFrame(s, fg_color="transparent")
        row.pack(anchor="w", fill="x", pady=(6, 4))
        self.e_folder = ctk.CTkEntry(row, width=420, placeholder_text="Choose a folder...")
        self.e_folder.pack(side="left", padx=(0, 10))
        if self.cfg.get("memory_folder"):
            self.e_folder.insert(0, self.cfg["memory_folder"])
        self.e_folder.bind("<KeyRelease>", lambda e: self._mark_settings_dirty())
        ctk.CTkButton(row, text="Browse...", width=100,
                      command=self._browse_folder).pack(side="left")
        hint("Subfolders created automatically: raw_backup/  blooms/  reports/")

        btn_row_s = ctk.CTkFrame(s, fg_color="transparent")
        btn_row_s.pack(anchor="w", pady=(20, 4))
        ctk.CTkButton(btn_row_s, text="Save Settings", width=160, fg_color="#1f6aa5",
                      command=self._save_settings).pack(side="left", padx=(0, 16))
        ctk.CTkButton(btn_row_s, text="Re-enable Replace Warning", width=200,
                      fg_color="#3a3a3a",
                      command=self._reenable_replace_warning).pack(side="left")
        self.lbl_settings_dirty = ctk.CTkLabel(s, text="",
                                                text_color="#ff9800",
                                                font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_settings_dirty.pack(anchor="w", pady=(4, 0))
        self.lbl_settings_ok = ctk.CTkLabel(s, text="", text_color="#4caf50")
        self.lbl_settings_ok.pack(anchor="w")

    def _reenable_replace_warning(self):
        self.usage["skip_replace_warning"] = False
        save_usage(self.usage)
        self.lbl_settings_ok.configure(text="Replace warning re-enabled.")
        self.after(3000, lambda: self.lbl_settings_ok.configure(text=""))

    def _on_tab_change(self):
        if self._settings_dirty and self.tabs.get() != "Settings":
            messagebox.showwarning(
                "Unsaved Settings",
                "You have unsaved changes in Settings.\n\n"
                "Go back to Settings and click Save Settings, or your changes won't take effect."
            )

    def _mark_settings_dirty(self):
        self._settings_dirty = True
        self.lbl_settings_dirty.configure(text="⚠ Unsaved changes — click Save Settings!")

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Choose Memory Folder")
        if d:
            self.e_folder.delete(0, "end")
            self.e_folder.insert(0, d)
            self._mark_settings_dirty()

    def _save_settings(self):
        self.cfg["api_key"]       = self.e_apikey.get().strip()
        self.cfg["api_endpoint"]  = self.e_endpoint.get().strip()
        self.cfg["default_mode"]  = MODE_API.get(self.om_mode.get(), "balanced")
        self.cfg["memory_folder"] = self.e_folder.get().strip()
        if self.cfg["memory_folder"]:
            ensure_memory_folders(self.cfg["memory_folder"])
        save_config(self.cfg)
        self._settings_dirty = False
        self.lbl_settings_dirty.configure(text="")
        self.lbl_settings_ok.configure(text="Settings saved.")
        self.after(3000, lambda: self.lbl_settings_ok.configure(text=""))

    # -----------------------------------------------------------------------
    # CONNECT
    # -----------------------------------------------------------------------
    def _build_connect(self):
        t = self.tabs.tab("Connect")
        f = ctk.CTkFrame(t)
        f.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(f, text="API Connection Test",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(20, 4))
        ctk.CTkLabel(f, text="Verify your key and see live API stats.",
                     text_color="#888888").pack(pady=(0, 16))

        self.tb_connect = ctk.CTkTextbox(f, height=220, width=580,
                                          font=ctk.CTkFont(family="Courier New", size=12),
                                          state="disabled")
        self.tb_connect.pack(pady=8)

        ctk.CTkButton(f, text="Test Connection", width=180, fg_color="#1f6aa5",
                      command=self._test_connection).pack(pady=10)

        self.lbl_connect = ctk.CTkLabel(f, text="", font=ctk.CTkFont(size=13))
        self.lbl_connect.pack(pady=4)

    def _test_connection(self):
        key = self.cfg.get("api_key", "")
        ep  = self.cfg.get("api_endpoint", "https://api.soultechlabs.net")
        if not key:
            self.lbl_connect.configure(text="No API key -- go to Settings first.",
                                        text_color="#ff9800")
            return
        self.lbl_connect.configure(text="Testing...", text_color="#888888")

        def run():
            try:
                h = requests.get(f"{ep}/api/v1/health",
                                  headers={"X-API-Key": key}, timeout=10).json()
                s = requests.get(f"{ep}/api/v1/stats",
                                  headers={"X-API-Key": key}, timeout=10).json()
                info = (
                    f"  Status:           {h.get('status','?').upper()}\n"
                    f"  API Version:      {h.get('version','?')}\n"
                    f"  Provider:         {h.get('provider','?')}\n"
                    f"  Endpoint:         {ep}\n\n"
                    f"  Vocabulary:\n"
                    f"    Phono entries:    {s.get('phono_entries',0):,}\n"
                    f"    Semantic entries: {s.get('semantic_entries',0):,}\n\n"
                    f"  Timestamp:        {h.get('timestamp','?')}"
                )
                self._set_tb(self.tb_connect, info)
                self.lbl_connect.configure(text="Connected", text_color="#4caf50")
                self.lbl_status.configure(text="Connected",  text_color="#4caf50")
            except Exception as e:
                self._set_tb(self.tb_connect, f"  ERROR: {e}")
                self.lbl_connect.configure(text="Connection failed", text_color="#f44336")
                self.lbl_status.configure(text="Not connected",      text_color="#666666")

        threading.Thread(target=run, daemon=True).start()

    # -----------------------------------------------------------------------
    # CONVERT
    # -----------------------------------------------------------------------
    def _build_convert(self):
        t = self.tabs.tab("Convert")

        # Left panel -- scrollable so nothing gets clipped at any window size
        left_outer = ctk.CTkFrame(t, width=360)
        left_outer.pack(side="left", fill="y", padx=(8, 4), pady=8)
        left_outer.pack_propagate(False)
        left = ctk.CTkScrollableFrame(left_outer, width=340, fg_color="transparent")
        left.pack(fill="both", expand=True)

        ctk.CTkLabel(left, text="Convert File",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 8), padx=14, anchor="w")

        ctk.CTkButton(left, text="Select File", width=255,
                      command=self._conv_select).pack(padx=14, pady=4)

        self.lbl_conv_file = ctk.CTkLabel(left, text="No file selected",
                                           text_color="#666666",
                                           font=ctk.CTkFont(size=11), wraplength=300)
        self.lbl_conv_file.pack(padx=14, pady=4)

        ctk.CTkFrame(left, height=1, fg_color="#2a2a2a").pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(left, text="Compression Mode",
                     font=ctk.CTkFont(size=12)).pack(padx=14, anchor="w")
        self.om_conv_mode = ctk.CTkOptionMenu(left, values=MODE_LABELS, width=260,
                                               command=self._conv_mode_changed)
        self.om_conv_mode.pack(padx=14, pady=(4, 4))
        self.om_conv_mode.set(MODE_FROM_API.get(self.cfg.get("default_mode","balanced"), MODE_LABELS[1]))

        self.lbl_mode_hint = ctk.CTkLabel(left, text="", text_color="#888888",
                                           font=ctk.CTkFont(size=10), wraplength=300)
        self.lbl_mode_hint.pack(padx=14, anchor="w", pady=(0, 6))

        # ── Option checkboxes ────────────────────────────────────────────
        def _make_cb_row(parent, cb_attr, text, hint_text, hint_color, default_on=False):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=(2, 0))
            cb = ctk.CTkCheckBox(row, text=text, font=ctk.CTkFont(size=12))
            cb.pack(anchor="w")
            if default_on:
                cb.select()
            setattr(self, cb_attr, cb)
            ctk.CTkLabel(row, text=hint_text, text_color=hint_color,
                         font=ctk.CTkFont(size=10), wraplength=290).pack(anchor="w", padx=24)

        opt_frame = ctk.CTkFrame(left, fg_color="transparent")
        opt_frame.pack(padx=14, anchor="w", pady=(0, 6))

        _make_cb_row(opt_frame, "cb_organizer",
                     "Run Organizer first",
                     "Structures messy text for better compression.",
                     "#4caf50" if LOCAL_PIPELINE_AVAILABLE else "#ff9800",
                     default_on=True)

        _make_cb_row(opt_frame, "cb_save_original",
                     "Save Original in ThoughtStream",
                     "Creates a copy of the original file in raw_backup/ before any changes.",
                     "#6eb5ff",
                     default_on=True)

        _make_cb_row(opt_frame, "cb_replace_original",
                     "Replace Original File Location",
                     "Overwrites the source file with the Bloom.\n⚠ High risk — Backup recommended.",
                     "#ff9800",
                     default_on=False)

        btn_run_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_run_row.pack(padx=14, pady=(6, 2), fill="x")
        ctk.CTkButton(btn_run_row, text="Run Compression", width=180, fg_color="#2d7a2d",
                      command=self._conv_preview).pack(side="left", padx=(0, 8))
        self.btn_stop = ctk.CTkButton(btn_run_row, text="Stop", width=65,
                                      fg_color="#7a1f1f", hover_color="#5c1818",
                                      command=self._conv_stop)
        self.btn_stop.pack(side="left")
        ctk.CTkLabel(left, text="Uses compression credits. Output shown before saving.",
                     text_color="#666666", font=ctk.CTkFont(size=10),
                     wraplength=300).pack(padx=14, anchor="w", pady=(0, 4))

        ctk.CTkFrame(left, height=1, fg_color="#2a2a2a").pack(fill="x", padx=14, pady=8)

        # Stats
        ctk.CTkLabel(left, text="Results",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(padx=14, anchor="w")
        self.tb_conv_stats = ctk.CTkTextbox(left, height=160,
                                             font=ctk.CTkFont(family="Courier New", size=11),
                                             state="disabled")
        self.tb_conv_stats.pack(padx=14, pady=4, fill="x")

        self.lbl_tokens_consumed = ctk.CTkLabel(left, text="",
                                                 text_color="#6eb5ff",
                                                 font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_tokens_consumed.pack(padx=14, anchor="w", pady=(0, 2))

        ctk.CTkFrame(left, height=1, fg_color="#2a2a2a").pack(fill="x", padx=14, pady=6)

        # Quality card
        ctk.CTkLabel(left, text="Quality Score",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(padx=14, anchor="w")
        self.tb_quality = ctk.CTkTextbox(left, height=110,
                                          font=ctk.CTkFont(family="Courier New", size=10),
                                          state="disabled")
        self.tb_quality.pack(padx=14, pady=(4, 6), fill="x")

        ctk.CTkFrame(left, height=1, fg_color="#2a2a2a").pack(fill="x", padx=14, pady=6)

        self.btn_replace = ctk.CTkButton(left, text="Replace Memory With Bloom", width=255,
                                          fg_color="#7a1f1f", hover_color="#5c1818",
                                          command=self._conv_replace)
        self.btn_replace.pack(padx=14, pady=(4, 2))

        self.lbl_replace_hint = ctk.CTkLabel(left, text="Original backed up automatically.",
                                              text_color="#666666",
                                              font=ctk.CTkFont(size=10), wraplength=300)
        self.lbl_replace_hint.pack(padx=14, anchor="w", pady=(0, 4))

        self.lbl_conv_action = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11),
                                             text_color="#4caf50")
        self.lbl_conv_action.pack(padx=14, pady=2)

        self.lbl_preview_badge = ctk.CTkLabel(left,
                                               text="Compression ready -- no files changed yet",
                                               text_color="#555577",
                                               font=ctk.CTkFont(size=10))
        self.lbl_preview_badge.pack(padx=14, pady=(0, 8), anchor="w")

        # Right preview panel
        right = ctk.CTkFrame(t)
        right.pack(side="right", fill="both", expand=True, padx=(4, 8), pady=8)

        ctk.CTkLabel(right, text="Preview",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 4), padx=14, anchor="w")

        toggle = ctk.CTkFrame(right, fg_color="transparent")
        toggle.pack(fill="x", padx=14, pady=4)
        self.pv_var = ctk.StringVar(value="compressed")
        ctk.CTkRadioButton(toggle, text="Compressed", variable=self.pv_var,
                           value="compressed", command=self._pv_update).pack(side="left", padx=(0, 16))
        ctk.CTkRadioButton(toggle, text="Original",   variable=self.pv_var,
                           value="original",   command=self._pv_update).pack(side="left")

        clip_row = ctk.CTkFrame(right, fg_color="transparent")
        clip_row.pack(fill="x", padx=14, pady=(4, 0))
        ctk.CTkButton(clip_row, text="Copy Output", width=130, height=28,
                      font=ctk.CTkFont(size=12),
                      command=self._pv_copy).pack(side="left", padx=(0, 10))
        ctk.CTkButton(clip_row, text="Paste as Input", width=140, height=28,
                      font=ctk.CTkFont(size=12), fg_color="#2d4a6e",
                      command=self._pv_paste).pack(side="left", padx=(0, 10))
        self.lbl_clip = ctk.CTkLabel(clip_row, text="", text_color="#4caf50",
                                      font=ctk.CTkFont(size=11))
        self.lbl_clip.pack(side="left")

        # Disclaimer banner
        disc = ctk.CTkFrame(right, fg_color="#2a1a00", corner_radius=6)
        disc.pack(fill="x", padx=14, pady=(6, 0))
        ctk.CTkLabel(
            disc,
            text="⚠️  Compression consumes tokens quickly. Each run counts against your plan limit. "
                 "Review your content before compressing. Keep an eye on your Usage tab.",
            text_color="#ffaa33",
            font=ctk.CTkFont(size=11),
            wraplength=680,
            justify="left",
        ).pack(padx=12, pady=6, anchor="w")

        self.tb_preview = ctk.CTkTextbox(right, font=ctk.CTkFont(family="Courier New", size=11))
        self.tb_preview.pack(fill="both", expand=True, padx=14, pady=(4, 4))
        self._set_tb(self.tb_preview, "Select a file, paste text, or type directly here — then click Run Compression.")
        # Make preview editable so users can type/paste directly
        self.tb_preview.configure(state="normal")

        clear_row = ctk.CTkFrame(right, fg_color="transparent")
        clear_row.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkButton(clear_row, text="Clear", width=80, height=26,
                      fg_color="#4a2a2a", hover_color="#6a1a1a",
                      font=ctk.CTkFont(size=11),
                      command=self._conv_clear).pack(side="left")
        ctk.CTkLabel(clear_row, text="Clears preview and resets current file.",
                     text_color="#666666", font=ctk.CTkFont(size=10)).pack(side="left", padx=8)

        # Init mode hint
        self._conv_mode_changed(self.om_conv_mode.get())

    def _conv_mode_changed(self, label):
        api_mode = MODE_API.get(label, "balanced")
        # Determine display mode for hints (aggressive shows as balanced + coming soon note)
        display_mode = api_mode
        hints = {
            "conservative": "Safe for memory replacement. Preserves readability.",
            "balanced":     "AI-native kernel. Review before replacing live memory.",
            "aggressive":   "Coming soon — currently runs as Balanced mode.",
        }
        colors = {
            "conservative": "#4caf50",
            "balanced":     "#ff9800",
            "aggressive":   "#888888",
        }
        self.lbl_mode_hint.configure(text=hints.get(api_mode, ""),
                                      text_color=colors.get(api_mode, "#888888"))
        # Aggressive maps to balanced for replace style (not yet available)
        style_key = "balanced" if api_mode == "aggressive" else api_mode
        style = MODE_REPLACE_STYLE.get(style_key, MODE_REPLACE_STYLE["balanced"])
        self.btn_replace.configure(fg_color=style[0], hover_color=style[1])
        self.lbl_replace_hint.configure(text=style[2])

    def _conv_select(self):
        if self.current_compressed and self.current_file and not getattr(self, '_bloom_was_replaced', False):
            choice = messagebox.askyesnocancel(
                "Unsaved Bloom",
                "You have an unsaved Bloom from the current file.\n\n"
                "Yes = discard it and open a new file.\n"
                "No = go back and use Replace Memory first.\n"
                "Cancel = do nothing.",
            )
            if choice is None or choice is False:
                return
        p = filedialog.askopenfilename(
            title="Select file to compress",
            filetypes=[("Text files", "*.txt *.md *.json"), ("All files", "*.*")]
        )
        if p:
            self.current_file         = p
            self.current_original     = None
            self.current_compressed   = None
            self.current_result       = None
            self.current_score        = None
            self.last_registered_hash = None
            self._bloom_was_replaced  = False
            self.lbl_conv_file.configure(text=os.path.basename(p), text_color="#cccccc")
            self._set_tb(self.tb_preview, f"Ready: {os.path.basename(p)}\n\nClick Run Compression to compress.")
            self._set_tb(self.tb_conv_stats, "")
            self._set_tb(self.tb_quality, "")

    def _conv_preview(self):
        if not self.current_file:
            messagebox.showwarning("No file", "Select a file first.")
            return
        key = self.cfg.get("api_key", "")
        if not key:
            messagebox.showwarning("No API key", "Set your API key in Settings.")
            return
        self._set_tb(self.tb_preview, "Running...")
        self._set_tb(self.tb_conv_stats, "Running...")
        self._set_tb(self.tb_quality, "")
        self.lbl_conv_action.configure(text="")

        def run():
            try:
                with open(self.current_file, "r", encoding="utf-8", errors="replace") as f:
                    raw_text = f.read()
                self.current_original = raw_text

                ep         = self.cfg.get("api_endpoint", "https://api.soultechlabs.net")
                mode_label = self.om_conv_mode.get()
                mode       = MODE_API.get(mode_label, "balanced")

                # ── Double-compression guard ──────────────────────────────
                if detect_already_compressed(raw_text):
                    proceed = messagebox.askyesno(
                        "Already Compressed?",
                        "This text appears to already be a ThoughtStream Bloom.\n\n"
                        "Re-compressing a bloom can reduce readability and introduce artifacts.\n"
                        "ThoughtStream may start treating its own operators as source material.\n\n"
                        "Recommended: use the original source or organized text instead.\n\n"
                        "Continue anyway?",
                    )
                    if not proceed:
                        self.after(0, lambda: self.lbl_conv_action.configure(
                            text="Compression cancelled — already-compressed input detected.",
                            text_color="#ff9800"))
                        return

                # Organizer pre-pass — server-side when toggled
                use_organizer    = bool(self.cb_organizer.get())
                prepass_warnings = []

                if use_organizer:
                    self.after(0, lambda: self.lbl_conv_action.configure(
                        text="Organizer + Compressing...", text_color="#888888"))
                else:
                    self.after(0, lambda: self.lbl_conv_action.configure(
                        text="Compressing...", text_color="#888888"))

                r = chunk_and_compress(key, ep, raw_text, mode,
                                       run_organizer=use_organizer)
                prepass_warnings = r.get("organizer_warnings", [])

                self.current_compressed = r.get("compressed", "")
                self.current_result     = r

                orig  = len(raw_text)
                comp  = len(self.current_compressed)
                pct   = round((1 - comp / orig) * 100, 1) if orig else 0
                saved = orig - comp
                tok_in    = orig  // CHARS_PER_TOKEN
                tok_out   = comp  // CHARS_PER_TOKEN
                tok_saved = tok_in - tok_out

                stats = (
                    f"  Original:    {orig:,} chars  (~{tok_in:,} tokens)\n"
                    f"  Compressed:  {comp:,} chars  (~{tok_out:,} tokens)\n"
                    f"  Saved:       {saved:,} chars  (~{tok_saved:,} tokens)\n"
                    f"  Ratio:       {pct}%\n"
                    f"  Chunks:      {r.get('chunks', 1)}\n"
                    f"  Mode:        {mode}"
                )
                self._set_tb(self.tb_conv_stats, stats)

                # Tokens consumed flash indicator (thread-safe via after())
                tok_snap = tok_in
                self.after(0, lambda t=tok_snap: self._flash_tokens_consumed(t))

                # Quality score
                score = post_compression_score(raw_text, self.current_compressed,
                                               mode, prepass_warnings)
                self.current_score = score

                archive_verdict  = "PASS" if score["archive_pass"]  else "FAIL"
                memory_verdict   = "SAFE" if score["memory_safe"]   else "HOLD"
                md_note          = f"{score['md_artifacts']} found" if score["md_artifacts"] else "none"
                tion_note        = "mixed (review)" if score["tion_mixed"] else "consistent"
                warn_lines       = "\n  ".join(prepass_warnings) if prepass_warnings else "none"

                quality_text = (
                    f"  Deep archive:     {archive_verdict}\n"
                    f"  Memory replace:   {memory_verdict}\n"
                    f"  MD artifacts:     {md_note}\n"
                    f"  Operator consis.: {tion_note}\n"
                    f"  Prepass notes:\n"
                    f"  {warn_lines}"
                )
                self._set_tb(self.tb_quality, quality_text)
                self._pv_update()
                self.after(0, lambda: self.lbl_conv_action.configure(
                    text="Preview ready", text_color="#4caf50"))

                # Log usage — dedup: only count once per unique file + content
                content_hash = hashlib.md5(
                    (str(self.current_file) + raw_text).encode("utf-8")
                ).hexdigest()
                # Dedup: only count chars/requests once per unique file+content
                if content_hash != self.last_registered_hash:
                    self.last_registered_hash = content_hash
                    self.usage["total_requests"]  = self.usage.get("total_requests",  0) + r.get("chunks", 1)
                    self.usage["total_chars_in"]  = self.usage.get("total_chars_in",  0) + orig
                    self.usage["total_chars_out"] = self.usage.get("total_chars_out", 0) + comp
                    self.usage["total_saved"]     = self.usage.get("total_saved",     0) + saved
                    self.usage["total_tokens_in"]  = self.usage.get("total_tokens_in",  0) + tok_in
                    self.usage["total_tokens_out"] = self.usage.get("total_tokens_out", 0) + tok_out
                save_usage(self.usage)
                self.after(0, self._usage_refresh)  # auto-update Usage tab

            except requests.exceptions.HTTPError as http_err:
                status = http_err.response.status_code if http_err.response is not None else 0
                if status == 402:
                    try:
                        detail    = http_err.response.json().get("detail", {})
                        remaining = detail.get("remaining_credits", 0)
                        required  = detail.get("required_credits", 0)
                        msg = (f"Compression limit reached.\n\n"
                               f"Credits remaining: {remaining:,} chars\n"
                               f"Credits needed:    {required:,} chars\n\n"
                               f"Upgrade your plan at soultechlabs.net\n\n"
                               f"Original file was not changed.")
                    except Exception:
                        msg = "Compression limit reached.\nUpgrade your plan at soultechlabs.net\n\nOriginal file was not changed."
                    self._set_tb(self.tb_preview, msg)
                    self._set_tb(self.tb_conv_stats, "LIMIT REACHED")
                    self.after(0, lambda: self.lbl_conv_action.configure(
                        text="Credit limit reached", text_color="#f44336"))
                else:
                    self._set_tb(self.tb_preview, f"API Error {status}:\n{http_err}")
                    self._set_tb(self.tb_conv_stats, f"Error:\n{http_err}")
                    self.after(0, lambda: self.lbl_conv_action.configure(
                        text="Error", text_color="#f44336"))
            except Exception as e:
                self._set_tb(self.tb_preview, f"Error:\n{e}")
                self._set_tb(self.tb_conv_stats, f"Error:\n{e}")
                self.after(0, lambda: self.lbl_conv_action.configure(
                    text="Error", text_color="#f44336"))

        self._stop_requested = False
        threading.Thread(target=run, daemon=True).start()

    def _conv_clear(self):
        if not messagebox.askyesno("Clear Preview", "Clear the preview and reset the current file?\n\nAny unsaved bloom will be lost."):
            return
        self.current_file        = None
        self.current_original    = None
        self.current_compressed  = None
        self.current_result      = None
        self.current_score       = None
        self.last_registered_hash = None
        self._bloom_was_replaced  = False
        self.lbl_conv_file.configure(text="No file selected", text_color="#666666")
        self.lbl_conv_action.configure(text="")
        self.lbl_preview_badge.configure(text="Compression ready -- no files changed yet", text_color="#555577")
        self.lbl_tokens_consumed.configure(text="")
        self._set_tb(self.tb_conv_stats, "")
        self._set_tb(self.tb_quality, "")
        self.tb_preview.configure(state="normal")
        self.tb_preview.delete("1.0", "end")
        self.tb_preview.insert("1.0", "Select a file, paste text, or type directly here — then click Run Compression.")

    def _flash_tokens_consumed(self, token_count: int):
        """Show 'Tokens Consumed: X' then fade after 15 seconds."""
        self.lbl_tokens_consumed.configure(
            text=f"Tokens Consumed: {token_count:,}",
            text_color="#6eb5ff",
        )
        self.after(15000, lambda: self.lbl_tokens_consumed.configure(text=""))

    def _conv_stop(self):
        self._stop_requested = True
        self.lbl_conv_action.configure(text="Stopping...", text_color="#ff9800")

    def _pv_update(self):
        mode = self.pv_var.get()
        src  = self.current_original if mode == "original" else self.current_compressed
        if not src:
            return
        truncated = src[:6000] + ("\n\n[ Showing first 6,000 chars. Use Replace Memory to save the full Bloom. ]" if len(src) > 6000 else "")
        self._set_tb(self.tb_preview, truncated)

    def _pv_copy(self):
        text = self.tb_preview.get("1.0", "end").strip()
        if not text or text.startswith("Select a file"):
            self.lbl_clip.configure(text="Nothing to copy", text_color="#ff9800")
            self.after(2500, lambda: self.lbl_clip.configure(text=""))
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_clip.configure(text="Copied!", text_color="#4caf50")
        self.after(2500, lambda: self.lbl_clip.configure(text=""))

    def _pv_paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            text = ""
        if not text:
            self.lbl_clip.configure(text="Clipboard empty", text_color="#ff9800")
            self.after(2500, lambda: self.lbl_clip.configure(text=""))
            return

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
            encoding="utf-8", prefix="ts_paste_"
        )
        tmp.write(text)
        tmp.close()

        self.current_file        = tmp.name
        self.current_original    = text
        self.current_compressed  = None
        self.current_result      = None
        self.current_score       = None
        self.lbl_conv_file.configure(text="[pasted text]", text_color="#6eb5ff")
        self._set_tb(self.tb_preview, text)
        self.pv_var.set("original")
        self.lbl_clip.configure(
            text=f"{len(text):,} chars pasted -- click Run Preview",
            text_color="#4caf50"
        )
        self.after(4000, lambda: self.lbl_clip.configure(text=""))

    def _show_replace_dialog(self, title, body, mode_color="#ff9800") -> bool:
        """
        Custom replace confirmation dialog with 'Don't show again' checkbox.
        Returns True if user confirms, False if cancelled.
        Skips entirely if skip_replace_warning is set (except Aggressive block).
        """
        if self.usage.get("skip_replace_warning", False):
            return True

        result = {"ok": False}
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry("480x300")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()

        ctk.CTkLabel(dlg, text=title,
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=mode_color).pack(pady=(20, 8), padx=24, anchor="w")

        ctk.CTkLabel(dlg, text=body,
                     font=ctk.CTkFont(size=12),
                     wraplength=440, justify="left").pack(padx=24, anchor="w")

        cb_skip = ctk.CTkCheckBox(dlg, text="Don't show this warning again",
                                   font=ctk.CTkFont(size=11),
                                   text_color="#888888")
        cb_skip.pack(padx=24, pady=(20, 8), anchor="w")

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=(4, 20))

        def on_confirm():
            if cb_skip.get():
                self.usage["skip_replace_warning"] = True
                save_usage(self.usage)
            result["ok"] = True
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        ctk.CTkButton(btn_row, text="Replace", width=130, fg_color="#1f6a1f",
                      command=on_confirm).pack(side="left", padx=(0, 16))
        ctk.CTkButton(btn_row, text="Cancel",  width=130, fg_color="#3a3a3a",
                      command=on_cancel).pack(side="left")

        dlg.wait_window()
        return result["ok"]

    def _conv_replace(self):
        if not self.current_compressed:
            messagebox.showwarning("No preview", "Run Preview first.")
            return

        score    = self.current_score or {}
        mode     = MODE_API.get(self.om_conv_mode.get(), "balanced")
        mem_safe = score.get("memory_safe", False)

        if mode == "balanced" and not mem_safe:
            ok = self._show_replace_dialog(
                "Quality Score: HOLD",
                f"Balanced mode output is AI-readable but may not be human-walkable.\n\n"
                f"File:  {self.current_file}\n\n"
                f"Original will be backed up to raw_backup/ automatically.\n"
                f"Bloom copy saved to blooms/\n\n"
                f"Review the compressed preview before continuing.",
                mode_color="#ff9800"
            )
            if not ok:
                return
        else:
            ok = self._show_replace_dialog(
                "Replace Memory With Bloom?",
                f"File:  {self.current_file}\n\n"
                f"1. Original backed up to raw_backup/ automatically.\n"
                f"2. Bloom copy saved to blooms/\n"
                f"3. File overwritten with bloom output.\n\n"
                f"ThoughtStream Hub is beta software.\n"
                f"Always review output before relying on it.",
                mode_color="#4caf50"
            )
            if not ok:
                return

        save_original  = bool(self.cb_save_original.get())
        replace_source = bool(self.cb_replace_original.get())

        # Safety: if replacing source without saving original, warn harder
        if replace_source and not save_original:
            go = messagebox.askyesno(
                "No Backup Selected",
                "You have not enabled 'Save Original in ThoughtStream'.\n\n"
                "If you replace the original file, the original may be permanently lost.\n\n"
                "Are you absolutely sure you want to continue without a backup?",
            )
            if not go:
                return

        try:
            fname = os.path.basename(self.current_file)
            mem   = self.cfg.get("memory_folder", "")
            if mem:
                ensure_memory_folders(mem)
                bk_dir    = Path(mem) / "raw_backup"
                bloom_dir = Path(mem) / "blooms"
                rpt_dir   = Path(mem) / "reports"
            else:
                base = Path(self.current_file).parent / "ThoughtStream"
                ensure_memory_folders(base)
                bk_dir    = base / "raw_backup"
                bloom_dir = base / "blooms"
                rpt_dir   = base / "reports"

            ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
            bk_path    = bk_dir    / f"{ts}_{fname}"
            bloom_path = bloom_dir / f"{ts}_{Path(fname).stem}.bloom{Path(fname).suffix}"

            actions = []

            # Save original backup if checked
            if save_original:
                shutil.copy2(self.current_file, bk_path)
                actions.append(f"Backup: {bk_path}")

            # Always save bloom to blooms/
            with open(bloom_path, "w", encoding="utf-8") as f:
                f.write(self.current_compressed)
            actions.append(f"Bloom: {bloom_path}")

            # Overwrite source only if checked
            if replace_source:
                with open(self.current_file, "w", encoding="utf-8") as f:
                    f.write(self.current_compressed)
                actions.append(f"Replaced: {self.current_file}")

            # Save report
            rpt = {
                "file":              self.current_file,
                "backup":            str(bk_path) if save_original else None,
                "bloom":             str(bloom_path),
                "replaced_source":   replace_source,
                "timestamp":         ts,
                "original_length":   len(self.current_original),
                "compressed_length": len(self.current_compressed),
                "mode":              mode,
                "quality_score":     score,
            }
            rpt_path = rpt_dir / f"{ts}_{fname}.report.json"
            with open(rpt_path, "w", encoding="utf-8") as f:
                json.dump(rpt, f, indent=2, ensure_ascii=False)

            self._bloom_was_replaced = True
            summary = "\n".join(actions)
            self.lbl_conv_action.configure(text=f"Done.\n{summary}", text_color="#4caf50")
            self.lbl_preview_badge.configure(text=f"Bloom saved to: {bloom_path}", text_color="#4caf50")

        except Exception as e:
            messagebox.showerror("Error", f"Replace failed:\n{e}")
            self.lbl_conv_action.configure(text="Replace failed", text_color="#f44336")

    # -----------------------------------------------------------------------
    # BATCH
    # -----------------------------------------------------------------------
    def _build_batch(self):
        t = self.tabs.tab("Batch")

        top = ctk.CTkFrame(t, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(10, 4))

        ctk.CTkLabel(top, text="Batch Convert Folder",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=6)
        ctk.CTkButton(top, text="Select Folder", width=150,
                      command=self._batch_browse).pack(side="left", padx=16)
        self.lbl_batch_folder = ctk.CTkLabel(top, text="No folder selected",
                                              text_color="#666666")
        self.lbl_batch_folder.pack(side="left")

        opts = ctk.CTkFrame(t, fg_color="transparent")
        opts.pack(fill="x", padx=8, pady=4)

        ctk.CTkLabel(opts, text="File types:", font=ctk.CTkFont(size=12)).pack(side="left", padx=6)
        self.cb_md   = ctk.CTkCheckBox(opts, text=".md")
        self.cb_txt  = ctk.CTkCheckBox(opts, text=".txt")
        self.cb_json = ctk.CTkCheckBox(opts, text=".json")
        for cb in (self.cb_md, self.cb_txt):
            cb.pack(side="left", padx=6)
            cb.select()
        self.cb_json.pack(side="left", padx=6)

        ctk.CTkLabel(opts, text="Mode:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(20, 4))
        self.om_batch_mode = ctk.CTkOptionMenu(opts, values=MODE_LABELS, width=300)
        self.om_batch_mode.pack(side="left", padx=4)
        self.om_batch_mode.set(MODE_FROM_API.get(self.cfg.get("default_mode","balanced"), MODE_LABELS[1]))

        self.cb_batch_organizer = ctk.CTkCheckBox(opts, text="Run Organizer")
        self.cb_batch_organizer.pack(side="left", padx=(16, 4))
        self.cb_batch_organizer.select()  # on by default for batch

        ctk.CTkButton(opts, text="Run Batch", fg_color="#2d7a2d", width=120,
                      command=self._batch_run).pack(side="right", padx=8)

        log_hdr = ctk.CTkFrame(t, fg_color="transparent")
        log_hdr.pack(fill="x", padx=8, pady=(6, 0))
        ctk.CTkLabel(log_hdr, text="Batch Output Log",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        ctk.CTkLabel(log_hdr,
                     text="   Blooms saved to blooms/ folder. Originals are never overwritten.",
                     text_color="#4caf50", font=ctk.CTkFont(size=10)).pack(side="left")

        self.tb_batch = ctk.CTkTextbox(t, font=ctk.CTkFont(family="Courier New", size=11),
                                        state="disabled")
        self.tb_batch.pack(fill="both", expand=True, padx=8, pady=(4, 10))

    def _batch_browse(self):
        d = filedialog.askdirectory(title="Select folder to batch convert")
        if d:
            self.batch_folder = d
            self.lbl_batch_folder.configure(text=d, text_color="#cccccc")

    def _batch_run(self):
        if not self.batch_folder:
            messagebox.showwarning("No folder", "Select a folder first.")
            return
        key = self.cfg.get("api_key", "")
        if not key:
            messagebox.showwarning("No API key", "Set your API key in Settings.")
            return
        exts = []
        if self.cb_md.get():   exts.append(".md")
        if self.cb_txt.get():  exts.append(".txt")
        if self.cb_json.get(): exts.append(".json")
        if not exts:
            messagebox.showwarning("No file types", "Pick at least one file type.")
            return

        files = [f for f in Path(self.batch_folder).iterdir()
                 if f.is_file() and f.suffix.lower() in exts]
        if not files:
            messagebox.showinfo("No files", "No matching files found.")
            return

        ok = messagebox.askyesno(
            "Run Batch?",
            f"{len(files)} file(s) found.\n\n"
            f"Compressed copies saved to kernels/ -- originals untouched.\n\nContinue?"
        )
        if not ok:
            return

        def run():
            self._set_tb(self.tb_batch, "")
            org_label = "organizer ON" if bool(self.cb_batch_organizer.get()) else "organizer OFF"
            self._blog(f"Batch start -- {len(files)} file(s)  [{org_label}]\n" + "-"*52 + "\n")
            ep             = self.cfg.get("api_endpoint", "https://api.soultechlabs.net")
            mode           = MODE_API.get(self.om_batch_mode.get(), "balanced")
            use_organizer  = bool(self.cb_batch_organizer.get())
            mem            = self.cfg.get("memory_folder", "")

            if mem:
                ensure_memory_folders(mem)
                out_dir = Path(mem) / "blooms"
            else:
                base = Path(self.batch_folder) / "ThoughtStream"
                ensure_memory_folders(base)
                out_dir = base / "blooms"

            total_in = total_out = ok_count = err_count = 0

            for i, fp in enumerate(files, 1):
                self._blog(f"[{i}/{len(files)}] {fp.name} ... ")
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    r    = chunk_and_compress(key, ep, text, mode,
                                              run_organizer=use_organizer)
                    comp = r.get("compressed", "")
                    oi   = len(text)
                    oo   = len(comp)
                    pct  = round((1 - oo/oi)*100, 1) if oi else 0
                    out_path = out_dir / f"{fp.stem}.bloom{fp.suffix}"
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(comp)
                    total_in  += oi
                    total_out += oo
                    ok_count  += 1
                    self._blog(f"OK  {pct}% saved  ({oi:,} -> {oo:,})\n")
                except Exception as e:
                    self._blog(f"ERR  {e}\n")
                    err_count += 1

            saved = total_in - total_out
            ratio = round((1 - total_out/total_in)*100, 1) if total_in else 0
            self._blog(
                "\n" + "-"*52 + "\n"
                f"Done.\n"
                f"  Files:   {ok_count} ok / {err_count} errors\n"
                f"  In:      {total_in:,} chars\n"
                f"  Out:     {total_out:,} chars\n"
                f"  Saved:   {saved:,} chars  ({ratio}%)\n"
                f"  Output:  {out_dir}\n"
            )
            self.usage["total_requests"]   = self.usage.get("total_requests",   0) + ok_count
            self.usage["total_chars_in"]   = self.usage.get("total_chars_in",   0) + total_in
            self.usage["total_chars_out"]  = self.usage.get("total_chars_out",  0) + total_out
            self.usage["total_saved"]      = self.usage.get("total_saved",      0) + saved
            self.usage["total_tokens_in"]  = self.usage.get("total_tokens_in",  0) + total_in  // CHARS_PER_TOKEN
            self.usage["total_tokens_out"] = self.usage.get("total_tokens_out", 0) + total_out // CHARS_PER_TOKEN
            save_usage(self.usage)

        threading.Thread(target=run, daemon=True).start()

    def _blog(self, text):
        def _do():
            self.tb_batch.configure(state="normal")
            self.tb_batch.insert("end", text)
            self.tb_batch.see("end")
            self.tb_batch.configure(state="disabled")
        self.after(0, _do)

    # -----------------------------------------------------------------------
    # USAGE
    # -----------------------------------------------------------------------
    def _build_usage(self):
        t = self.tabs.tab("Usage")
        s = ctk.CTkScrollableFrame(t)
        s.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(s, text="Usage and Token Budget",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 2), anchor="w")
        ctk.CTkLabel(s, text="Local usage tracking. No background uploads. Conversion requests sent only when you run them.",
                     text_color="#888888", font=ctk.CTkFont(size=12)).pack(pady=(0, 12), anchor="w")

        lim_row = ctk.CTkFrame(s, fg_color="transparent")
        lim_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(lim_row, text="Token limit per key:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))
        self.e_token_limit = ctk.CTkEntry(lim_row, width=120, placeholder_text="100000")
        self.e_token_limit.pack(side="left", padx=(0, 10))
        ctk.CTkButton(lim_row, text="Set", width=70,
                      command=self._usage_set_limit).pack(side="left")
        self.lbl_limit_ok = ctk.CTkLabel(lim_row, text="", text_color="#4caf50",
                                          font=ctk.CTkFont(size=11))
        self.lbl_limit_ok.pack(side="left", padx=8)

        # Plan preset buttons
        plan_row = ctk.CTkFrame(s, fg_color="transparent")
        plan_row.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(plan_row, text="Preloaded Limits:",
                     text_color="#888888",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 10))
        for plan_name, plan_tokens in PLAN_LIMITS.items():
            ctk.CTkButton(
                plan_row,
                text=plan_name,
                width=80,
                height=28,
                font=ctk.CTkFont(size=12),
                fg_color="#2d2d2d",
                hover_color="#3a3a5a",
                command=lambda t=plan_tokens, n=plan_name: self._usage_set_plan(t, n),
            ).pack(side="left", padx=4)

        ctk.CTkLabel(s, text="Compression Usage",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(4, 2))
        self.pb_tokens = ctk.CTkProgressBar(s, width=560, height=22)
        self.pb_tokens.pack(anchor="w", pady=(0, 4))
        self.pb_tokens.set(0)
        self.lbl_token_bar = ctk.CTkLabel(s, text="0 / 0 tokens used",
                                           font=ctk.CTkFont(size=12))
        self.lbl_token_bar.pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(s, text="Local counter is an estimate. Server count is authoritative.",
                     text_color="#aaaaaa", font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(s, text="ThoughtStream typically achieves 30-60% compression. Results vary by file type and content density.",
                     text_color="#aaaaaa", font=ctk.CTkFont(size=11), wraplength=580).pack(anchor="w", pady=(0, 12))

        self.tb_usage = ctk.CTkTextbox(s, height=270, width=600,
                                        font=ctk.CTkFont(family="Courier New", size=12),
                                        state="disabled")
        self.tb_usage.pack(pady=4, anchor="w")

        row = ctk.CTkFrame(s, fg_color="transparent")
        row.pack(pady=10, anchor="w")
        ctk.CTkButton(row, text="Refresh", width=120,
                      command=self._usage_refresh).pack(side="left", padx=(0, 10))
        ctk.CTkButton(row, text="Reset Stats", width=120,
                      fg_color="#7a1f1f", hover_color="#5c1818",
                      command=self._usage_reset).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(row, text="Reset clears local display only. Server tracks independently.",
                     text_color="#aaaaaa", font=ctk.CTkFont(size=11)).pack(side="left")

        self._usage_refresh()

    def _usage_set_plan(self, tokens: int, name: str):
        """One-click plan preset -- sets limit and saves."""
        self.e_token_limit.delete(0, "end")
        self.e_token_limit.insert(0, str(tokens))
        self.usage["token_limit"] = tokens
        save_usage(self.usage)
        self.lbl_limit_ok.configure(text=f"{name} plan set  ({tokens:,} tokens)", text_color="#4caf50")
        self.after(3000, lambda: self.lbl_limit_ok.configure(text=""))
        self._usage_refresh()

    def _usage_set_limit(self):
        try:
            val = int(self.e_token_limit.get().strip().replace(",", ""))
            self.usage["token_limit"] = val
            save_usage(self.usage)
            self.lbl_limit_ok.configure(text=f"Set to {val:,}")
            self.after(3000, lambda: self.lbl_limit_ok.configure(text=""))
            self._usage_refresh()
        except ValueError:
            self.lbl_limit_ok.configure(text="Enter a number", text_color="#ff9800")

    def _usage_refresh(self):
        self.usage = load_usage()
        ti  = self.usage.get("total_chars_in",   0)
        to  = self.usage.get("total_chars_out",  0)
        ts  = self.usage.get("total_saved",      0)
        rq  = self.usage.get("total_requests",   0)
        tki = self.usage.get("total_tokens_in",  0)
        tko = self.usage.get("total_tokens_out", 0)
        lim = self.usage.get("token_limit",      100000)
        rt  = round((1 - to/ti)*100, 1) if ti else 0

        pct_used  = min(tki / lim, 1.0) if lim else 0
        remaining = max(lim - tki, 0)

        if pct_used < 0.6:
            bar_color = "#4caf50"
        elif pct_used < 0.85:
            bar_color = "#ff9800"
        else:
            bar_color = "#f44336"

        self.pb_tokens.configure(progress_color=bar_color)
        self.pb_tokens.set(pct_used)
        self.lbl_token_bar.configure(
            text=f"{tki:,} / {lim:,} tokens used  ({remaining:,} remaining -- {round(pct_used*100,1)}%)",
            text_color=bar_color
        )

        if not self.e_token_limit.get():
            self.e_token_limit.insert(0, str(lim))

        text = (
            f"  Total API Requests:     {rq:,}\n\n"
            f"  Tokens (est. ~4 chars each):\n"
            f"    Input processed:     {tki:,}\n"
            f"    Output produced:     {tko:,}\n"
            f"    Tokens saved:        {tki - tko:,}\n"
            f"    Limit:               {lim:,}\n"
            f"    Remaining:           {remaining:,}\n\n"
            f"  Characters:\n"
            f"    Input:               {ti:,}\n"
            f"    Output:              {to:,}\n"
            f"    Saved:               {ts:,}\n\n"
            f"  Overall Compression:   {rt}%\n\n"
            f"  Config:   {CONFIG_FILE}\n"
            f"  Usage:    {USAGE_FILE}"
        )
        self._set_tb(self.tb_usage, text)

    def _usage_reset(self):
        if messagebox.askyesno("Reset?", "Clear all local usage stats?\n(Token limit will be kept.)"):
            lim = self.usage.get("token_limit", 100000)
            self.usage = DEFAULT_USAGE.copy()
            self.usage["token_limit"] = lim
            save_usage(self.usage)
            self._usage_refresh()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------
    def _set_tb(self, widget, text):
        def _do():
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            # Keep preview box editable; lock read-only widgets only
            if widget is not self.tb_preview:
                widget.configure(state="disabled")
        self.after(0, _do)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = ThoughtStreamHub()
    app.mainloop()

