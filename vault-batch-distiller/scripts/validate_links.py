#!/usr/bin/env python3
"""Validate all [[wikilinks]] in a study note hit real .md files in source dir."""
import os, re, glob, argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", required=True, help="path to study note .md")
    parser.add_argument("--src", required=True, help="source directory with original .md files")
    args = parser.parse_args()

    actual = {
        os.path.splitext(os.path.basename(f))[0]
        for f in glob.glob(os.path.join(args.src, "*.md"))
    }
    s = open(args.note, encoding="utf-8", errors="ignore").read()
    s_clean = re.sub(r'`[^`]*`', '', s)
    links = re.findall(r'\[\[([^\]]+)\]\]', s_clean)
    dead = [L for L in sorted(set(links)) if L not in actual]

    print(f"links: {len(set(links))} unique, dead: {len(dead)}")
    for L in dead:
        print(f"  DEAD: {L}")
    if dead:
        exit(1)
    print("OK: 0 dead links")


if __name__ == "__main__":
    main()
