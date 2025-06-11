#!/usr/bin/env python3
"""
WriteControl Analytics Script
Analyzes writing session data to provide insights about changes in wordcount,
sentences, paragraphs, and overall editing activity.

Usage:
    wc_analytics.py [log_file] [--all] [--dir DIR]  # Original single-file analysis
    wc_analytics.py analyze <log_file> [--all] [--dir DIR]  # Explicit analyze
    wc_analytics.py process <log_files...>  # Generate commit message
"""

import json
import sys
import os
import re
from datetime import datetime, timedelta
import argparse
from pathlib import Path
import nltk
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
from nltk.tokenize import sent_tokenize

def get_text_metrics(text):
    """Calculate metrics for a given text."""
    if not text:
        return {
            "words": 0,
            "sentences": 0,
            "paragraphs": 0
        }

    # Count paragraphs (non-empty lines)
    paragraphs = [p for p in text.split('\n') if p.strip()]

    # Count sentences
    sentences = sent_tokenize(text)

    # Count words
    words = re.findall(r'\b\w+\b', text)

    return {
        "words": len(words),
        "sentences": len(sentences),
        "paragraphs": len(paragraphs)
    }

def calculate_similarity(text1, text2):
    """
    Calculate a simple similarity percentage between two texts.
    Using Jaccard similarity on the word level.
    """
    if not text1 and not text2:
        return 100.0

    words1 = set(re.findall(r'\b\w+\b', text1.lower()))
    words2 = set(re.findall(r'\b\w+\b', text2.lower()))

    intersection = len(words1.intersection(words2))
    union = len(words1.union(words2))

    if union == 0:
        return 100.0

    return round((intersection / union) * 100, 1)

def format_time(ms):
    """Format milliseconds into a human-readable time string."""
    seconds = ms / 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
    elif minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    else:
        return f"{int(seconds)}s"

def analyze_session(log_path):
    """Analyze a single writing session log file."""
    with open(log_path, 'r') as f:
        session_data = json.load(f)

    filename = session_data['filename']
    base_filename = os.path.basename(filename)
    start_time = session_data['start_time'] / 1000  # Convert to seconds

    # Get events sorted by time
    events = sorted(session_data['events'], key=lambda e: e['dt'])
    session_duration_ms = events[-1]['dt'] if events else 0

    # Extract text at the beginning and end
    initial_content = None
    final_content = None

    for event in events:
        if event['type'] == 'start':
            try:
                with open(filename, 'r') as f:
                    initial_content = f.read()
            except:
                # File might not exist anymore, try to reconstruct from events
                initial_content = ""

    try:
        with open(filename, 'r') as f:
            final_content = f.read()
    except:
        final_content = "File no longer accessible"

    # Calculate metrics
    initial_metrics = get_text_metrics(initial_content)
    final_metrics = get_text_metrics(final_content)

    # Calculate changes
    changes = {
        "words": final_metrics["words"] - initial_metrics["words"],
        "sentences": final_metrics["sentences"] - initial_metrics["sentences"],
        "paragraphs": final_metrics["paragraphs"] - initial_metrics["paragraphs"]
    }

    # Calculate similarity percentage
    similarity = calculate_similarity(initial_content, final_content)
    change_percentage = 100 - similarity

    # Extract mode durations
    mode_durations = session_data.get('mode_durations', {})
    insert_duration_ms = mode_durations.get('i', 0)
    normal_duration_ms = mode_durations.get('n', 0)

    # Count edit events
    edit_events = sum(1 for e in events if e['type'] in ['k', 'd'])

    result = {
        "filename": base_filename,
        "full_path": filename,
        "session_date": datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M'),
        "session_duration_ms": session_duration_ms,
        "session_duration": format_time(session_duration_ms),
        "insert_time": format_time(insert_duration_ms),
        "normal_time": format_time(normal_duration_ms),
        "initial_metrics": initial_metrics,
        "final_metrics": final_metrics,
        "changes": changes,
        "change_percentage": change_percentage,
        "edit_events": edit_events,
        "log_path": log_path
    }

    return result

def find_all_sessions(log_dir, filename=None):
    """Find all session logs for a specific file or all files."""
    logs = []

    for log_file in Path(log_dir).glob("*.json"):
        try:
            with open(log_file, 'r') as f:
                session_data = json.load(f)

            if filename is None or os.path.basename(session_data['filename']) == filename:
                logs.append((session_data['start_time'], str(log_file)))
        except:
            continue

    # Sort by start time
    logs.sort()
    return [log[1] for log in logs]

