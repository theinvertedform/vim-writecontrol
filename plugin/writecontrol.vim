if exists('g:loaded_writecontrol') || !has('python3')
    finish
endif
let g:loaded_writecontrol = 1

" Default settings
" Removed: g:writecontrol_auto_repos (unused filter)
" Removed: g:writecontrol_analytics_script (analytics triggering moved)
" Removed: g:writecontrol_archive_dir (unused)
let g:writecontrol_debug = get(g:, 'writecontrol_debug', 0)

python3 << EOF
import vim
import os
import time
from dataclasses import dataclass
from typing import List, Dict, Set, Optional
import json
from enum import Enum

class VimMode(Enum):
    NORMAL = 'n'
    INSERT = 'i'
    VISUAL = 'v'
    CMDLINE = 'c'
    EX = 'e'
    SELECT = 's'
    TERMINAL = 't'
    REPLACE = 'r'

@dataclass
class KeyEvent:
    dt: int        # Delta milliseconds from session start
    pos: int       # Combined line/col position (line * 1000 + col)
    type: str      # 'k' (keystroke), 'd' (delete), 'm' (mode), 'c' (cursor), 's' (save), 'cmd' (command), 'start', 'end'
    content: str   # The actual keystroke, mode identifier, or command
    word: str      # Current word being edited (empty if not in word)

class WritingSession:
    def __init__(self, filename: str):
        self.filename = filename
        self.start_time = int(time.time() * 1000)  # Millisecond precision
        self.events: List[KeyEvent] = []
        self.last_content = None
        self.current_word = ''
        self.current_mode = VimMode.NORMAL
        self.mode_start_time = self.start_time
        self.mode_durations = {mode: 0 for mode in VimMode}
        self.last_position = (1, 0)  # Line, col
        self.last_command = ''

    def to_dict(self) -> Dict:
        return {
            'filename': self.filename,
            'start_time': self.start_time,
            'mode_durations': {
                mode.value: duration
                for mode, duration in self.mode_durations.items()
            },
            'events': [
                {
                    'dt': e.dt,
                    'pos': e.pos,
                    'type': e.type,
                    'content': e.content,
                    'word': e.word
                } for e in self.events
            ]
        }

