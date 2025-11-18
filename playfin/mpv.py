import os
from .ui import *
import requests
import tempfile
import subprocess
import time
import socket
import json
import threading
from .config import *

config = get_credentials()
JELLYFIN_URL = config["JELLYFIN_URL"]


def play_item(item_id, item_name, token, headers, user_id):
    cleanup()  # Clean up curses before playback

    try:
        stream_url = f"{JELLYFIN_URL}/Items/{item_id}/Download?api_key={token}"

        # === START PLAYBACK SESSION ===
        requests.post(
            f"{JELLYFIN_URL}/Sessions/Playing",
            headers=headers,
            json={
                "ItemId": item_id,
                "CanSeek": True,
                "IsPaused": True,
                "IsMuted": False,
                "PlaybackStartTimeTicks": 0,
                "PlayMethod": "DirectStream",
            },
        )

        # === MPV IPC ===
        ipc_path = tempfile.NamedTemporaryFile(delete=False).name
        playback_info = requests.get(
            f"{JELLYFIN_URL}/Users/{user_id}/Items/{item_id}", headers=headers
        ).json()

        start_position_ticks = playback_info.get("UserData", {}).get(
            "PlaybackPositionTicks", 0
        )
        start_position_seconds = (
            start_position_ticks // 10_000_000
        )  # Convert ticks to seconds

        print(
            f"Starting playback of '{item_name}' from {start_position_seconds} seconds..."
        )

        mpv_proc = subprocess.Popen(
            [
                "mpv",
                stream_url,
                f"--input-ipc-server={ipc_path}",
                # "--slang=en", # subs
                # "--alang=ja", # audio
                f"--start={start_position_seconds}",
                "--fs"
            ]
        )

        import errno

        sock = socket.socket(socket.AF_UNIX)

        timeout = time.time() + 5  # wait max 5 seconds
        while True:
            try:
                if os.path.exists(ipc_path):
                    sock.connect(ipc_path)
                    break
            except socket.error as e:
                if e.errno != errno.ECONNREFUSED:
                    raise
            if time.time() > timeout:
                raise TimeoutError(f"Could not connect to MPV IPC socket at {ipc_path}")
            time.sleep(0.1)

            def send_ipc_command(command):
                try:
                    msg = json.dumps({"command": command})
                    sock.sendall((msg + "\n").encode())
                    response = b""
                    while not response.endswith(b"\n"):
                        response += sock.recv(4096)
                    return json.loads(response.decode())
                except Exception as e:
                    print(f"IPC command failed: {e}")
                    return None
        def get_position():
            result = send_ipc_command(["get_property", "playback-time"])
            if result and "data" in result and isinstance(result["data"], (int, float)):
                return result["data"]
            return None

        def get_playback_status():
            result = send_ipc_command(["get_property", "pause"])
            if result and "data" in result and isinstance(result["data"], bool):
                return not result["data"]  # Return True if playing, False if paused
            return None

        # === SIMPLE PROGRESS REPORTING ===
        def report_progress():
            while mpv_proc.poll() is None:  # While MPV is running
                try:
                    current_pos = get_position()
                    if current_pos is not None:
                        try:
                            requests.post(
                                f"{JELLYFIN_URL}/Sessions/Playing/Progress",
                                headers=headers,
                                json={
                                    "ItemId": item_id,
                                    "PositionTicks": int(current_pos * 10_000_000),
                                },
                                timeout=2,  # Short timeout to prevent hanging
                            )
                            print(
                                f"↻ Current progress: {current_pos:.1f} seconds", end="\r"
                            )
                        except requests.exceptions.RequestException as e:
                            print(f"⚠ Progress report failed: {e}")
                    time.sleep(2)  # Report progress every 2 seconds
                except Exception as e:
                    print(f"⚠ Unexpected error in progress reporting: {e}")
                    time.sleep(2)

        progress_thread = threading.Thread(target=report_progress, daemon=True)
        progress_thread.start()

        # ^C fix so that jellyfin doesnt keep playing the progress
        try:
            while mpv_proc.poll() is None:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nCaught interrupt, stopping playback...")
            mpv_proc.terminate()
            try:
                mpv_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                mpv_proc.kill()

        # === STOP SESSION ===
        try:
            final_pos = get_position() or 0  # Default to 0 if None
            requests.post(
                f"{JELLYFIN_URL}/Sessions/Playing/Stopped",
                headers=headers,
                json={
                    "ItemId": item_id,
                    "PositionTicks": int(final_pos * 10_000_000),
                    "MediaSourceId": item_id,
                },
                timeout=3
            )
            print(f"\n⏹ Playback stopped at position: {final_pos:.1f} seconds")
        except Exception as e:
            print(f"\n⚠ Failed to send stop notification: {e}")
        sock.close()
        try:
            os.unlink(ipc_path)
        except:
            pass

    except Exception as e:
        print(f"\n⚠ Error during playback: {e}")
        cleanup()
        raise

    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    curses.curs_set(0)
    
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    
    return stdscr  # Return the new stdscr object
