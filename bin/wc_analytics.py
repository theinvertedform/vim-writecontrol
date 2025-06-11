#!/usr/bin/env python3
"""
WriteControl Analytics Script
Analyzes writing session data by reconstructing document state from recorded events.

Usage:
    wc-analytics.py analyze <log_file> [--all] [--dir DIR]
    wc-analytics.py process <log_files...>
    wc-analytics.py summary [--filename FILE] [--dir DIR]
    wc-analytics.py list [--dir DIR] [--sort words|duration|date]
"""

import json
import sys
import os
import re
from datetime import datetime
import argparse
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

def parse_position(pos: int) -> Tuple[int, int]:
    """Convert encoded position back to (line, col)"""
    return (pos // 1000, pos % 1000)

def encode_position(line: int, col: int) -> int:
    """Encode (line, col) to single int"""
    return line * 1000 + col

class DocumentState:
    """Maintains document state and applies events"""

    def __init__(self, initial_content: str = ""):
        self.lines = initial_content.split('\n') if initial_content else ['']
        self.cursor_line = 1
        self.cursor_col = 0

    def get_content(self) -> str:
        return '\n'.join(self.lines)

    def set_cursor(self, line: int, col: int):
        """Update cursor position (1-based line, 0-based col)"""
        self.cursor_line = max(1, min(line, len(self.lines)))
        line_len = len(self.lines[self.cursor_line - 1])
        self.cursor_col = max(0, min(col, line_len))

    def apply_keystroke(self, content: str):
        """Apply keystroke at current position"""
        if not content:
            return

        line_idx = self.cursor_line - 1
        line = self.lines[line_idx]

        # Handle special content markers
        if content.startswith('[') and content.endswith(']'):
            # Multi-line additions like "[3 new lines]"
            match = re.match(r'\[(\d+) new lines?\]', content)
            if match:
                new_line_count = int(match.group(1))
                # Insert new lines after current
                for _ in range(new_line_count):
                    self.lines.insert(line_idx + 1, '')
                self.cursor_line += 1
                self.cursor_col = 0
                return

        # Handle newline
        if content == '\n' or content == '\r\n':
            # Split current line at cursor
            before = line[:self.cursor_col]
            after = line[self.cursor_col:]
            self.lines[line_idx] = before
            self.lines.insert(line_idx + 1, after)
            self.cursor_line += 1
            self.cursor_col = 0
        else:
            # Insert content at cursor position
            new_line = line[:self.cursor_col] + content + line[self.cursor_col:]
            self.lines[line_idx] = new_line
            self.cursor_col += len(content)

    def apply_deletion(self, content: str):
        """Apply deletion at current position"""
        if not content:
            return

        line_idx = self.cursor_line - 1

        # Handle special deletion markers
        if content.startswith('[') and content.endswith(']'):
            match = re.match(r'\[(\d+) deleted lines?\]', content)
            if match:
                del_count = int(match.group(1))
                # Delete lines starting from current
                for _ in range(min(del_count, len(self.lines) - line_idx)):
                    if line_idx < len(self.lines):
                        del self.lines[line_idx]
                # Adjust cursor
                if line_idx >= len(self.lines):
                    self.cursor_line = len(self.lines)
                    self.cursor_col = len(self.lines[-1]) if self.lines else 0
                return

        # Single character deletion (backspace/delete)
        line = self.lines[line_idx]
        if self.cursor_col > 0:
            # Backspace
            new_line = line[:self.cursor_col-1] + line[self.cursor_col:]
            self.lines[line_idx] = new_line
            self.cursor_col -= 1
        elif self.cursor_line > 1:
            # Join with previous line
            prev_line = self.lines[line_idx - 1]
            self.lines[line_idx - 1] = prev_line + line
            del self.lines[line_idx]
            self.cursor_line -= 1
            self.cursor_col = len(prev_line)

def reconstruct_session(events: List[Dict], initial_content: str = "") -> Dict[str, DocumentState]:
    """Reconstruct document states from events"""
    states = {}
    doc = DocumentState(initial_content)

    # Store initial state
    states['initial'] = DocumentState(initial_content)

    for event in events:
        event_type = event['type']
        pos = event.get('pos', 0)
        content = event.get('content', '')

        # Update cursor position if changed
        if pos > 0:
            line, col = parse_position(pos)
            doc.set_cursor(line, col)

        # Apply event
        if event_type == 'k':  # Keystroke
            doc.apply_keystroke(content)
        elif event_type == 'd':  # Deletion
            doc.apply_deletion(content)
        elif event_type == 's' and content == 'pre':
            # Snapshot state before save
            states['pre_save'] = DocumentState(doc.get_content())
        elif event_type == 'end':
            # Final state
            states['final'] = DocumentState(doc.get_content())

    # Ensure we have final state
    if 'final' not in states:
        states['final'] = doc

    return states

def get_text_metrics(text: str) -> Dict[str, int]:
    """Calculate metrics for given text"""
    if not text:
        return {"words": 0, "sentences": 0, "paragraphs": 0}

    # Count non-empty paragraphs
    paragraphs = [p for p in text.split('\n') if p.strip()]

    # Count sentences (simple regex)
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if s.strip()]

    # Count words
    words = re.findall(r'\b\w+\b', text)

    return {
        "words": len(words),
        "sentences": len(sentences),
        "paragraphs": len(paragraphs)
    }

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity between texts"""
    if not text1 and not text2:
        return 100.0

    words1 = set(re.findall(r'\b\w+\b', text1.lower()))
    words2 = set(re.findall(r'\b\w+\b', text2.lower()))

    if not words1 and not words2:
        return 100.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return round((intersection / union) * 100, 1) if union > 0 else 100.0

def format_time(ms: int) -> str:
    """Format milliseconds to human readable"""
    seconds = ms / 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    elif minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        return f"{seconds:.1f}s"

def analyze_session(log_path: str) -> Optional[Dict]:
    """Analyze a single session log"""
    try:
        with open(log_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {log_path}: {e}")
        return None

    filename = data['filename']
    base_filename = os.path.basename(filename)
    start_time = data['start_time'] / 1000

    events = sorted(data['events'], key=lambda e: e['dt'])
    if not events:
        return None

    session_duration_ms = events[-1]['dt']

    # Try to get initial content from file or use empty
    initial_content = ""
    try:
        # Only use file content if it exists and session is recent
        if os.path.exists(filename):
            file_mtime = os.path.getmtime(filename)
            session_end_time = start_time + (session_duration_ms / 1000)
            # If file was modified within an hour of session end, might be reliable
            if abs(file_mtime - session_end_time) < 3600:
                with open(filename, 'r') as f:
                    initial_content = f.read()
    except:
        pass

    # Reconstruct states from events
    states = reconstruct_session(events, initial_content)

    initial_text = states['initial'].get_content()
    final_text = states['final'].get_content()

    # Calculate metrics
    initial_metrics = get_text_metrics(initial_text)
    final_metrics = get_text_metrics(final_text)

    changes = {
        "words": final_metrics["words"] - initial_metrics["words"],
        "sentences": final_metrics["sentences"] - initial_metrics["sentences"],
        "paragraphs": final_metrics["paragraphs"] - initial_metrics["paragraphs"]
    }

    similarity = calculate_similarity(initial_text, final_text)
    change_percentage = 100 - similarity

    # Mode durations
    mode_durations = data.get('mode_durations', {})

    # Count different event types
    event_counts = defaultdict(int)
    for event in events:
        event_counts[event['type']] += 1

    # Calculate typing speed in insert mode
    insert_ms = mode_durations.get('i', 0)
    keystroke_count = event_counts.get('k', 0)
    typing_speed = 0
    if insert_ms > 0 and keystroke_count > 0:
        typing_speed = keystroke_count / (insert_ms / 60000)  # keystrokes per minute

    return {
        "filename": base_filename,
        "full_path": filename,
        "session_date": datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M'),
        "session_duration_ms": session_duration_ms,
        "session_duration": format_time(session_duration_ms),
        "mode_durations": mode_durations,
        "insert_time": format_time(mode_durations.get('i', 0)),
        "normal_time": format_time(mode_durations.get('n', 0)),
        "initial_metrics": initial_metrics,
        "final_metrics": final_metrics,
        "changes": changes,
        "change_percentage": change_percentage,
        "event_counts": dict(event_counts),
        "typing_speed": round(typing_speed, 1),
        "log_path": log_path
    }

def find_sessions(log_dir: str, filename: Optional[str] = None) -> List[str]:
    """Find session logs, optionally filtered by filename"""
    logs = []

    for log_file in Path(log_dir).glob("*.json"):
        if filename:
            try:
                with open(log_file, 'r') as f:
                    data = json.load(f)
                if os.path.basename(data['filename']) != filename:
                    continue
            except:
                continue

        logs.append(str(log_file))

    # Sort by modification time
    logs.sort(key=lambda x: os.path.getmtime(x))
    return logs

def print_session_report(session: Dict, accumulated: Optional[Dict] = None):
    """Print formatted session report"""
    print("\n" + "="*60)
    print(f"WRITECONTROL SESSION REPORT: {session['filename']}")
    print(f"Session date: {session['session_date']}")
    print("="*60)

    print("\nSESSION METRICS:")
    print(f"Duration: {session['session_duration']}")
    print(f"Insert mode: {session['insert_time']}")
    print(f"Normal mode: {session['normal_time']}")
    print(f"Typing speed: {session['typing_speed']} keystrokes/min")

    print("\nEVENT COUNTS:")
    for event_type, count in sorted(session['event_counts'].items()):
        event_names = {
            'k': 'Keystrokes',
            'd': 'Deletions',
            'c': 'Cursor moves',
            'm': 'Mode changes',
            's': 'Saves',
            'cmd': 'Commands'
        }
        print(f"  {event_names.get(event_type, event_type)}: {count}")

    print("\nCONTENT CHANGES:")
    print(f"Words: {session['initial_metrics']['words']} → {session['final_metrics']['words']} ({session['changes']['words']:+d})")
    print(f"Sentences: {session['initial_metrics']['sentences']} → {session['final_metrics']['sentences']} ({session['changes']['sentences']:+d})")
    print(f"Paragraphs: {session['initial_metrics']['paragraphs']} → {session['final_metrics']['paragraphs']} ({session['changes']['paragraphs']:+d})")
    print(f"\nText similarity: {100 - session['change_percentage']:.1f}% (changed: {session['change_percentage']:.1f}%)")

    if accumulated:
        print("\n" + "-"*60)
        print("ACCUMULATED STATS:")
        print(f"Total sessions: {accumulated['total_sessions']}")
        print(f"Total time: {accumulated['total_duration']}")
        print(f"Total words written: {accumulated['total_words_added']}")
        print(f"Average typing speed: {accumulated['avg_typing_speed']:.1f} keystrokes/min")

def generate_commit_message(file_sessions: Dict[str, List[Dict]]) -> str:
    """Generate commit message from sessions"""
    if not file_sessions:
        return "Update"

    # Single file
    if len(file_sessions) == 1:
        filename, sessions = list(file_sessions.items())[0]
        base_name = os.path.basename(filename)

        total_words = sum(s['changes']['words'] for s in sessions)
        total_duration_ms = sum(s['session_duration_ms'] for s in sessions)

        # New file
        if all(s['initial_metrics']['words'] == 0 for s in sessions):
            final_words = sessions[-1]['final_metrics']['words']
            return f"New file {base_name}: {final_words} words, {format_time(total_duration_ms)}"

        # Edited file
        if total_words > 0:
            msg = f"Edit {base_name}: +{total_words} words"
        elif total_words < 0:
            msg = f"Edit {base_name}: {total_words} words"
        else:
            avg_change = sum(s['change_percentage'] for s in sessions) / len(sessions)
            if avg_change > 30:
                msg = f"Revise {base_name}: {int(avg_change)}% changed"
            else:
                msg = f"Edit {base_name}"

        if total_duration_ms > 300000:  # 5+ minutes
            msg += f", {format_time(total_duration_ms)}"

        return msg

    # Multiple files
    file_count = len(file_sessions)
    total_words = sum(sum(s['changes']['words'] for s in sessions) for sessions in file_sessions.values())
    total_duration_ms = sum(sum(s['session_duration_ms'] for s in sessions) for sessions in file_sessions.values())

    # Short summary for 3 or fewer files
    if file_count <= 3:
        summaries = []
        for filename, sessions in file_sessions.items():
            base_name = os.path.basename(filename)
            words = sum(s['changes']['words'] for s in sessions)
            if words != 0:
                summaries.append(f"{base_name} ({words:+d}w)")

        if summaries:
            msg = f"Edit {', '.join(summaries)}"
        else:
            msg = f"Edit {file_count} files"
    else:
        msg = f"Edit {file_count} files"
        if total_words > 0:
            msg += f": +{total_words} words"
        elif total_words < 0:
            msg += f": {total_words} words"

    if total_duration_ms > 300000:
        msg += f", {format_time(total_duration_ms)}"

    return msg

def cmd_analyze(args):
    """Analyze command"""
    session = analyze_session(args.log_file)
    if not session:
        return 1

    if args.all:
        # Get log directory
        log_dir = os.path.dirname(args.log_file)
        target_file = os.path.basename(session['full_path'])

        all_logs = find_sessions(log_dir, target_file)
        all_sessions = []
        for log in all_logs:
            s = analyze_session(log)
            if s:
                all_sessions.append(s)

        # Accumulate stats
        if all_sessions:
            total_duration_ms = sum(s['session_duration_ms'] for s in all_sessions)
            total_words_added = sum(max(0, s['changes']['words']) for s in all_sessions)
            total_keystrokes = sum(s['event_counts'].get('k', 0) for s in all_sessions)
            total_insert_ms = sum(s['mode_durations'].get('i', 0) for s in all_sessions)

            avg_speed = 0
            if total_insert_ms > 0:
                avg_speed = total_keystrokes / (total_insert_ms / 60000)

            accumulated = {
                'total_sessions': len(all_sessions),
                'total_duration': format_time(total_duration_ms),
                'total_words_added': total_words_added,
                'avg_typing_speed': avg_speed
            }

            print_session_report(session, accumulated)
        else:
            print_session_report(session)
    else:
        print_session_report(session)

    return 0

def cmd_process(args):
    """Process command for commit messages"""
    file_sessions = defaultdict(list)

    for log_file in args.log_files:
        session = analyze_session(log_file)
        if session:
            file_sessions[session['full_path']].append(session)

    msg = generate_commit_message(dict(file_sessions))
    print(f"Commit message: {msg}")
    return 0

def cmd_summary(args):
    """Summary command"""
    log_dir = args.dir or get_default_log_dir()

    logs = find_sessions(log_dir, args.filename)
    if not logs:
        print("No sessions found")
        return 1

    # Group by file
    file_stats = defaultdict(lambda: {
        'sessions': 0,
        'total_duration_ms': 0,
        'total_words': 0,
        'total_keystrokes': 0
    })

    for log in logs:
        session = analyze_session(log)
        if session:
            stats = file_stats[session['filename']]
            stats['sessions'] += 1
            stats['total_duration_ms'] += session['session_duration_ms']
            stats['total_words'] += session['changes']['words']
            stats['total_keystrokes'] += session['event_counts'].get('k', 0)

    # Print summary
    print("\nWRITECONTROL SUMMARY")
    print("="*60)

    for filename, stats in sorted(file_stats.items()):
        print(f"\n{filename}:")
        print(f"  Sessions: {stats['sessions']}")
        print(f"  Total time: {format_time(stats['total_duration_ms'])}")
        print(f"  Words change: {stats['total_words']:+d}")
        print(f"  Keystrokes: {stats['total_keystrokes']}")

    return 0

def cmd_list(args):
    """List tracked files"""
    log_dir = args.dir or get_default_log_dir()
    logs = find_sessions(log_dir)

    if not logs:
        print("No sessions found")
        return 1

    # Collect file stats
    file_data = defaultdict(lambda: {
        'sessions': [],
        'first_seen': None,
        'last_seen': None,
        'total_duration_ms': 0,
        'total_words': 0
    })

    for log in logs:
        session = analyze_session(log)
        if session:
            data = file_data[session['filename']]
            session_time = datetime.strptime(session['session_date'], '%Y-%m-%d %H:%M')

            data['sessions'].append(session)
            data['total_duration_ms'] += session['session_duration_ms']
            data['total_words'] += session['changes']['words']

            if not data['first_seen'] or session_time < data['first_seen']:
                data['first_seen'] = session_time
            if not data['last_seen'] or session_time > data['last_seen']:
                data['last_seen'] = session_time

    # Sort files
    items = list(file_data.items())
    if args.sort == 'words':
        items.sort(key=lambda x: abs(x[1]['total_words']), reverse=True)
    elif args.sort == 'duration':
        items.sort(key=lambda x: x[1]['total_duration_ms'], reverse=True)
    else:  # date
        items.sort(key=lambda x: x[1]['last_seen'], reverse=True)

    # Print list
    print("\nTRACKED FILES")
    print("="*80)
    print(f"{'File':<30} {'Sessions':<10} {'Duration':<15} {'Words':<10} {'Last Edited'}")
    print("-"*80)

    for filename, data in items:
        print(f"{filename[:30]:<30} {len(data['sessions']):<10} "
              f"{format_time(data['total_duration_ms']):<15} "
              f"{data['total_words']:+d}".ljust(10) + " "
              f"{data['last_seen'].strftime('%Y-%m-%d')}")

    return 0

def get_default_log_dir():
    """Get default log directory"""
    xdg_state = os.getenv('XDG_STATE_HOME', os.path.expanduser('~/.local/state'))
    return os.path.join(xdg_state, 'writecontrol', 'current')

def main():
    parser = argparse.ArgumentParser(description='WriteControl Analytics')
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze session log')
    analyze_parser.add_argument('log_file', help='Path to log file')
    analyze_parser.add_argument('--all', action='store_true', help='Show all sessions for this file')

    # Process command
    process_parser = subparsers.add_parser('process', help='Generate commit message')
    process_parser.add_argument('log_files', nargs='+', help='Log files to process')

    # Summary command
    summary_parser = subparsers.add_parser('summary', help='Show summary statistics')
    summary_parser.add_argument('--filename', help='Filter by filename')
    summary_parser.add_argument('--dir', help='Log directory')

    # List command
    list_parser = subparsers.add_parser('list', help='List tracked files')
    list_parser.add_argument('--dir', help='Log directory')
    list_parser.add_argument('--sort', choices=['date', 'words', 'duration'], default='date')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to command
    if args.command == 'analyze':
        return cmd_analyze(args)
    elif args.command == 'process':
        return cmd_process(args)
    elif args.command == 'summary':
        return cmd_summary(args)
    elif args.command == 'list':
        return cmd_list(args)

    return 0

if __name__ == "__main__":
    sys.exit(main())
