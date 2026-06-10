"""
Video Downloader - A modern GUI application for downloading videos
Uses yt-dlp as backend and CustomTkinter for the UI
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import yt_dlp
import threading
import os
import sys
import re
import json
import time
import shutil
from pathlib import Path
from datetime import datetime


# ─── FFmpeg Detection ─────────────────────────────────────────────────────────
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


# ─── App Theme Configuration ──────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "1.0.0"
APP_TITLE = "VideoByAbdullah"
WINDOW_SIZE = "900x680"
MIN_SIZE = (800, 600)


# ─── Color Palette ─────────────────────────────────────────────────────────────
COLORS = {
    "accent":        "#3B82F6",   # Blue
    "accent_hover":  "#2563EB",
    "success":       "#22C55E",
    "warning":       "#F59E0B",
    "error":         "#EF4444",
    "bg_dark":       "#0F172A",
    "bg_card":       "#1E293B",
    "bg_input":      "#334155",
    "text_primary":  "#F1F5F9",
    "text_secondary":"#94A3B8",
    "border":        "#334155",
}


# ─── Utility Functions ─────────────────────────────────────────────────────────

def strip_ansi(text):
    """Remove ANSI terminal color codes from error strings."""
    return re.sub(r'\x1b\[[0-9;]*m|\[\d+;\d+m|\[0m', '', str(text))


def format_size(bytes_val):
    """Convert bytes to a human-readable string."""
    if bytes_val is None:
        return "Unknown"
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def format_duration(seconds):
    """Convert seconds to mm:ss or hh:mm:ss string."""
    if seconds is None:
        return "Unknown"
    seconds = int(seconds)
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def sanitize_filename(name):
    """Remove characters not safe for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name)


def get_default_download_path():
    """Return the user's Downloads folder."""
    return str(Path.home() / "Downloads")


# ─── Format Picker Data ────────────────────────────────────────────────────────

def build_format_list(formats, is_audio_only=False):
    """
    Build a user-friendly format list.
    Uses yt-dlp filter strings (not raw IDs) so they stay valid at download time.
    """
    if is_audio_only:
        return [
            {"label": "Best Audio  (auto)",    "format_id": "bestaudio/best"},
            {"label": "Audio ~128kbps",         "format_id": "bestaudio[abr<=128]/bestaudio/best"},
            {"label": "Audio ~64kbps  (small)", "format_id": "bestaudio[abr<=64]/bestaudio/best"},
        ]

    # Collect unique heights available in this video
    heights = sorted(set(
        f.get("height")
        for f in formats
        if f.get("height") and f.get("vcodec") != "none"
    ), reverse=True)

    entries = []

    if FFMPEG_AVAILABLE:
        # Can merge video+audio → offer every height
        entries.append({"label": "Best Quality  (auto)", "format_id": "bestvideo+bestaudio/best"})
        for h in heights:
            entries.append({
                "label":     f"{h}p",
                "format_id": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]",
            })
    else:
        # No ffmpeg → only pre-merged (progressive) streams work reliably
        # These are capped at 720p on YouTube but always work without merging
        entries.append({"label": "Best Quality  (auto)", "format_id": "best"})
        for h in [720, 480, 360, 240, 144]:
            if any((f.get("height") or 0) >= h for f in formats):
                entries.append({
                    "label":     f"Up to {h}p",
                    "format_id": f"best[height<={h}]/best",
                })

    return entries


# ─── Download Engine ───────────────────────────────────────────────────────────

