"""Duplicate file finder.

Looks for files with the same content, even if the names are different.
To keep it fast it compares size first, then the first 64 KB, and only
then the whole file.
"""
import argparse
import hashlib
import importlib
import os
import sys
from collections import defaultdict

CHUNK_SIZE = 64 * 1024  # read files 64 KB at a time


def load_package(name, pip_name=None):
    # only import the extra packages when they are really needed
    try:
        return importlib.import_module(name)
    except ImportError:
        sys.exit(f"The package '{pip_name or name}' is missing. "
                 "Run: pip install -r requirements.txt")


def scan_files(root):
    """Yield (path, size) for every non-empty file under root."""
    for folder, _, names in os.walk(str(root)):
        for name in names:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue  # skip shortcuts so we never loop
            try:
                size = os.path.getsize(path)
            except OSError:
                continue  # can't read it, ignore
            if size > 0:
                yield path, size


def hash_file(path, partial=False):
    """SHA-256 of a file. partial=True only looks at the first 64 KB."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        if partial:
            digest.update(f.read(CHUNK_SIZE))
        else:
            while True:
                block = f.read(CHUNK_SIZE)
                if not block:
                    break
                digest.update(block)
    return digest.hexdigest()


def _regroup(groups, key_fn):
    # split each group again using key_fn, drop anything left alone
    result = defaultdict(list)
    for paths in groups:
        if len(paths) < 2:
            continue
        for path in paths:
            try:
                result[key_fn(path)].append(path)
            except OSError:
                pass
    return list(result.values())


def find_duplicates(root):
    by_size = defaultdict(list)
    for path, size in scan_files(root):
        by_size[size].append(path)

    # same size and same start
    groups = _regroup(
        by_size.values(),
        lambda p: (os.path.getsize(p), hash_file(p, partial=True)),
    )
    # same whole file
    groups = _regroup(groups, hash_file)

    return [g for g in groups if len(g) > 1]


def choose_keeper(group, rule="oldest"):
    if rule == "oldest":
        return min(group, key=os.path.getmtime)
    if rule == "shortest_path":
        return min(group, key=len)
    return group[0]


def clean_group(group, rule="oldest", dry_run=True):
    keeper = choose_keeper(group, rule)
    for path in group:
        if path == keeper:
            continue
        if dry_run:
            print(f"   [preview] would remove: {path}")
            continue
        load_package("send2trash").send2trash(path)
        print(f"   moved to Recycle Bin: {path}")
    return keeper


def image_hash(path):
    image_module = load_package("PIL.Image", "pillow")
    imagehash = load_package("imagehash")
    with image_module.open(path) as img:
        return imagehash.phash(img)


def are_similar(h1, h2, threshold=5):
    return (h1 - h2) <= threshold  # small difference = similar picture


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{int(size)} bytes"
            return f"{size:.1f} {unit}"
        size /= 1024


def ask_for_folder():
    # used when the program is run without a folder (like the Run button)
    answer = input("Enter the folder to scan: ")
    return answer.strip().strip('"').strip("'")


def read_options():
    parser = argparse.ArgumentParser(
        description="Find files with identical content and optionally remove extras."
    )
    parser.add_argument("root", nargs="?",
                        help="folder to scan (asked for if left out)")
    parser.add_argument("--clean", action="store_true",
                        help="handle the duplicates, keeping one file per group")
    parser.add_argument("--rule", default="oldest",
                        choices=["oldest", "shortest_path"],
                        help="which file to keep (default: oldest)")
    parser.add_argument("--yes", action="store_true",
                        help="really remove the extra copies (default: preview only)")
    return parser.parse_args()


def main():
    options = read_options()
    root = options.root or ask_for_folder()

    if not os.path.isdir(root):
        sys.exit(f"'{root}' is not a folder.")

    print(f"Scanning {root} ...")
    groups = find_duplicates(root)

    extra_copies = 0
    wasted_bytes = 0
    for number, group in enumerate(groups, start=1):
        each = os.path.getsize(group[0])
        print(f"\nGroup {number} ({len(group)} files, {format_size(each)} each)")
        for path in group:
            print("  ", path)
        extra_copies += len(group) - 1
        wasted_bytes += each * (len(group) - 1)
        if options.clean:
            keeper = clean_group(group, options.rule, dry_run=not options.yes)
            print(f"   keeping: {keeper}")

    print("\n" + "-" * 40)
    if not groups:
        print("No duplicate files found.")
        return
    print(f"Duplicate groups : {len(groups)}")
    print(f"Extra copies     : {extra_copies}")
    print(f"Space that can be freed: {format_size(wasted_bytes)}")
    if options.clean and not options.yes:
        print("This was only a preview. "
              "Add --yes to move the extra copies to the Recycle Bin.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped by the user.")
