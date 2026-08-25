#!/usr/bin/env python3
"""
Patch Codex model catalog so combo/mm-m3 reports image input capability.

Why this exists:
  `ocx sync` regenerates ~/.codex/cc-switch-model-catalog.json from the
  minimax-cn provider, which has no image-modal metadata. Codex desktop
  reads `input_modalities` to decide whether the screenshot/paste-image
  affordance is enabled, so without this patch M3 looks text-only.

Usage:
  python3 patch-mm3-vision.py            # patch in place (idempotent)
  python3 patch-mm3-vision.py --check    # exit 0 if already patched, 1 otherwise
  python3 patch-mm3-vision.py --restore  # remove the vision alias + revert mm-m3
"""
from __future__ import annotations
import argparse, copy, json, sys
from pathlib import Path

CATALOG = Path.home() / '.codex' / 'cc-switch-model-catalog.json'

def load():
    return json.loads(CATALOG.read_text())

def save(d):
    CATALOG.write_text(json.dumps(d, indent=2, ensure_ascii=False))

def find_mm3(models):
    for m in models:
        if m.get('slug') == 'combo/mm-m3':
            return m
    return None

def find_vision(models):
    for m in models:
        if m.get('slug') == 'combo/mm-m3-vision':
            return m
    return None

def patched(models):
    mm3 = find_mm3(models)
    vis = find_vision(models)
    return bool(mm3 and vis and 'image' in (mm3.get('input_modalities') or []))

def apply_patch():
    d = load()
    mm3 = find_mm3(d['models'])
    if not mm3:
        print('combo/mm-m3 not found in catalog — nothing to patch', file=sys.stderr)
        return False
    mm3['input_modalities'] = ['text', 'image']
    mm3['description'] = (
        'Routed via opencodex → minimax-cn/MiniMax-M3. '
        'Multimodal: supports image input.'
    )
    mm3['priority'] = 4
    new_models = []
    inserted = False
    for m in d['models']:
        new_models.append(m)
        if m.get('slug') == 'combo/mm-m3' and not find_vision(d['models']):
            vision = copy.deepcopy(m)
            vision['slug'] = 'combo/mm-m3-vision'
            vision['display_name'] = 'MM-M3-Vision'
            vision['priority'] = 3
            new_models.append(vision)
            inserted = True
    d['models'] = new_models
    save(d)
    return inserted

def restore():
    d = load()
    d['models'] = [m for m in d['models'] if m.get('slug') != 'combo/mm-m3-vision']
    for m in d['models']:
        if m.get('slug') == 'combo/mm-m3':
            m['input_modalities'] = ['text']
            m['priority'] = 5
            m['description'] = 'Routed via opencodex → combo (combo).'
    save(d)

def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument('--check', action='store_true', help='exit 0 if already patched')
    g.add_argument('--restore', action='store_true', help='revert patch')
    args = p.parse_args()
    d = load()
    if args.check:
        return 0 if patched(d['models']) else 1
    if args.restore:
        restore()
        print('Restored.')
        return 0
    inserted = apply_patch()
    if inserted:
        print('Patched. Added combo/mm-m3-vision alias + enabled image on mm-m3.')
    elif patched(d['models']):
        print('Already patched — no change.')
    else:
        print('Patch applied (idempotent).', file=sys.stderr)
    return 0

if __name__ == '__main__':
    sys.exit(main())