class DownloadTask:
    """Encapsulates a single download job and reports progress via callbacks."""

    def __init__(self, url, format_id, output_dir, is_audio, on_progress, on_done, on_error, is_playlist=False, browser=None, cookies_file=None):
        self.url          = url
        self.format_id    = format_id
        self.output_dir   = output_dir
        self.is_audio     = is_audio
        self.is_playlist  = is_playlist
        self.on_progress  = on_progress
        self.on_done      = on_done
        self.on_error     = on_error
        self.browser      = browser
        self.cookies_file = cookies_file
        self._cancelled   = False
        self._thread    = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancelled = True

    def _build_ydl_opts(self):
        outtmpl = os.path.join(self.output_dir, "%(title)s.%(ext)s")

        if self.is_playlist:
            outtmpl = os.path.join(self.output_dir, "%(playlist_title)s", "%(playlist_index)s - %(title)s.%(ext)s")

        postprocessors = []

        if self.is_audio:
            if FFMPEG_AVAILABLE:
                fmt = "bestaudio/best" if self.format_id == "bestaudio/best" else self.format_id
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                })
            else:
                # No ffmpeg: download best audio stream as-is (m4a/webm)
                fmt = "bestaudio/best"
        else:
            # If format requires merging but ffmpeg missing, fall back to best pre-merged
            needs_merge = "+" in self.format_id
            if needs_merge and not FFMPEG_AVAILABLE:
                fmt = "best"
            else:
                fmt = self.format_id

        opts = {
            "format":          fmt,
            "outtmpl":         outtmpl,
            "progress_hooks":  [self._hook],
            "noplaylist":      not self.is_playlist,
            "merge_output_format": "mp4" if FFMPEG_AVAILABLE else None,
            "postprocessors":  postprocessors,
            "quiet":           True,
            "no_warnings":     True,
            "concurrent_fragment_downloads": 4,
        }
        if self.cookies_file:
            opts["cookiefile"] = self.cookies_file
        elif self.browser:
            opts["cookiesfrombrowser"] = (self.browser,)

        opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
        # Remove None values so yt-dlp doesn't choke on them
        opts = {k: v for k, v in opts.items() if v is not None}
        return opts

    def _hook(self, d):
        if self._cancelled:
            raise yt_dlp.utils.DownloadCancelled()

        status = d.get("status")
        if status == "downloading":
            total    = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed    = d.get("speed") or 0
            eta      = d.get("eta") or 0
            percent  = (downloaded / total * 100) if total else 0
            filename = os.path.basename(d.get("filename", ""))

            self.on_progress({
                "percent":    percent,
                "speed":      speed,
                "eta":        eta,
                "downloaded": downloaded,
                "total":      total,
                "filename":   filename,
                "status":     "downloading",
            })

        elif status == "finished":
            self.on_progress({"percent": 100, "status": "processing", "filename": os.path.basename(d.get("filename", ""))})

    def _run(self):
        try:
            opts = self._build_ydl_opts()
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.url])
            if not self._cancelled:
                self.on_done()
        except yt_dlp.utils.DownloadCancelled:
            self.on_error("Download cancelled.")
        except Exception as exc:
            self.on_error(strip_ansi(str(exc)))


# ─── Fetch Info Worker ─────────────────────────────────────────────────────────

class InfoFetcher:
    """Fetches video metadata in a background thread."""

    def __init__(self, url, on_done, on_error, browser=None, cookies_file=None):
        self.url          = url
        self.on_done      = on_done
        self.on_error     = on_error
        self.browser      = browser
        self.cookies_file = cookies_file

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            opts = {
                "quiet":        True,
                "no_warnings":  True,
                "skip_download":True,
                "noplaylist":   False,
            }
            if self.cookies_file:
                opts["cookiefile"] = self.cookies_file
            elif self.browser:
                opts["cookiesfrombrowser"] = (self.browser,)

            # Android bypasses YouTube's n-challenge; web+cookies handles auth for restricted videos.
            # Always try android first for public videos, web as fallback for login-required ones.
            opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
            self.on_done(info)
        except Exception as exc:
            self.on_error(strip_ansi(str(exc)))


# ─── Playlist Dialog ───────────────────────────────────────────────────────────