class WriteControl:
    def __init__(self):
        self.current_session = None
        self.setup_directories()
        self.debug_mode = bool(int(vim.eval('g:writecontrol_debug')))

    def debug(self, message: str):
        """Print a debug message if debug mode is enabled"""
        if self.debug_mode:
            # Use f-string formatting for consistency
            vim.command(f"echom 'WriteControl DEBUG: {message}'")

    def setup_directories(self):
        # Get XDG directory paths with fallbacks
        xdg_state_home = os.getenv('XDG_STATE_HOME')
        if not xdg_state_home:
            xdg_state_home = os.path.join(os.path.expanduser('~'), '.local', 'state')

        # Create base directories for the Vim plugin
        # The Vim plugin is only responsible for writing to the current directory
        self.current_dir = os.path.join(xdg_state_home, 'writecontrol', 'current')

        # Create the necessary directory
        os.makedirs(self.current_dir, exist_ok=True)

    def get_current_word(self):
        """Helper method to get the current word under cursor"""
        try:
            line, col = vim.current.window.cursor
            # Check line validity against buffer length
            if line <= 0 or line > len(vim.current.buffer):
                return ''

            line_content = vim.current.buffer[line-1]

            # Check column validity against line length (col is 0-based index)
            if not line_content or col >= len(line_content):
                # Allow getting word if cursor is just after the word
                if col > 0 and (line_content[col-1].isalnum() or line_content[col-1] == '_'):
                   col -= 1 # Adjust col to be on the last character of the word
                else:
                   return '' # Cursor not within or immediately after a word


            word_start = col
            # Allow starting search from adjusted column
            while word_start >= 0 and (line_content[word_start].isalnum() or line_content[word_start] == '_'):
                 if word_start == 0: # Break if we hit start of line
                    break
                 if not (line_content[word_start-1].isalnum() or line_content[word_start-1] == '_'):
                    break # Stop if the previous char is not part of a word
                 word_start -= 1

            word_end = col
            while word_end < len(line_content) and (line_content[word_end].isalnum() or line_content[word_end] == '_'):
                word_end += 1

            # Ensure word_start did not go negative if word starts at column 0
            word_start = max(0, word_start)

            return line_content[word_start:word_end]
        except Exception as e:
            self.debug(f"Error getting current word: {str(e)}")
            return ''

    def start_session(self):
        filename = vim.current.buffer.name

        # Keep check for unnamed buffers, use debug message
        if not filename:
            self.debug("Cannot track unnamed buffer")
            return

        self.current_session = WritingSession(filename)
        self.current_session.last_content = '\n'.join(vim.current.buffer[:])

        # Record initial position
        line, col = vim.current.window.cursor
        self.current_session.last_position = (line, col)

        # Record session start event
        self.current_session.events.append(
            KeyEvent(
                dt=0,
                pos=line * 1000 + col,
                type='start',
                content='',
                word=self.get_current_word()
            )
        )
        self.debug(f"Session started for {os.path.basename(filename)}") # Added debug message

    def record_mode_change(self, new_mode: VimMode):
        if not self.current_session:
            return

        now = int(time.time() * 1000)
        # Ensure mode exists before calculating duration (robustness)
        if self.current_session.current_mode in self.current_session.mode_durations:
             mode_duration = now - self.current_session.mode_start_time
             self.current_session.mode_durations[self.current_session.current_mode] += mode_duration
        else:
             self.debug(f"Warning: Previous mode {self.current_session.current_mode} not found in durations.")


        # Record the mode change event
        line, col = vim.current.window.cursor
        position = line * 1000 + col

        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=position,
                type='m',
                content=new_mode.value,
                word=self.get_current_word()
            )
        )

        self.debug(f"Mode change: {self.current_session.current_mode.value} -> {new_mode.value}")

        self.current_session.current_mode = new_mode
        self.current_session.mode_start_time = now

    def identify_content_change(self, current_content, last_content, position):
        """Try to intelligently determine what changed in the buffer"""
        # Handle None case for initial state
        if last_content is None:
            return 'k', '+' # Treat initial load as an addition

        if len(current_content) == len(last_content):
            # Could be replacement or complex change, simplifying to 'r'
            # Check if content is actually different to avoid logging no-op changes
            if current_content != last_content:
                 return 'r', '~'
            else:
                 return None, None # Indicate no actual change

        if len(current_content) > len(last_content):
            # Added content
            line, col = position
            try:
                # Get the current lines and previous lines
                current_lines = current_content.split('\n')
                last_lines = last_content.split('\n')

                # Check if new lines were added
                if len(current_lines) > len(last_lines):
                    # Line addition
                    new_lines = len(current_lines) - len(last_lines)
                    return 'k', f"[{new_lines} new lines]"

                # Check if content was added to the current line
                # Ensure line index is valid for both lists
                if 0 < line <= len(current_lines) and 0 < line <= len(last_lines):
                    current_line_str = current_lines[line-1]
                    last_line_str = last_lines[line-1]

                    if len(current_line_str) > len(last_line_str):
                        # Content added to current line
                        # Try to identify the added character if simple insertion at cursor
                        diff_len = len(current_line_str) - len(last_line_str)
                        if col > 0 and col <= len(current_line_str) and current_line_str[:col-diff_len] + current_line_str[col:] == last_line_str:
                           added = current_line_str[col-diff_len:col]
                        elif col >= len(last_line_str):
                            # Added at end
                            added = current_line_str[len(last_line_str):]
                        else:
                            # Added in middle, hard to determine exactly
                            added = '+'
                        return 'k', added
            except Exception as e:
                self.debug(f"Error identifying content addition: {str(e)}")

            return 'k', '+'  # Default: something was added

        else:  # len(current_content) < len(last_content)
            # Removed content
            line, col = position
            try:
                # Get the current lines and previous lines
                current_lines = current_content.split('\n')
                last_lines = last_content.split('\n')

                # Check if lines were removed
                if len(current_lines) < len(last_lines):
                    # Line deletion
                    removed_lines = len(last_lines) - len(current_lines)
                    return 'd', f"[{removed_lines} deleted lines]"

                # Check if content was removed from the current line
                # Ensure line index is valid for both lists
                if 0 < line <= len(current_lines) and 0 < line <= len(last_lines):
                    current_line_str = current_lines[line-1]
                    last_line_str = last_lines[line-1]

                    if len(current_line_str) < len(last_line_str):
                        # Content removed from current line
                        # Simple approximation: mark as deletion
                        return 'd', '-' # Represent character deletion simply
            except Exception as e:
                self.debug(f"Error identifying content deletion: {str(e)}")

            return 'd', '-'  # Default: something was deleted

    def record_keystroke(self):
        if not self.current_session:
            return

        now = int(time.time() * 1000)
        current_content = '\n'.join(vim.current.buffer[:])
        last_content = self.current_session.last_content

        if current_content == last_content:
            # No actual change detected
            return

        # Get cursor position
        line, col = vim.current.window.cursor
        position = (line, col)
        pos_int = line * 1000 + col

        # Determine what changed
        event_type, content = self.identify_content_change(current_content, last_content, position)

        # Only record if identify_content_change detected a change
        if event_type is not None:
            self.current_session.events.append(
                KeyEvent(
                    dt=now - self.current_session.start_time,
                    pos=pos_int,
                    type=event_type,
                    content=content,
                    word=self.get_current_word()
                )
            )
            self.debug(f"Content change: type={event_type}, content='{content}', pos={pos_int}")

        # Update last known state regardless of logging, for next comparison
        self.current_session.last_content = current_content
        self.current_session.last_position = position


    def record_cursor_movement(self):
        if not self.current_session:
            return

        # Get cursor position
        line, col = vim.current.window.cursor
        position = (line, col)
        pos_int = line * 1000 + col

        # Only record if position actually changed
        if self.current_session.last_position == position:
            return

        now = int(time.time() * 1000)
        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=pos_int,
                type='c',
                content='', # Cursor move has no specific content
                word=self.get_current_word()
            )
        )

        self.debug(f"Cursor moved: {self.current_session.last_position} -> {position}")
        self.current_session.last_position = position

    def record_cmdline_enter(self):
        if not self.current_session:
            return

        now = int(time.time() * 1000)

        # Record mode change first
        self.record_mode_change(VimMode.CMDLINE)

        line, col = vim.current.window.cursor
        pos_int = line * 1000 + col

        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=pos_int,
                type='cmd',
                content='enter', # Mark command line entry
                word='' # Word context usually not relevant here
            )
        )

        self.debug("Command line entered")

    def record_cmdline_leave(self):
        if not self.current_session:
            return

        now = int(time.time() * 1000)

        # Record mode change back to normal *first* before getting history
        self.record_mode_change(VimMode.NORMAL)

        # Try to capture the command that was executed
        last_cmd = '' # Default to empty
        try:
            # Get the most recent command history entry
            # histget returns empty string if history is empty or index is out of bounds
            last_cmd = vim.eval('histget(":", -1)')
            self.current_session.last_command = last_cmd
        except Exception as e:
            # vim.error can be raised if e.g. history unavailable
            self.debug(f"Error getting last command: {str(e)}")


        line, col = vim.current.window.cursor
        pos_int = line * 1000 + col

        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=pos_int,
                type='cmd',
                content=last_cmd, # Record the captured command
                word=''
            )
        )

        self.debug(f"Command line left, command: '{last_cmd}'")

    def record_before_save(self):
        if not self.current_session:
            return

        now = int(time.time() * 1000)
        line, col = vim.current.window.cursor
        pos_int = line * 1000 + col

        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=pos_int,
                type='s', # 's' for save event
                content='pre', # Mark as pre-save
                word='' # Word not usually relevant for save event itself
            )
        )

        self.debug("Before save")

    def record_after_save(self):
        if not self.current_session:
            return

        now = int(time.time() * 1000)
        line, col = vim.current.window.cursor
        pos_int = line * 1000 + col

        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=pos_int,
                type='s',
                content='post', # Mark as post-save
                word=''
            )
        )

        self.debug("After save")

    def record_visual_mode_enter(self):
        # No need to check self.current_session, record_mode_change does it
        mode = vim.eval('mode()') # Get the current mode reported by Vim

        # Map Vim's mode() output to our Enum
        vim_mode_map = {
           'v': VimMode.VISUAL,    # Visual characterwise
           'V': VimMode.VISUAL,    # Visual linewise
           '\x16': VimMode.VISUAL, # Visual blockwise (Ctrl-V)
           's': VimMode.SELECT,    # Select characterwise
           'S': VimMode.SELECT,    # Select linewise
           '\x13': VimMode.SELECT, # Select blockwise (Ctrl-S) - less common
           'R': VimMode.REPLACE,   # Replace mode
           'Rv': VimMode.REPLACE,  # Virtual Replace mode
        }

        new_mode = vim_mode_map.get(mode)

        if new_mode:
             self.record_mode_change(new_mode)
             self.debug(f"Specific mode entered: {mode} -> {new_mode.value}")
        else:
             self.debug(f"Unhandled mode change to: {mode}")


    def record_visual_mode_leave(self):
        # Typically leaving Visual/Select/Replace goes back to Normal mode
        self.record_mode_change(VimMode.NORMAL)
        # The previous mode is implicitly captured by the mode duration logic
        self.debug("Visual/Select/Replace mode left (assuming Normal)")

    def end_session(self):
        if not self.current_session:
            return

        # Update final mode duration
        now = int(time.time() * 1000)
        # Ensure robustness if mode somehow not in dict
        if self.current_session.current_mode in self.current_session.mode_durations:
            mode_duration = now - self.current_session.mode_start_time
            self.current_session.mode_durations[self.current_session.current_mode] += mode_duration

        # Record session end event
        line, col = vim.current.window.cursor
        pos_int = line * 1000 + col

        self.current_session.events.append(
            KeyEvent(
                dt=now - self.current_session.start_time,
                pos=pos_int,
                type='end',
                content='',
                word=''
            )
        )

        # Save session log to current directory
        # Sanitize filename slightly in case of weird characters, although basename should be safe
        safe_basename = os.path.basename(self.current_session.filename).replace('/','_').replace('\\','_')
        log_filename = f"{safe_basename}_{self.current_session.start_time}.json"
        log_path = os.path.join(self.current_dir, log_filename)

        try:
            with open(log_path, 'w') as f:
                json.dump(self.current_session.to_dict(), f, indent=2)
        except IOError as e:
             self.debug(f"Error writing log file {log_path}: {e}")
             vim.command(f"echom 'WriteControl Error: Could not write log file {log_path}'")
             # Clear session even if save failed? Or keep trying? For now, clear.
             self.current_session = None
             return


        # Confirmation message
        vim.command(f"echo 'WriteControl: Session log saved: {os.path.basename(log_path)}'")
        self.debug(f"Session ended with {len(self.current_session.events)} events recorded.")
        self.current_session = None

