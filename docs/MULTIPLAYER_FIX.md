# Multiplayer fix

SteaMidra can download and apply multiplayer fixes for supported games using a built-in flow (remote sources). Some builds ship with credentials already configured; otherwise you can enter your own in **Settings**.

---

## What you need

- A valid **multiplayer fix** account when the build does not embed credentials (username and password are stored securely after the first use).
- Optional extra Python packages depending on your install — see the Setup Guide and `requirements.txt` (for example httpx, beautifulsoup4, lxml, Selenium).

## How to use it

Run SteaMidra, choose **Apply multiplayer fix** from the menu or the library, pick your Steam library and the game, then follow the prompts.

## If something goes wrong

If login fails, check your credentials in **Settings**. If the game is not found, try the full official game name. If downloads or extraction fail, check your network and antivirus. See `debug.log` in the SteaMidra folder or ask on Discord.

## Responsibility

Use this feature at your own risk. SteaMidra automates downloading and extracting third-party files into your game folder. Respect each game's terms of service.
