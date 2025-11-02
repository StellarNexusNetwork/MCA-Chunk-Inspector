#!/usr/bin/env python3
"""
mca_chunk_inspector.py
读取单个 region (.mca) 文件里的指定 chunk（cx, cz），尝试处理损坏并输出 JSON。
目标场景：处理 10MB+ 的 region，能在常见损坏情况下做恢复与诊断。
"""

import argparse
import struct
import json
import os
import sys
from io import BytesIO

import zlib
import gzip
import binascii

# 尝试导入解析 NBT 的库（优先 nbtlib，然后 python-nbt）
nbt_parser_kind = None
try:
    import nbtlib
    nbt_parser_kind = "nbtlib"
except Exception:
    try:
        from nbt import nbt as python_nbt
        nbt_parser_kind = "python-nbt"
    except Exception:
        nbt_parser_kind = None

def read_region_header(f):
    f.seek(0)
    header = f.read(8192)
    if len(header) < 8192:
        raise IOError("Region header too short")
    # first 4096 bytes: 1024 entries of 4 bytes
    offsets = [struct.unpack(">I", header[i*4:(i+1)*4])[0] for i in range(1024)]
    return offsets

def chunk_index(cx, cz):
    # inside region: coordinates 0..31
    rx = cx & 31
    rz = cz & 31
    return rx + rz * 32

def extract_chunk_raw_from_region(path, cx, cz):
    """
    返回字典：
    {
      'found': True/False,
      'offset_sector': int,
      'sector_count': int,
      'length': int or None,
      'compression': int or None,
      'compressed_bytes': bytes or None,
      'raw_sector_data': bytes (the whole sector block read),
      'errors': [...]
    }
    """
    res = {'found': False, 'errors': []}
    try:
        with open(path, "rb") as f:
            offsets = read_region_header(f)
            idx = chunk_index(cx, cz)
            entry = offsets[idx]
            offset_sector = entry >> 8
            sector_count = entry & 0xFF
            res.update({'offset_sector': offset_sector, 'sector_count': sector_count})
            if offset_sector == 0:
                res['errors'].append("Chunk not present (offset 0).")
                return res

            start = offset_sector * 4096
            f.seek(0, os.SEEK_END)
            total_size = f.tell()
            if start >= total_size:
                res['errors'].append(f"Offset points beyond file (start={start}, file={total_size}).")
                # try to scan a bit later for possible compressed stream
            # 尝试按正式格式读取 chunk
            try:
                f.seek(start)
                # 读取 4 字节 length（big endian）
                raw_head = f.read(4)
                if len(raw_head) < 4:
                    res['errors'].append("Couldn't read length header (short read).")
                else:
                    length = struct.unpack(">I", raw_head)[0]
                    # 读取 length bytes (chunk data) — 1 byte compression type + payload
                    compressed = f.read(length)
                    if len(compressed) < max(0, length):
                        res['errors'].append(f"Chunk length {length} but only read {len(compressed)} bytes.")
                    else:
                        comp_type = compressed[0] if len(compressed)>0 else None
                        payload = compressed[1:] if len(compressed)>1 else b""
                        res.update({
                            'found': True,
                            'length': length,
                            'compression': comp_type,
                            'compressed_bytes': payload,
                            'raw_sector_data': raw_head + compressed
                        })
                        return res
            except Exception as e:
                res['errors'].append(f"Standard read error: {e}")

            # 若标准读取失败，尝试扫描附近区域查找 zlib/gzip header（恢复尝试）
            SCAN_LIMIT = 1024 * 1024 * 4  # 向后扫描最多 4MB
            scan_start = max(start, 4096)  # 避免覆盖 header
            f.seek(0, os.SEEK_END)
            file_end = f.tell()
            scan_end = min(file_end, scan_start + SCAN_LIMIT)
            f.seek(scan_start)
            block = f.read(scan_end - scan_start)
            # 搜索 gzip header (1f 8b) 或 zlib headers (common 78 9c or 78 01 or 78 da)
            gz_pos = block.find(b"\x1f\x8b")
            z_pos = block.find(b"\x78")
            candidate_pos = None
            cand_type = None
            if gz_pos != -1:
                candidate_pos = scan_start + gz_pos
                cand_type = 'gzip'
            elif z_pos != -1:
                # 找到 0x78 之后再看下一个字节是否常见的 zlib flags
                # look few bytes ahead to avoid false positives
                found = -1
                for off in range(z_pos, min(z_pos+32, len(block))):
                    b1 = block[off]
                    if b1 == 0x78:
                        if off+1 < len(block):
                            b2 = block[off+1]
                            # common pairs: 78 9C, 78 01, 78 DA
                            if b2 in (0x9c, 0x01, 0xda):
                                found = off
                                break
                if found != -1:
                    candidate_pos = scan_start + found
                    cand_type = 'zlib'
            if candidate_pos is not None:
                res['errors'].append(f"Could not read by header; found candidate compressed stream at file offset {candidate_pos} ({cand_type}). Will try to extract.")
                # read from candidate_pos to end (or up to some MB)
                f.seek(candidate_pos)
                tail = f.read(min(8 * 1024 * 1024, file_end - candidate_pos))
                # try decompress progressively
                try:
                    if cand_type == 'gzip':
                        decompressed = gzip.decompress(tail)
                        res.update({'found': True, 'compression': 1, 'compressed_bytes': tail, 'decompressed_bytes': decompressed})
                        return res
                    else:
                        decompressed = zlib.decompress(tail)
                        res.update({'found': True, 'compression': 2, 'compressed_bytes': tail, 'decompressed_bytes': decompressed})
                        return res
                except Exception as e:
                    res['errors'].append(f"Decompression from candidate failed: {e}")
            else:
                res['errors'].append("No gzip/zlib header found during scan.")
    except Exception as e:
        res['errors'].append(f"IO error opening region: {e}")
    return res

