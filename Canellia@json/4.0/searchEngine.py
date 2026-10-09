"""Filesystem traversal independent of GTK, with cancellation and cycle detection."""
import os
import re


def compile_matcher(key, regex=False):
    if regex:
        expression = re.compile(key)
        return lambda name: expression.search(name) is not None
    folded = key.casefold()
    return lambda name: folded in name.casefold()


def search_files(directory, matcher, hidden=False, follow_symlinks=False,
                 cancel=None, on_error=None):
    if not directory or not os.path.isdir(directory):
        raise ValueError('Select an existing search folder')
    pending = [os.path.abspath(directory)]
    visited = set()
    while pending:
        if cancel is not None and cancel.is_set():
            return
        current = pending.pop()
        real = os.path.realpath(current)
        if real in visited:
            continue
        visited.add(real)
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if cancel is not None and cancel.is_set():
                        return
                    if not hidden and entry.name.startswith('.'):
                        continue
                    try:
                        is_directory = entry.is_dir()
                        if matcher(entry.name):
                            yield entry.name, current, is_directory
                        if is_directory and (follow_symlinks or not entry.is_symlink()):
                            pending.append(entry.path)
                    except OSError as error:
                        if on_error is not None:
                            on_error(str(error))
        except OSError as error:
            if on_error is not None:
                on_error(str(error))
