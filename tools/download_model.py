# -*- coding: utf-8 -*-
"""
抠图模型下载器
================================================
按需下载更强的高精度模型（默认只下 u2netp，随包已经带了）。

    py -3.12 tools/download_model.py --list
    py -3.12 tools/download_model.py --model isnet-general-use
    py -3.12 tools/download_model.py --all

为什么不用 PowerShell / curl：这台机器上 Windows 原生 schannel TLS 不可用
（curl 报 AcquireCredentialsHandle failed），而 Python 自带 OpenSSL 是通的。
所以这里用 urllib，并且依次尝试官方地址和几个国内加速镜像。
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"

# 名称 -> (说明, 大约大小 MB, 候选地址)
MODELS = {
    "u2netp": (
        "U²-Net 轻量版，320×320，4.5MB，速度最快、精度一般（默认）",
        4.5,
        ["https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"],
    ),
    "u2net": (
        "U²-Net 完整版，320×320，168MB，比 u2netp 稳",
        168,
        ["https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"],
    ),
    "isnet-general-use": (
        "IS-Net 通用版，1024×1024，170MB，插画/立绘推荐（边缘细、发丝好）",
        170,
        ["https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"],
    ),
    "birefnet-general": (
        "BiRefNet 通用版，1024×1024，约 900MB，当前最强但慢（CPU 单张数十秒）",
        900,
        ["https://github.com/danielgatis/rembg/releases/download/v0.0.0/birefnet-general.onnx"],
    ),
}

MIRRORS = [
    "{url}",
    "https://ghfast.top/{url}",
    "https://gh-proxy.com/{url}",
    "https://ghproxy.net/{url}",
    "https://mirror.ghproxy.com/{url}",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def download(url: str, target: Path, timeout: int = 600) -> bool:
    request = urllib.request.Request(url, headers=HEADERS)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            got = 0
            started = time.monotonic()
            with open(tmp, "wb") as fh:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total and got % (8 * 1048576) < 65536:
                        pct = got * 100.0 / total
                        speed = got / 1048576.0 / max(0.001, time.monotonic() - started)
                        print(f"    {pct:5.1f}%  {got / 1048576.0:6.1f}/{total / 1048576.0:.1f} MB  {speed:.2f} MB/s", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"    失败：{exc}")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False

    if got < 100_000:
        print(f"    失败：文件太小（{got} 字节）")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False

    tmp.replace(target)
    print(f"    成功：{got / 1048576.0:.2f} MB，用时 {time.monotonic() - started:.0f} 秒")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="下载抠图模型到 models/")
    ap.add_argument("--model", action="append", default=[], help="模型名（可重复）；默认 u2netp")
    ap.add_argument("--all", action="store_true", help="下载全部模型")
    ap.add_argument("--list", action="store_true", help="只列出可用模型")
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = ap.parse_args()

    if args.list:
        for name, (desc, mb, _urls) in MODELS.items():
            target = MODEL_DIR / (name + ".onnx")
            have = f"已存在 {target.stat().st_size / 1048576.0:.1f}MB" if target.exists() else "未下载"
            print(f"{name:20s} ~{mb:>4}MB  [{have}]  {desc}")
        return 0

    names = list(MODELS) if args.all else (args.model or ["u2netp"])
    unknown = [n for n in names if n not in MODELS]
    if unknown:
        print("未知模型：" + "、".join(unknown) + "（用 --list 看可选）")
        return 2

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    for name in names:
        desc, _mb, urls = MODELS[name]
        target = MODEL_DIR / (name + ".onnx")
        if target.exists() and target.stat().st_size > 100_000 and not args.force:
            print(f"[跳过] {name}.onnx 已存在（{target.stat().st_size / 1048576.0:.1f} MB）")
            continue
        print(f"[下载] {name}.onnx —— {desc}")
        ok = False
        for template in MIRRORS:
            for url in urls:
                candidate = template.format(url=url)
                print(f"  尝试 {candidate}")
                if download(candidate, target):
                    ok = True
                    break
            if ok:
                break
        if not ok:
            failed.append(name)

    print("")
    if failed:
        print("以下模型没下载成功：" + "、".join(failed))
        print("不影响使用：抠图会自动回退到已有的轻量模型或纯色背景算法。")
        return 1
    print(f"模型已就绪：{MODEL_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