def parse_nbt_bytes(data_bytes):
    import nbtlib
    try:
        # nbtlib.load 要求一个类文件对象（BytesIO）
        nbtobj = nbtlib.load(BytesIO(data_bytes), gzipped=False)
    except Exception as e1:
        try:
            # fallback: 尝试用 parse 解析
            nbtobj = nbtlib.File.parse(BytesIO(data_bytes))
        except Exception as e2:
            print(f"NBT parsing failed: {e2}")
            return None
    return nbtobj

def nbt_to_json_safe(obj):
    # some values might be bytes; convert safely
    if isinstance(obj, bytes):
        return binascii.hexlify(obj).decode('ascii')
    if isinstance(obj, dict):
        return {str(k): nbt_to_json_safe(v) for k,v in obj.items()}
    if isinstance(obj, list):
        return [nbt_to_json_safe(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # fallback
    return str(obj)


def main():
    p = argparse.ArgumentParser(description="Inspect a single chunk inside an MCA region and output JSON.")
    p.add_argument("--mca", required=True, help="Path to .mca region file (e.g. World/DIM1/region/r.0.0.mca)")
    p.add_argument("--cx", type=int, default=0, help="Chunk X (region-local or absolute; low 5 bits used)")
    p.add_argument("--cz", type=int, default=0, help="Chunk Z")
    p.add_argument("--out", default="chunk_out.json", help="Output JSON filename")
    p.add_argument("--raw-nbt-out", default=None, help="If set, write raw decompressed NBT bytes to this file")
    args = p.parse_args()

    print("Using NBT parser:", nbt_parser_kind)
    print("Opening region:", args.mca, "chunk:", (args.cx, args.cz))
    info = extract_chunk_raw_from_region(args.mca, args.cx, args.cz)

    # Dump diagnostic info
    diag = {
        'mca': args.mca,
        'chunk': {'cx': args.cx, 'cz': args.cz},
        'found': info.get('found', False),
        'offset_sector': info.get('offset_sector'),
        'sector_count': info.get('sector_count'),
        'length': info.get('length'),
        'compression_byte': info.get('compression'),
        'errors': info.get('errors', [])[:10]
    }

    if not info.get('found', False):
        print("Chunk not found or couldn't be read. Diagnostics:")
        print(json.dumps(diag, indent=2))
        # if decompressed_bytes is present (from scan), attempt to parse
        if 'decompressed_bytes' in info:
            print("Found decompressed bytes from heuristic scan; attempting to parse...")
            try:
                parsed = parse_nbt_bytes(info['decompressed_bytes'])
                js = nbt_to_json_safe(parsed)
                with open(args.out, "w", encoding="utf-8") as f:
                    json.dump({'diagnostics': diag, 'nbt': js}, f, ensure_ascii=False, indent=2)
                print("Wrote parsed JSON to", args.out)
                if args.raw_nbt_out:
                    with open(args.raw_nbt_out, "wb") as f:
                        f.write(info['decompressed_bytes'])
                        print("Wrote raw decompressed NBT bytes to", args.raw_nbt_out)
                return
            except Exception as e:
                print("Parsing decompressed bytes failed:", e)
                if args.raw_nbt_out:
                    with open(args.raw_nbt_out, "wb") as f:
                        f.write(info.get('decompressed_bytes', b''))
                        print("Saved raw decompressed bytes to", args.raw_nbt_out)
        # otherwise exit with diagnostics
        print("No parsed data. Saved diagnostics above. You can try MCA Selector / Amulet with the region file.")
        return

    # we have compressed bytes in expected place
    compressed = info.get('compressed_bytes')
    comp_type = info.get('compression')
    decompressed = None
    try:
        if comp_type == 1:
            # gzip
            decompressed = gzip.decompress(compressed)
        elif comp_type == 2:
            decompressed = zlib.decompress(compressed)
        else:
            # unknown compression - try both
            try:
                decompressed = gzip.decompress(compressed)
                comp_type = 1
            except Exception:
                decompressed = zlib.decompress(compressed)
                comp_type = 2
        print("Decompressed chunk bytes, length:", len(decompressed))
    except Exception as e:
        print("Decompression error:", e)
        # try scanning raw sector for embedded compressed stream (fallback)
        if 'raw_sector_data' in info and info['raw_sector_data']:
            raw = info['raw_sector_data']
            # find gzip/zlib in raw
            gz = raw.find(b"\x1f\x8b")
            zpos = raw.find(b"\x78")
            candidate = None
            ctype = None
            if gz!=-1:
                candidate = raw[gz:]
                ctype = 'gzip'
            elif zpos!=-1:
                # try pick slice
                candidate = raw[zpos:]
                ctype = 'zlib'
            if candidate:
                try:
                    if ctype=='gzip':
                        decompressed = gzip.decompress(candidate)
                        print("Recovered by scanning sector with gzip.")
                        comp_type = 1
                    else:
                        decompressed = zlib.decompress(candidate)
                        print("Recovered by scanning sector with zlib.")
                        comp_type = 2
                except Exception as e2:
                    print("Recovery decompress failed:", e2)
        if decompressed is None:
            print("无法解压 chunk 的压缩数据。将原始压缩体保存为 <out>.chunk_compressed.bin 以便离线分析。")
            try:
                with open(args.out + ".chunk_compressed.bin", "wb") as f:
                    f.write(compressed or b"")
                print("Saved", args.out + ".chunk_compressed.bin")
            except Exception as e:
                print("保存失败:", e)
            return

    # 现在我们有 decompressed bytes -> 解析 NBT
    try:
        parsed = parse_nbt_bytes(decompressed)
        js = nbt_to_json_safe(parsed)
        output = {'diagnostics': diag, 'nbt': js}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print("Parsed NBT written to", args.out)
        if args.raw_nbt_out:
            with open(args.raw_nbt_out, "wb") as f:
                f.write(decompressed)
                print("Saved raw decompressed NBT bytes to", args.raw_nbt_out)
    except Exception as e:
        print("NBT parsing failed:", e)
        # save decompressed bytes for GUI tools
        if args.raw_nbt_out:
            with open(args.raw_nbt_out, "wb") as f:
                f.write(decompressed)
                print("Saved raw decompressed NBT bytes to", args.raw_nbt_out)
        else:
            fn = args.out + ".decompressed.nbt"
            with open(fn, "wb") as f:
                f.write(decompressed)
            print("Saved decompressed NBT to", fn, " — open with NBTExplorer / Amulet for manual inspection.")


if __name__ == "__main__":
    main()