def accumulate_stats(sessions):
    """Accumulate statistics across multiple sessions."""
    if not sessions:
        return {}

    total_duration_ms = sum(s["session_duration_ms"] for s in sessions)
    total_insert_ms = sum(int(s.get("mode_durations", {}).get("i", 0)) for s in sessions)
    total_words_added = sum(max(0, s["changes"]["words"]) for s in sessions)
    total_edit_events = sum(s["edit_events"] for s in sessions)

    # Calculate words per minute (only counting insert mode time)
    wpm = 0
    if total_insert_ms > 0:
        insert_minutes = total_insert_ms / (1000 * 60)
        wpm = total_words_added / insert_minutes if insert_minutes > 0 else 0

    return {
        "total_sessions": len(sessions),
        "total_duration": format_time(total_duration_ms),
        "total_duration_ms": total_duration_ms,
        "total_insert_time": format_time(total_insert_ms),
        "total_words_added": total_words_added,
        "total_edit_events": total_edit_events,
        "words_per_minute": round(wpm, 1)
    }

def print_session_report(session_data, accumulated_data=None):
    """Print a formatted report for a single session."""
    print("\n" + "="*60)
    print(f"WRITECONTROL SESSION REPORT: {session_data['filename']}")
    print(f"Session date: {session_data['session_date']}")
    print("="*60)

    print("\nSESSION METRICS:")
    print(f"Duration: {session_data['session_duration']}")
    print(f"Time in Insert mode: {session_data.get('insert_time', 'N/A')}")
    print(f"Time in Normal mode: {session_data.get('normal_time', 'N/A')}")
    print(f"Edit events: {session_data['edit_events']}")

    print("\nCONTENT CHANGES:")
    print(f"Words: {session_data['initial_metrics']['words']} → {session_data['final_metrics']['words']} " +
          f"({session_data['changes']['words']:+d})")
    print(f"Sentences: {session_data['initial_metrics']['sentences']} → {session_data['final_metrics']['sentences']} " +
          f"({session_data['changes']['sentences']:+d})")
    print(f"Paragraphs: {session_data['initial_metrics']['paragraphs']} → {session_data['final_metrics']['paragraphs']} " +
          f"({session_data['changes']['paragraphs']:+d})")

    print(f"\nText changed: {session_data['change_percentage']:.1f}%")

    if accumulated_data:
        print("\n" + "-"*60)
        print("ACCUMULATED STATS ACROSS ALL SESSIONS:")
        print(f"Total sessions: {accumulated_data['total_sessions']}")
        print(f"Total writing time: {accumulated_data['total_duration']}")
        print(f"Total words added: {accumulated_data['total_words_added']}")
        print(f"Words per minute: {accumulated_data['words_per_minute']}")
        print("-"*60)

def generate_commit_message(file_sessions):
    """Generate a descriptive commit message from session data"""

    if not file_sessions:
        return None

    # Single file
    if len(file_sessions) == 1:
        filename, sessions = list(file_sessions.items())[0]
        base_name = os.path.basename(filename)

        # Aggregate stats
        total_words = sum(s['changes']['words'] for s in sessions)
        total_duration_ms = sum(s['session_duration_ms'] for s in sessions)

        # Special handling for new files
        if all(s['initial_metrics']['words'] == 0 for s in sessions):
            return f"New file {base_name}: {sessions[-1]['final_metrics']['words']} words, {format_time(total_duration_ms)}"

        # Format message based on changes
        if total_words > 0:
            msg = f"Edit {base_name}: +{total_words} words"
        elif total_words < 0:
            msg = f"Edit {base_name}: {total_words} words"
        else:
            # No word change, check for other changes
            avg_change_pct = sum(s['change_percentage'] for s in sessions) / len(sessions)
            if avg_change_pct > 30:
                msg = f"Revise {base_name}: {int(avg_change_pct)}% changed"
            else:
                msg = f"Edit {base_name}"

        # Add duration if significant
        if total_duration_ms > 300000:  # 5 minutes
            msg += f", {format_time(total_duration_ms)}"

        return msg

    # Multiple files
    else:
        file_count = len(file_sessions)
        total_words = sum(sum(s['changes']['words'] for s in sessions)
                         for sessions in file_sessions.values())
        total_duration_ms = sum(sum(s['session_duration_ms'] for s in sessions)
                               for sessions in file_sessions.values())

        # Create file summary
        file_summaries = []
        for filename, sessions in file_sessions.items():
            base_name = os.path.basename(filename)
            words_change = sum(s['changes']['words'] for s in sessions)
            if words_change != 0:
                file_summaries.append(f"{base_name} ({words_change:+d}w)")

        # Build message
        if file_summaries and len(file_summaries) <= 3:
            msg = f"Edit {', '.join(file_summaries)}"
        else:
            msg = f"Edit {file_count} files"
            if total_words > 0:
                msg += f": +{total_words} words"
            elif total_words < 0:
                msg += f": {total_words} words"

        # Add total duration if significant
        if total_duration_ms > 300000:  # 5 minutes
            msg += f", {format_time(total_duration_ms)}"

        return msg

