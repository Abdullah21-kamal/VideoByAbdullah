# VideoByAbdullah 🎬

A free, modern video downloader desktop app built with Python.
Supports YouTube, Facebook, TikTok, Vimeo, and 1000+ other platforms.

---

## Features

- Download videos from YouTube, Facebook, TikTok, Vimeo, and more
- Choose video quality before downloading
- Switch between Video (MP4) and Audio (MP3) mode
- Real-time progress bar with speed and ETA
- Clean modern dark/light UI
- No installation needed (just run the .exe)

---

## Download (Windows .exe)

> No Python needed — just download and double-click.

**[[https://drive.google.com/file/d/1ROmwkFX9ZABcQWcy5bZhl7YdgDkZ4W2w/view?usp=sharing](#)](https://drive.google.com/file/d/1ROmwkFX9ZABcQWcy5bZhl7YdgDkZ4W2w/view?usp=sharing)** 

> ⚠️ Windows may show "Windows protected your PC" — click **More info** → **Run anyway**. This is normal for unsigned apps.

---

## Run from source

**1. Install dependencies:**
```
pip install -r requirements.txt
```

**2. Run the app:**
```
python video_downloader.py
```

---

## Build the .exe yourself

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "VideoByAbdullah" --hidden-import customtkinter --hidden-import yt_dlp video_downloader.py
```

The exe will be in the `dist/` folder.

---

## Tech Stack

- [Python](https://python.org)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — download engine
- [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) — modern GUI

---

## Important Notice

Please use this app **only for halal and lawful purposes**.
Do NOT use it to download copyrighted music, inappropriate content,
or anything that goes against Islamic values.
This app was built with good intentions — let's keep it that way. 🤲

---

## Author

Built by **Abdullah** — feel free to reach out on LinkedIn!
