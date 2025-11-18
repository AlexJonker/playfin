import curses
import os
from .constants import CONFIG_FILE
from .cache import get_cached_show_status, get_cached_season_status
import json
from .encryption import decrypt_password

def load_config(): # duplicate since im not in the mood to fix it properly. This project is fucked anyway.
    if not os.path.exists(CONFIG_FILE):
        return None

    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)

        # Decrypt password
        key = config["ENCRYPTION_KEY"]
        config["JELLYFIN_PASSWORD"] = decrypt_password(config["JELLYFIN_PASSWORD"], key)
        return config
    except Exception as e:
        return None

config = load_config()
JELLYFIN_URL = config["JELLYFIN_URL"]


def init_curses():
    # Initialize curses
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    curses.curs_set(0)  # Hide cursor

    # Initialize colors if supported
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Watched items
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)  # Error messages
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)  # Menu headers
        curses.init_pair(
            4, curses.COLOR_YELLOW, curses.COLOR_BLACK
        )  # Partially watched items

    return stdscr

stdscr = init_curses()


def get_input(stdscr, prompt, hidden=False):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    stdscr.addstr(h // 2 - 1, (w - len(prompt)) // 2, prompt)
    stdscr.refresh()

    if hidden:
        curses.noecho()
    else:
        curses.echo()

    input_str = ""
    while True:
        c = stdscr.getch()
        if c == curses.KEY_ENTER or c in [10, 13]:
            break
        elif c == curses.KEY_BACKSPACE or c == 127:
            if len(input_str) > 0:
                input_str = input_str[:-1]
                stdscr.delch(h // 2, (w - len(prompt)) // 2 + len(input_str))
        else:
            input_str += chr(c)
            if hidden:
                stdscr.addch(h // 2, (w - len(prompt)) // 2 + len(input_str) - 1, "*")
            else:
                stdscr.addch(h // 2, (w - len(prompt)) // 2 + len(input_str) - 1, c)

    curses.noecho()
    return input_str


def cleanup():
    curses.nocbreak()
    stdscr.keypad(False)
    curses.echo()
    curses.endwin()

def display_menu(items, title, selected_index=0, status_msg="", headers=None):
    stdscr.clear()
    h, w = stdscr.getmaxyx()

    # Calculate the visible range of items
    max_visible_items = h - 4  # Leave space for title and status message
    start_index = max(0, selected_index - max_visible_items + 1)
    end_index = min(len(items), start_index + max_visible_items)

    # Draw title
    if curses.has_colors():
        stdscr.addstr(
            0, (w - len(title)) // 2, title, curses.color_pair(3) | curses.A_BOLD
        )
    else:
        stdscr.addstr(0, (w - len(title)) // 2, title, curses.A_BOLD)

    # First pass: draw all items without status (fast)
    for idx, item in enumerate(items[start_index:end_index]):
        actual_idx = start_index + idx
        item_text = (
            f"> {item['Name']}" if actual_idx == selected_index else f"  {item['Name']}"
        )
        stdscr.addstr(
            idx + 2,
            2,
            item_text,
            curses.A_REVERSE if actual_idx == selected_index else 0,
        )

    stdscr.refresh()  # Show initial draw quickly

    # Second pass: add status indicators (slower but now visible)
    for idx, item in enumerate(items[start_index:end_index]):
        actual_idx = start_index + idx
        user_data = item.get("UserData", {})
        is_watched = user_data.get("Played", False)
        is_partial = not is_watched and user_data.get("PlaybackPositionTicks", 0) > 0

        # Get status from cache if needed
        if "Id" in item and not (is_watched or is_partial):
            if item.get("Type") == "Series":
                status = get_cached_show_status(item["Id"], headers, JELLYFIN_URL)
                has_watched = status["watched"]
                has_partial = status["partial"]
            elif item.get("Type") == "Season":
                status = get_cached_season_status(item.get("SeriesId", ""), item["Id"], headers, JELLYFIN_URL)
                has_watched = status["watched"]
                has_partial = status["partial"]
        
            else:
                has_watched = False
                has_partial = False
        else:
            has_watched = False
            has_partial = False

        # Determine final status
        if is_watched:
            color = 1
            indicator = "✔"
        elif is_partial:
            color = 4
            indicator = "~"
        elif has_watched:
            color = 1
            indicator = "✔"
        elif has_partial:
            color = 4
            indicator = "~"
        else:
            color = 0
            indicator = " "

        # Apply color if needed
        if color > 0 and curses.has_colors():
            item_text = (
                f"> {item['Name']}"
                if actual_idx == selected_index
                else f"  {item['Name']}"
            )
            attr = curses.A_REVERSE if actual_idx == selected_index else 0
            stdscr.addstr(idx + 2, 2, item_text, attr | curses.color_pair(color))

        # Add indicator if needed
        if indicator != " ":
            if curses.has_colors():
                stdscr.addstr(idx + 2, w - 2, indicator, curses.color_pair(color))
            else:
                stdscr.addstr(idx + 2, w - 2, indicator)

    # Status message
    if status_msg:
        if curses.has_colors() and "Error" in status_msg:
            stdscr.addstr(h - 1, 0, status_msg, curses.color_pair(2))
        else:
            stdscr.addstr(h - 1, 0, status_msg)

    stdscr.refresh()




def select_from_list(items, title, allow_escape_up=False, headers=None):
    selected_index = 0
    filtered_items = items[:]
    search_query = ""
    status_msg = "↑/↓: Navigate | Enter: Select | Q: Quit | /: Search"
    if allow_escape_up:
        status_msg += " | ESC: Go Back"

    def filter_items(query):
        return [item for item in items if query.lower() in item["Name"].lower()]

    display_menu(filtered_items, title, selected_index, status_msg, headers)

    while True:
        try:
            key = stdscr.getch()

            if key == ord('/'):  # Begin search
                search_query = ""
                stdscr.addstr(curses.LINES - 2, 0, "Search: ")
                stdscr.clrtoeol()
                curses.echo()
                while True:
                    ch = stdscr.getch()
                    if ch in [10, 13]:  # Enter
                        break
                    elif ch in [27]:  # ESC to cancel
                        search_query = ""
                        break
                    elif ch in [curses.KEY_BACKSPACE, 127]:
                        search_query = search_query[:-1]
                    else:
                        try:
                            search_query += chr(ch)
                        except:
                            pass
                    filtered_items = filter_items(search_query)
                    selected_index = 0
                    stdscr.addstr(curses.LINES - 2, 0, f"Search: {search_query}")
                    stdscr.clrtoeol()
                    display_menu(filtered_items, title, selected_index, f"Search: {search_query}")
                curses.noecho()
                display_menu(filtered_items, title, selected_index, status_msg)

            elif key == curses.KEY_UP and selected_index > 0:
                selected_index -= 1
                display_menu(filtered_items, title, selected_index, status_msg)
            elif key == curses.KEY_DOWN and selected_index < len(filtered_items) - 1:
                selected_index += 1
                display_menu(filtered_items, title, selected_index, status_msg)
            elif key == curses.KEY_ENTER or key in [10, 13]:
                if filtered_items:
                    return items.index(filtered_items[selected_index])
            elif key == 27 and allow_escape_up:
                return -1
            elif key in [ord('q'), ord('Q')]:
                cleanup()
                os._exit(0)
        except Exception as e:
            display_menu(filtered_items, title, selected_index, f"Error: {str(e)}")
    return selected_index




def select_media_type():
    options = [
        {"Name": "TV Shows", "Type": "Series"},
        {"Name": "Movies", "Type": "Movie"},
    ]
    selected = select_from_list(options, "Select Media Type", allow_escape_up=False)
    return options[selected]["Type"]