def process_logs_for_commit(log_files):
    """Process multiple log files and generate a commit message"""

    file_sessions = {}

    for log_file in log_files:
        try:
            session = analyze_session(log_file)
            filename = session['full_path']

            if filename not in file_sessions:
                file_sessions[filename] = []
            file_sessions[filename].append(session)
        except Exception as e:
            # Skip files that can't be processed
            continue

    return generate_commit_message(file_sessions)

def main():
    parser = argparse.ArgumentParser(description='Analyze WriteControl session logs')

    # Check if first argument looks like a subcommand
    if len(sys.argv) > 1 and sys.argv[1] in ['analyze', 'process']:
        # Use subcommands
        subparsers = parser.add_subparsers(dest='command', help='Commands')

        # Analyze subcommand
        analyze_parser = subparsers.add_parser('analyze', help='Analyze a single session')
        analyze_parser.add_argument('log_file', help='Path to the session log file')
        analyze_parser.add_argument('--all', action='store_true', help='Analyze all sessions for this file')
        analyze_parser.add_argument('--dir', help='Custom log directory path')

        # Process subcommand
        process_parser = subparsers.add_parser('process', help='Process logs for commit message')
        process_parser.add_argument('log_files', nargs='+', help='Log files to process')

        args = parser.parse_args()
    else:
        # Backward compatibility - no subcommand
        parser.add_argument('log_file', nargs='?', help='Path to the session log file')
        parser.add_argument('--all', action='store_true', help='Analyze all sessions for this file')
        parser.add_argument('--dir', help='Custom log directory path')
        args = parser.parse_args()
        args.command = None

    # Handle process command
    if args.command == 'process':
        commit_msg = process_logs_for_commit(args.log_files)
        if commit_msg:
            print(f"Commit message: {commit_msg}")
        return 0

    # Handle analyze command or backward compatibility mode
    # Determine log directory
    if hasattr(args, 'dir') and args.dir:
        log_dir = args.dir
    else:
        xdg_state_home = os.getenv('XDG_STATE_HOME')
        if not xdg_state_home:
            xdg_state_home = os.path.join(os.path.expanduser('~'), '.local', 'state')
        log_dir = os.path.join(xdg_state_home, 'writecontrol', 'current')

    if not os.path.exists(log_dir):
        print(f"Error: Log directory {log_dir} does not exist")
        return 1

    if hasattr(args, 'log_file') and args.log_file:
        if not os.path.exists(args.log_file):
            print(f"Error: Log file {args.log_file} does not exist")
            return 1

        log_path = args.log_file
        session_data = analyze_session(log_path)

        if args.all:
            # Find all sessions for this file
            with open(log_path, 'r') as f:
                file_data = json.load(f)
                target_filename = os.path.basename(file_data['filename'])

            all_logs = find_all_sessions(log_dir, target_filename)
            all_sessions = [analyze_session(log) for log in all_logs]
            accumulated_data = accumulate_stats(all_sessions)
            print_session_report(session_data, accumulated_data)
        else:
            print_session_report(session_data)
    else:
        # If no log file specified, analyze most recent log
        all_logs = find_all_sessions(log_dir)
        if not all_logs:
            print("No log files found")
            return 1

        latest_log = all_logs[-1]
        session_data = analyze_session(latest_log)

        # Find all sessions for this file
        target_filename = os.path.basename(session_data['filename'])
        related_logs = find_all_sessions(log_dir, target_filename)
        all_sessions = [analyze_session(log) for log in related_logs]
        accumulated_data = accumulate_stats(all_sessions)

        print_session_report(session_data, accumulated_data)

    return 0

if __name__ == "__main__":
    sys.exit(main())
