# -*- coding: utf-8 -*-
"""
音效裁剪（不重新编码）
================================================
把一段音频剪成能当"音效"用的小片段。MP3 直接按帧边界裁（MP3 的帧是自包含的，
所以切出来依然是合法 MP3，不需要 ffmpeg、不掉音质）；WAV 走标准库 wave 重写头。

    py -3.12 tools/audio_cut.py --input song.mp3 --output clip.mp3 --start 0 --end 2.6
    py -3.12 tools/audio_cut.py --input song.mp3 --output tail.mp3 --start 21.4
    py -3.12 tools/audio_cut.py --info --input song.mp3
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import wave
from pathlib import Path

SAMPLE_RATES = {0: 44100, 1: 48000, 2: 32000}
BITRATES_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
BITRATES_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]


def skip_id3(data: bytes) -> int:
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
        return 10 + size
    return 0


def mp3_frames(data: bytes):
    """产出 (offset, length, duration_seconds)；只认 Layer III 帧。"""
    i = skip_id3(data)
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        b1, b2 = data[i + 1], data[i + 2]
        version = (b1 >> 3) & 0x3      # 3=MPEG1, 2=MPEG2
        layer = (b1 >> 1) & 0x3        # 1=Layer III
        br_idx = (b2 >> 4) & 0xF
        sr_idx = (b2 >> 2) & 0x3
        pad = (b2 >> 1) & 0x1
        if layer != 1 or br_idx in (0, 15) or sr_idx == 3 or version not in (2, 3):
            i += 1
            continue
        rate = SAMPLE_RATES[sr_idx] if version == 3 else SAMPLE_RATES[sr_idx] // 2
        table = BITRATES_V1L3 if version == 3 else BITRATES_V2L3
        bitrate = table[br_idx] * 1000
        samples = 1152 if version == 3 else 576
        length = int((samples / 8) * bitrate / rate) + pad
        if length <= 4:
            i += 1
            continue
        yield i, length, samples / float(rate)
        i += length


def cut_mp3(src: Path, dst: Path, start: float, end: float | None) -> dict:
    data = src.read_bytes()
    out = bytearray()
    # 保留 ID3 头，播放器才认得到标题等信息
    header_len = skip_id3(data)
    if header_len:
        out += data[:header_len]
    t = 0.0
    kept = 0
    for offset, length, dur in mp3_frames(data):
        frame_start, frame_end = t, t + dur
        t = frame_end
        if frame_start + dur <= start:
            continue
        if end is not None and frame_start >= end:
            break
        out += data[offset:offset + length]
        kept += 1
    if kept == 0:
        raise SystemExit("没有可裁剪的 MP3 帧（起始时间超出音频长度？）")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(out))
    return {"format": "mp3", "frames": kept, "duration": round(sum(1 for _ in ()) or 0, 2), "bytes": len(out)}


def cut_wav(src: Path, dst: Path, start: float, end: float | None) -> dict:
    with wave.open(str(src), "rb") as w:
        params = w.getparams()
        rate = w.getframerate()
        start_frame = int(start * rate)
        total = w.getnframes()
        end_frame = total if end is None else min(total, int(end * rate))
        w.setpos(min(start_frame, total))
        frames = w.readframes(max(0, end_frame - start_frame))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as o:
        o.setparams(params)
        o.writeframes(frames)
    return {"format": "wav", "duration": round(len(frames) / max(1, params.sampwidth * params.nchannels * rate), 2), "bytes": dst.stat().st_size}


def info(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] == b"RIFF":
        with wave.open(str(path), "rb") as w:
            return {"format": "wav", "rate": w.getframerate(), "channels": w.getnchannels(),
                    "duration": round(w.getnframes() / max(1, w.getframerate()), 2), "bytes": len(data)}
    total = 0.0
    frames = 0
    first = None
    for offset, length, dur in mp3_frames(data):
        if first is None:
            first = (offset, length)
        total += dur
        frames += 1
    return {"format": "mp3", "frames": frames, "duration": round(total, 2), "bytes": len(data)}


def main() -> int:
    ap = argparse.ArgumentParser(description="裁剪音效（MP3 按帧边界，WAV 走标准库）")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--info", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(json.dumps({"ok": False, "error": "输入不存在: %s" % src}))
        return 2

    if args.info:
        print(json.dumps({"ok": True, **info(src)}))
        return 0

    if not args.output:
        print(json.dumps({"ok": False, "error": "需要 --output"}))
        return 2

    dst = Path(args.output)
    head = src.read_bytes()[:4]
    if head == b"RIFF":
        res = cut_wav(src, dst, args.start, args.end)
    else:
        res = cut_mp3(src, dst, args.start, args.end)
    print(json.dumps({"ok": True, "output": str(dst), **res}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