# Create the global WriteControl instance
writecontrol = WriteControl()
EOF

" Autocommands for session control
augroup WriteControl
    autocmd!
    " Trigger session start when a buffer is read/opened
    autocmd BufRead * python3 writecontrol.start_session()

    " Record mode changes accurately
    autocmd InsertEnter * python3 writecontrol.record_mode_change(VimMode.INSERT)
    autocmd InsertLeave * python3 writecontrol.record_mode_change(VimMode.NORMAL)

    " Record text changes (covers typing, pasting, deleting in Insert/Replace)
    autocmd TextChanged,TextChangedI,TextChangedP * python3 writecontrol.record_keystroke()

    " Record cursor movements
    autocmd CursorMoved,CursorMovedI * python3 writecontrol.record_cursor_movement()

    " Record command line usage
    autocmd CmdlineEnter * python3 writecontrol.record_cmdline_enter()
    autocmd CmdlineLeave * python3 writecontrol.record_cmdline_leave()

    " Record entering Visual/Select/Replace modes
    " The pattern *:... means 'any mode before the colon' changing to 'mode(s) after the colon'
    autocmd ModeChanged *:[vV\x16sS\x13R]* python3 writecontrol.record_visual_mode_enter()
    " Record leaving Visual/Select/Replace modes
    " The pattern ...:* means 'mode(s) before the colon' changing to 'any mode after the colon'
    " This is slightly broad, but coupled with record_visual_mode_enter should work.
    autocmd ModeChanged [vV\x16sS\x13R]:* python3 writecontrol.record_visual_mode_leave()

    " Record save events
    autocmd BufWritePre * python3 writecontrol.record_before_save()
    autocmd BufWritePost * python3 writecontrol.record_after_save()

    " End session cleanly when Vim exits
    autocmd VimLeave * python3 writecontrol.end_session()
augroup END

" Commands for manual control
command! StartTracking python3 writecontrol.start_session()
command! StopTracking python3 writecontrol.end_session()
command! ToggleWriteControlDebug let g:writecontrol_debug = !g:writecontrol_debug | python3 writecontrol.debug_mode = bool(g:writecontrol_debug) | echo "WriteControl Debug: " . (g:writecontrol_debug ? "Enabled" : "Disabled")