class PlaylistDialog(ctk.CTkToplevel):
    """Modal asking user: download single video or full playlist."""

    def __init__(self, parent, video_title, playlist_title, playlist_count):
        super().__init__(parent)
        self.title("Playlist Detected")
        self.geometry("480x260")
        self.resizable(False, False)
        self.grab_set()
        self.choice = None   # "single" | "playlist"

        self._build(video_title, playlist_title, playlist_count)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self, video_title, playlist_title, count):
        pad = {"padx": 24, "pady": 8}

        ctk.CTkLabel(
            self, text="Playlist Detected",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(24, 4))

        ctk.CTkLabel(
            self, text=f'This link belongs to playlist: "{playlist_title}" ({count} videos)',
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            wraplength=420
        ).pack(**pad)

        ctk.CTkLabel(
            self, text=f'Selected video: "{video_title[:60]}{"..." if len(video_title)>60 else ""}"',
            font=ctk.CTkFont(size=12),
            wraplength=420
        ).pack(**pad)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=16)

        ctk.CTkButton(
            btn_frame, text="Download This Video Only",
            width=200, fg_color=COLORS["accent"],
            command=lambda: self._choose("single")
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame, text=f"Download Full Playlist ({count})",
            width=200, fg_color=COLORS["bg_input"],
            command=lambda: self._choose("playlist")
        ).pack(side="left", padx=8)

    def _choose(self, choice):
        self.choice = choice
        self.destroy()

    def _on_close(self):
        self.choice = "single"
        self.destroy()


# ─── Main Application Window ───────────────────────────────────────────────────

class VideoDownloaderApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self._setup_window()
        self._init_state()
        self._build_ui()

    # ── Window Setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry(WINDOW_SIZE)
        self.minsize(*MIN_SIZE)
        # Center on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - self.winfo_width())  // 2
        y = (self.winfo_screenheight() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _init_state(self):
        self._info          = None       # Raw yt-dlp info dict
        self._formats       = []         # Parsed format entries
        self._download_task = None
        self._download_dir  = get_default_download_path()
        self._is_audio_mode = False
        self._is_fetching   = False
        self._is_downloading= False

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Root layout: sidebar + main area
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_panel()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=COLORS["bg_card"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # Logo / Title
        ctk.CTkLabel(
            sidebar, text="▶  VideoByAbdullah",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(pady=(28, 4), padx=20, anchor="w")

        ctk.CTkLabel(
            sidebar, text="Free Video Downloader",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"]
        ).pack(padx=20, anchor="w")

        ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=16, pady=20)

        # Mode toggle
        ctk.CTkLabel(sidebar, text="Download Mode", font=ctk.CTkFont(size=12, weight="bold")).pack(padx=20, anchor="w")

        self._mode_var = ctk.StringVar(value="video")
        modes = [("Video (MP4)", "video"), ("Audio (MP3)", "audio")]
        for label, val in modes:
            ctk.CTkRadioButton(
                sidebar, text=label, variable=self._mode_var, value=val,
                command=self._on_mode_change,
                font=ctk.CTkFont(size=12)
            ).pack(padx=24, pady=4, anchor="w")

        ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=16, pady=20)

        # Output folder
        ctk.CTkLabel(sidebar, text="Save to", font=ctk.CTkFont(size=12, weight="bold")).pack(padx=20, anchor="w")

        self._dir_label = ctk.CTkLabel(
            sidebar, text=self._shorten_path(self._download_dir),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            wraplength=190, justify="left"
        )
        self._dir_label.pack(padx=20, pady=(4, 8), anchor="w")

        ctk.CTkButton(
            sidebar, text="Change Folder",
            height=32, font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_input"],
            hover_color=COLORS["border"],
            command=self._pick_folder
        ).pack(padx=20, fill="x")

        self._browser_var = ctk.StringVar(value="None")
        self._cookies_file = None

        ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=16, pady=20)

        # Appearance toggle
        ctk.CTkLabel(sidebar, text="Appearance", font=ctk.CTkFont(size=12, weight="bold")).pack(padx=20, anchor="w")
        self._theme_switch = ctk.CTkSwitch(
            sidebar, text="Dark Mode",
            command=self._toggle_theme,
            font=ctk.CTkFont(size=12),
            onvalue="dark", offvalue="light"
        )
        self._theme_switch.select()
        self._theme_switch.pack(padx=20, pady=8, anchor="w")

        # Version at bottom
        ctk.CTkLabel(
            sidebar, text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        ).pack(side="bottom", pady=16)

    def _build_main_panel(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=0)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 0))

        ctk.CTkLabel(
            header, text="Download a Video",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Paste a YouTube, Vimeo, Twitter/X, TikTok, or any supported URL below.",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(2, 0))


        # URL input card
        self._build_url_card(main)

        # Info + format card
        self._build_info_card(main)

        # Progress card
        self._build_progress_card(main)

    def _build_url_card(self, parent):
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        card.grid(row=1, column=0, sticky="ew", padx=28, pady=16)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="Video URL", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(16, 6))

        self._url_entry = ctk.CTkEntry(
            card,
            placeholder_text="https://www.youtube.com/watch?v=...",
            height=44, font=ctk.CTkFont(size=13),
            corner_radius=8
        )
        self._url_entry.grid(row=1, column=0, sticky="ew", padx=(20, 8), pady=(0, 16))
        self._url_entry.bind("<Return>", lambda e: self._fetch_info())

        self._fetch_btn = ctk.CTkButton(
            card, text="Fetch Info",
            width=120, height=44,
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=8,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self._fetch_info
        )
        self._fetch_btn.grid(row=1, column=1, padx=(0, 20), pady=(0, 16))

    def _build_info_card(self, parent):
        self._info_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        self._info_card.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 16))
        self._info_card.grid_columnconfigure(0, weight=1)
        self._info_card.grid_rowconfigure(0, weight=0)

        # Placeholder
        self._placeholder_label = ctk.CTkLabel(
            self._info_card,
            text="Paste a URL and click \"Fetch Info\" to get started.",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        )
        self._placeholder_label.grid(row=0, column=0, pady=40)

        # Actual info widgets (hidden until fetch)
        self._thumb_label    = None
        self._title_label    = None
        self._meta_label     = None
        self._format_frame   = None
        self._format_var     = ctk.StringVar(value="")
        self._format_menu    = None
        self._download_btn   = None

    def _build_progress_card(self, parent):
        self._prog_card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=12)
        self._prog_card.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 24))
        self._prog_card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(self._prog_card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=20, pady=16)
        inner.grid_columnconfigure(0, weight=1)

        # Status label
        self._status_label = ctk.CTkLabel(
            inner, text="Idle",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        self._status_label.grid(row=0, column=0, sticky="w")

        # Percent label
        self._percent_label = ctk.CTkLabel(
            inner, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._percent_label.grid(row=0, column=1, sticky="e")

        # Progress bar
        self._progress_bar = ctk.CTkProgressBar(inner, height=10, corner_radius=5)
        self._progress_bar.set(0)
        self._progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=8)

        # Speed / ETA row
        stats_row = ctk.CTkFrame(inner, fg_color="transparent")
        stats_row.grid(row=2, column=0, columnspan=2, sticky="ew")

        self._speed_label = ctk.CTkLabel(stats_row, text="", font=ctk.CTkFont(size=11), text_color=COLORS["text_secondary"])
        self._speed_label.pack(side="left")

        self._eta_label = ctk.CTkLabel(stats_row, text="", font=ctk.CTkFont(size=11), text_color=COLORS["text_secondary"])
        self._eta_label.pack(side="right")

    # ── Info Fetching ──────────────────────────────────────────────────────────

    def _fetch_info(self):
        url = self._url_entry.get().strip()
        if not url:
            self._show_error("Please enter a URL first.")
            return

        if self._is_fetching:
            return

        self._is_fetching = True
        self._set_fetch_state(loading=True)
        self._clear_info_card()
        self._show_placeholder("Fetching video information...")
        self._update_status("Fetching metadata...", COLORS["warning"])

        browser = self._get_browser()
        InfoFetcher(url, on_done=self._on_info_fetched, on_error=self._on_fetch_error,
                    browser=browser, cookies_file=self._get_cookies_file()).start()

    def _get_browser(self):
        val = self._browser_var.get()
        return None if val == "None" else val

    def _get_cookies_file(self):
        return getattr(self, "_cookies_file", None)

    def _on_info_fetched(self, info):
        self.after(0, lambda: self._handle_info(info))

    def _on_fetch_error(self, err):
        self.after(0, lambda: self._handle_fetch_error(err))

    def _handle_info(self, info):
        self._is_fetching = False
        self._set_fetch_state(loading=False)
        self._info = info

        is_playlist = info.get("_type") == "playlist"

        if is_playlist:
            # Pick the first entry as the "selected" video but let user choose
            entries = info.get("entries", [])
            if not entries:
                self._show_error("Playlist appears to be empty.")
                return

            # Use first entry for display; ask what to download
            first = entries[0]
            if first is None:
                self._show_error("Could not load playlist entries.")
                return

            playlist_title = info.get("title", "Playlist")
            count = len(entries)
            video_title = first.get("title", "Unknown")

            dialog = PlaylistDialog(self, video_title, playlist_title, count)
            self.wait_window(dialog)

            if dialog.choice == "playlist":
                # Reload info but allow playlist
                self._show_placeholder("Fetching full playlist info...")
                self._is_fetching = True
                self._set_fetch_state(loading=True)
                InfoFetcher(
                    self._url_entry.get().strip(),
                    on_done=self._on_playlist_info_fetched,
                    on_error=self._on_fetch_error,
                    browser=self._get_browser(),
                    cookies_file=self._get_cookies_file()
                ).start()
                return
            else:
                # Use first entry
                info = first
                # Fetch its own formats if not embedded
                if "formats" not in info:
                    url = info.get("webpage_url") or info.get("url")
                    self._show_placeholder("Fetching video formats...")
                    self._is_fetching = True
                    self._set_fetch_state(loading=True)
                    InfoFetcher(url, on_done=self._on_info_fetched, on_error=self._on_fetch_error,
                                browser=self._get_browser(), cookies_file=self._get_cookies_file()).start()
                    return

        self._display_info(info, is_playlist=False)

    def _on_playlist_info_fetched(self, info):
        self.after(0, lambda: self._display_info(info, is_playlist=True))

    def _handle_fetch_error(self, err):
        self._is_fetching = False
        self._set_fetch_state(loading=False)
        self._show_placeholder("Could not load video info. Check the URL.")
        self._show_error(f"Error: {err[:300]}")
        self._update_status("Failed to fetch info.", COLORS["error"])

    def _display_info(self, info, is_playlist=False):
        self._info = info
        self._is_playlist = is_playlist
        self._is_fetching  = False
        self._set_fetch_state(loading=False)
        self._clear_info_card()
        try:
            self._populate_info_card(info, is_playlist)
            self._update_status("Ready to download.", COLORS["success"])
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._show_placeholder(f"UI Error: {exc}")
            self._update_status("Error loading info.", COLORS["error"])

    def _populate_info_card(self, info, is_playlist):
        """Fill the info card with title, metadata, and format selector."""
        card = self._info_card

        # ---- Title row ----
        title_frame = ctk.CTkFrame(card, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        title_frame.grid_columnconfigure(0, weight=1)

        title = info.get("title", "Unknown Title")
        if is_playlist:
            title = f"[Playlist] {info.get('title', 'Unknown Playlist')}"

        title_lbl = ctk.CTkLabel(
            title_frame, text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w", wraplength=560, justify="left"
        )
        title_lbl.grid(row=0, column=0, sticky="w")

        # ---- Meta row ----
        duration = format_duration(info.get("duration"))
        uploader = info.get("uploader") or info.get("channel") or "Unknown"
        view_count= info.get("view_count")
        views_str = f"{view_count:,} views" if view_count else ""
        count_str = f"{len(info.get('entries', []))} videos" if is_playlist else ""

        meta_parts = [p for p in [uploader, duration if not is_playlist else count_str, views_str] if p]
        meta_text  = "  ·  ".join(meta_parts)

        ctk.CTkLabel(
            card, text=meta_text,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(4, 12))

        # ---- Divider ----
        ctk.CTkFrame(card, height=1, fg_color=COLORS["border"]).grid(row=2, column=0, sticky="ew", padx=20)

        # ---- Format selector ----
        ctk.CTkLabel(card, text="Quality / Format:",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=3, column=0, sticky="w", padx=20, pady=(16, 4))

        # Build format list
        if is_playlist:
            fmt_entries = [
                {"label": "Best Quality (per video)",      "format_id": "bestvideo+bestaudio/best"},
                {"label": "720p (per video)",              "format_id": "bestvideo[height<=720]+bestaudio/best"},
                {"label": "480p (per video)",              "format_id": "bestvideo[height<=480]+bestaudio/best"},
                {"label": "Audio Only MP3 (per video)",    "format_id": "bestaudio/best"},
            ]
        else:
            raw_formats = info.get("formats", [])
            is_audio    = (self._mode_var.get() == "audio")
            fmt_entries = build_format_list(raw_formats, is_audio_only=is_audio)

        self._formats = fmt_entries
        labels = [e["label"] for e in fmt_entries]

        if not labels:
            labels = ["Best Available"]
            self._formats = [{"label": "Best Available", "format_id": "best"}]

        self._format_var.set(labels[0])
        self._format_menu = ctk.CTkOptionMenu(
            card, values=labels,
            variable=self._format_var,
            height=40,
            font=ctk.CTkFont(size=13),
            dropdown_font=ctk.CTkFont(size=13),
            dynamic_resizing=False,
        )
        self._format_menu.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 8))

        # ---- Download button ----
        btn_text = "Download Playlist" if is_playlist else "  ⬇  Download"

        self._download_btn = ctk.CTkButton(
            card,
            text=btn_text,
            height=46,
            font=ctk.CTkFont(size=14, weight="bold"),
            corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            command=self._start_download
        )
        self._download_btn.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 20))

    # ── Download Control ───────────────────────────────────────────────────────

    def _start_download(self):
        if self._info is None:
            self._show_error("Please fetch a video first.")
            return
        if self._is_downloading:
            return

        # Find selected format entry
        selected_label = self._format_var.get()
        fmt_entry = next((f for f in self._formats if f["label"] == selected_label), None)
        if fmt_entry is None:
            fmt_entry = {"format_id": "bestvideo+bestaudio/best"}

        format_id = fmt_entry["format_id"]
        is_audio  = (self._mode_var.get() == "audio") or "Audio" in selected_label

        url = self._url_entry.get().strip()
        is_playlist = getattr(self, "_is_playlist", False)

        self._is_downloading = True
        self._toggle_download_btn(active=True)
        self._progress_bar.set(0)
        self._update_status("Starting download...", COLORS["warning"])

        self._download_task = DownloadTask(
            url        = url,
            format_id  = format_id,
            output_dir = self._download_dir,
            is_audio   = is_audio,
            is_playlist= is_playlist,
            on_progress= self._on_download_progress,
            on_done    = self._on_download_done,
            on_error   = self._on_download_error,
            browser      = self._get_browser(),
            cookies_file = self._get_cookies_file(),
        )
        self._download_task.start()

    def _cancel_download(self):
        if self._download_task:
            self._download_task.cancel()
        self._is_downloading = False
        self._toggle_download_btn(active=False)
        self._update_status("Cancelled.", COLORS["error"])

    def _on_download_progress(self, data):
        self.after(0, lambda: self._update_progress_ui(data))

    def _on_download_done(self):
        self.after(0, self._handle_done)

    def _on_download_error(self, err):
        self.after(0, lambda: self._handle_dl_error(err))

    def _update_progress_ui(self, data):
        status = data.get("status", "downloading")
        percent = data.get("percent", 0)

        self._progress_bar.set(percent / 100)
        self._percent_label.configure(text=f"{percent:.1f}%")

        if status == "processing":
            self._status_label.configure(text="Post-processing (merging / converting)...")
            self._speed_label.configure(text="")
            self._eta_label.configure(text="")
            return

        filename = data.get("filename", "")
        speed    = data.get("speed", 0)
        eta      = data.get("eta", 0)
        downloaded = data.get("downloaded", 0)
        total      = data.get("total", 0)

        display_name = filename[:48] + "..." if len(filename) > 50 else filename
        self._status_label.configure(text=f"Downloading: {display_name}")
        self._speed_label.configure(text=f"Speed: {format_size(speed)}/s")

        eta_str = f"{eta}s" if eta < 60 else f"{eta//60}m {eta%60}s"
        size_str = f"{format_size(downloaded)} / {format_size(total)}"
        self._eta_label.configure(text=f"ETA: {eta_str}  |  {size_str}")

    def _handle_done(self):
        self._is_downloading = False
        self._toggle_download_btn(active=False)
        self._progress_bar.set(1)
        self._percent_label.configure(text="100%")
        self._status_label.configure(text="Download complete!")
        self._speed_label.configure(text="")
        self._eta_label.configure(text=f"Saved to: {self._shorten_path(self._download_dir)}")
        self._update_status("Done!", COLORS["success"])
        messagebox.showinfo("Download Complete", f"Your download has finished!\n\nSaved to:\n{self._download_dir}")

    def _handle_dl_error(self, err):
        self._is_downloading = False
        self._toggle_download_btn(active=False)
        self._update_status("Download failed.", COLORS["error"])
        self._status_label.configure(text="Download failed.")
        self._show_error(f"Download error:\n{err[:400]}")

    # ── UI Helpers ─────────────────────────────────────────────────────────────

    def _toggle_download_btn(self, active):
        if self._download_btn is None:
            return
        if active:
            self._download_btn.configure(
                text="  ✕  Cancel",
                fg_color=COLORS["error"],
                hover_color="#DC2626",
                command=self._cancel_download
            )
        else:
            self._download_btn.configure(
                text="  ⬇  Download",
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"],
                command=self._start_download
            )

    def _set_fetch_state(self, loading):
        if loading:
            self._fetch_btn.configure(text="Loading...", state="disabled", fg_color=COLORS["bg_input"])
        else:
            self._fetch_btn.configure(text="Fetch Info", state="normal", fg_color=COLORS["accent"])

    def _clear_info_card(self):
        for widget in self._info_card.winfo_children():
            widget.destroy()
        self._download_btn = None
        self._format_menu  = None

    def _show_placeholder(self, text="Paste a URL and click \"Fetch Info\" to get started."):
        self._clear_info_card()
        ctk.CTkLabel(
            self._info_card,
            text=text,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"]
        ).grid(row=0, column=0, pady=40)

    def _update_status(self, text, color=None):
        self._status_label.configure(text=text)
        if color:
            self._status_label.configure(text_color=color)

    def _on_mode_change(self):
        """Re-build format list when user switches between video/audio."""
        if self._info and not getattr(self, "_is_playlist", False):
            raw_formats = self._info.get("formats", [])
            is_audio    = (self._mode_var.get() == "audio")
            self._formats = build_format_list(raw_formats, is_audio_only=is_audio)
            labels = [e["label"] for e in self._formats]
            if self._format_menu:
                self._format_menu.configure(values=labels)
                self._format_var.set(labels[0])

    def _pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self._download_dir, title="Select Download Folder")
        if folder:
            self._download_dir = folder
            self._dir_label.configure(text=self._shorten_path(folder))

    def _pick_cookies_file(self):
        path = filedialog.askopenfilename(
            title="Select cookies.txt file",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self._cookies_file = path
            self._cookies_label.configure(
                text=os.path.basename(path),
                text_color=COLORS["success"]
            )
            # Disable browser dropdown when file is chosen
            self._browser_var.set("None")

    def _clear_cookies_file(self):
        self._cookies_file = None
        self._cookies_label.configure(text="No file selected", text_color=COLORS["text_secondary"])

    def _toggle_theme(self):
        mode = self._theme_switch.get()
        ctk.set_appearance_mode(mode)

    @staticmethod
    def _shorten_path(path, max_len=28):
        if len(path) <= max_len:
            return path
        parts = Path(path).parts
        if len(parts) > 2:
            return os.path.join(parts[0], "...", parts[-1])
        return path[:max_len] + "..."

    @staticmethod
    def _show_error(message):
        messagebox.showerror("Error", message)


# ─── Entry Point ───────────────────────────────────────────────────────────────

def main():
    # Windows: enable DPI awareness for crisp text
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = VideoDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
