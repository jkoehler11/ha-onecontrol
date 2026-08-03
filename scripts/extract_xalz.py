#!/usr/bin/env python3
from pathlib import Path
import lz4.block

BLOB = Path('/tmp/onecontrol_blob/libassemblies.arm64-v8a.blob.so')
OUTDIR = Path(__file__).resolve().parent.parent / 'extracted_assemblies'
OUTDIR.mkdir(parents=True, exist_ok=True)

data = BLOB.read_bytes()

# find assembly name table start by scanning for a long run
best_start = None
best_count = 0
for candidate in range(30000, 47000):
    pos = candidate
    count = 0
    while pos + 4 < len(data):
        length = int.from_bytes(data[pos:pos+4], 'little')
        if length <= 0 or length > 240 or pos+4+length > len(data):
            break
        name = data[pos+4:pos+4+length]
        if b'.dll' not in name and b'.exe' not in name and b'.resources' not in name:
            break
        count += 1
        pos += 4 + length
    if count > best_count:
        best_count = count
        best_start = candidate

if best_start is None:
    raise SystemExit('assembly table not found')

# parse entries
entries = []
pos = best_start
while pos + 4 < len(data):
    length = int.from_bytes(data[pos:pos+4], 'little')
    if length <= 0 or length > 1024 or pos+4+length > len(data):
        break
    name = data[pos+4:pos+4+length].decode('ascii', errors='replace')
    entries.append(name)
    pos += 4 + length

print('assembly count', len(entries), 'table_start', best_start)

# parse XALZ chunks
chunks = {}
pos = 0
while True:
    i = data.find(b'XALZ', pos)
    if i == -1:
        break
    idx = int.from_bytes(data[i+4:i+8], 'little')
    usize = int.from_bytes(data[i+8:i+12], 'little')
    chunks[idx] = (i, usize)
    pos = i+1

print('found', len(chunks), 'chunks')

# sort indices
indices = sorted(chunks.keys())
# build next offset map
offsets = [chunks[i][0] for i in indices]
offsets.append(len(data))
idx_to_next = {idx: offsets[i+1] for i, idx in enumerate(indices)}

extracted = 0
for i, name in enumerate(entries):
    if i not in chunks:
        print('no chunk for idx', i, 'name', name)
        continue
    off, usize = chunks[i]
    next_off = idx_to_next[i]
    # payload starts at off+12 (empirically observed)
    payload = data[off+12:next_off]
    try:
        out = lz4.block.decompress(payload, uncompressed_size=usize)
    except Exception as e:
        print('decompress failed for', i, name, 'err', e)
        continue
    target = OUTDIR / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(out)
    print('wrote', target, 'size', len(out))
    extracted += 1

print('extracted', extracted, 'of', len(entries))

# also dump any leftover chunks not mapped to entries
for idx in indices:
    if idx < len(entries):
        continue
    off, usize = chunks[idx]
    next_off = idx_to_next[idx]
    payload = data[off+12:next_off]
    try:
        out = lz4.block.decompress(payload, uncompressed_size=usize)
    except Exception:
        continue
    name = f'extra_chunk_{idx}.bin'
    target = OUTDIR / name
    target.write_bytes(out)
    print('wrote extra', target, 'size', len(out))

print('done')
