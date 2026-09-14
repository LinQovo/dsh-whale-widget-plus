# -*- coding: utf-8 -*-
"""
dsh-whale-widget 抠图引擎（命令行）
================================================
插件运行时由 Node 侧调用；也可以手动跑：

    py -3.12 tools/matting.py --input a.png --output b.png --engine auto
    py -3.12 tools/matting.py --list

引擎（--engine）
  auto    自动挑当前可用的最强模型（BiRefNet > IS-Net > U²-Net > u2netp），推荐
  best    IS-Net 通用版（1024×1024，边缘最细；缺模型则回退）
  fast    U²-Net 轻量版 u2netp（320×320，最快）
  simple  四角泛洪 + 最大连通域（纯色背景，不需要模型）
  none    只做格式归一化（任意格式 → PNG）

质量增强（默认开，--no-refine 可关）
  · 引导滤波（guided filter）：用原图当引导，把蒙版边缘吸附到真实轮廓上，
    比单纯放大蒙版锐利得多，发丝/袖口这类细节会明显变干净
  · 去白边（defringe）：对 0<alpha<1 的半透明像素反解前景色，
    去掉抠图常见的白/灰描边（挂在深色背景上尤其明显）
  · 最大连通域（只丢小碎块）/ 补洞 / 低值截断

推理流程沿用 luotianyi_pet/core/ai_matting.py 的思路（U²-Net, Apache-2.0；
onnx 权重取自 rembg 发布包, MIT），并按 IS-Net / BiRefNet 的归一化与输出特性扩展。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageFilter
    DEPS = True
    DEPS_ERROR = ""
except Exception as exc:  # 依赖缺失不致命：--list 等只读能力仍然可用
    np = None
    Image = None
    ImageFilter = None
    DEPS = False
    DEPS_ERROR = str(exc)

try:
    import cv2
    CV2 = True
except Exception:  # pragma: no cover
    CV2 = False

HERE = Path(__file__).resolve().parent
DEFAULT_MODELS_DIR = HERE.parent / "models"

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

# 模型登记表：文件、输入尺寸、归一化方式、rank（rank 越大越强）
MODEL_SPECS = {
    "isnet-general-use": {
        "file": "isnet-general-use.onnx",
        "size": 1024,
        "norm": "half",          # (x/0.5 - 1)/1.0，即 rembg 里 IS-Net 的归一化
        "desc": "IS-Net 通用版 1024×1024（插画/立绘最佳性价比）",
        "rank": 3,
    },
    "birefnet-general": {
        "file": "birefnet-general.onnx",
        "size": 1024,
        "norm": "imagenet",
        "desc": "BiRefNet 通用版 1024×1024（最强，但模型大、CPU 慢）",
        "rank": 4,
    },
    "u2net": {
        "file": "u2net.onnx",
        "size": 320,
        "norm": "imagenet",
        "desc": "U²-Net 完整版 320×320",
        "rank": 2,
    },
    "u2netp": {
        "file": "u2netp.onnx",
        "size": 320,
        "norm": "imagenet",
        "desc": "U²-Net 轻量版 320×320（最快）",
        "rank": 1,
    },
}
ENGINE_TO_MODEL = {"best": "isnet-general-use", "fast": "u2netp"}


# --------------------------------------------------- 纯色背景引擎（扁平插画神技）
def border_stats(rgb: np.ndarray):
    """取图像四边一圈像素的统计：中位色 + 均匀度（std 越小越"纯色"）。"""
    h, w, _ = rgb.shape
    band = max(2, int(min(h, w) * 0.02))
    ring = np.concatenate([
        rgb[:band].reshape(-1, 3), rgb[-band:].reshape(-1, 3),
        rgb[:, :band].reshape(-1, 3), rgb[:, -band:].reshape(-1, 3),
    ])
    color = np.median(ring, axis=0)
    spread = float(np.mean(np.std(ring, axis=0)))
    return color, spread


def color_alpha(rgb: np.ndarray, tolerance: int = 26):
    """
    纯色背景抠图：只把「与边框同色**且**和边框连通」的像素当背景。

    为什么不是简单的颜色阈值：白底 + 白衣服的图，全局阈值会把衣服也抠掉。
    从边框做连通域标记之后，被轮廓包住的白色（衣服/头发）不与边框连通，
    于是能完整保留——这对扁平插画是像素级正确的。
    返回 (alpha, 背景色, 均匀度)。
    """
    h, w, _ = rgb.shape
    bg, spread = border_stats(rgb)
    dist = np.sqrt(((rgb - bg[None, None, :]) ** 2).sum(axis=2))
    lo, hi = tolerance * 0.5, tolerance * 1.6
    bg_like = np.clip((hi - dist) / max(1e-6, hi - lo), 0.0, 1.0)

    if not CV2:
        return np.clip(1.0 - bg_like, 0.0, 1.0), bg, spread

    similar = (dist <= hi).astype(np.uint8)
    num, labels = cv2.connectedComponents(similar, connectivity=8)
    if num <= 1:
        return np.clip(1.0 - bg_like, 0.0, 1.0), bg, spread

    band = max(1, int(min(h, w) * 0.01))
    edge_labels = np.concatenate([
        labels[:band].ravel(), labels[-band:].ravel(),
        labels[:, :band].ravel(), labels[:, -band:].ravel(),
    ])
    keep = [int(v) for v in np.unique(edge_labels) if v != 0]
    if not keep:
        return np.clip(1.0 - bg_like, 0.0, 1.0), bg, spread

    bg_region = np.isin(labels, keep)
    # 稍微膨胀，把抗锯齿边缘也纳入「背景影响区」
    bg_region = cv2.dilate(bg_region.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1).astype(bool)
    alpha = 1.0 - bg_like * bg_region
    return np.clip(alpha, 0.0, 1.0), bg, spread


# ------------------------------------------------------------------ 模型选择
def model_path(models_dir: Path, name: str) -> Path:
    return models_dir / MODEL_SPECS[name]["file"]


def available_models(models_dir: Path):
    out = []
    for name, spec in sorted(MODEL_SPECS.items(), key=lambda kv: -kv[1]["rank"]):
        p = model_path(models_dir, name)
        size = p.stat().st_size if p.exists() else 0
        out.append({"id": name, "ready": size > 100_000, "mb": round(size / 1048576.0, 1), "size": spec["size"], "desc": spec["desc"]})
    return out


def pick_model(models_dir: Path, engine: str):
    """按引擎偏好挑一个已存在的模型，返回 (name, path) 或 (None, None)。"""
    if engine in ENGINE_TO_MODEL:
        name = ENGINE_TO_MODEL[engine]
        p = model_path(models_dir, name)
        if p.exists() and p.stat().st_size > 100_000:
            return name, p
    for name, _spec in sorted(MODEL_SPECS.items(), key=lambda kv: -kv[1]["rank"]):
        p = model_path(models_dir, name)
        if p.exists() and p.stat().st_size > 100_000:
            return name, p
    return None, None


def onnx_available() -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec("onnxruntime") is not None
    except (ImportError, ValueError):
        return False


# ------------------------------------------------------------- 推理核心
_SESSIONS: dict[str, object] = {}


def get_session(path: Path):
    key = str(path)
    session = _SESSIONS.get(key)
    if session is not None:
        return session
    import onnxruntime as ort
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    _SESSIONS[key] = session
    return session


def prepare_tensor(img: Image.Image, size: int, norm: str):
    rgb = img.convert("RGB").resize((size, size), Image.LANCZOS)
    arr = np.asarray(rgb).astype(np.float32)
    if norm == "half":
        arr = arr / max(1.0, float(arr.max()))
        arr = (arr / 0.5 - 1.0) / 1.0
    else:
        arr = arr / 255.0
        arr = (arr - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
    return np.ascontiguousarray(arr.transpose(2, 0, 1)[None].astype(np.float32))


def predict_mask(img: Image.Image, path: Path, model_name: str) -> np.ndarray:
    """跑模型，返回原图尺寸的 0..1 float 蒙版。"""
    spec = MODEL_SPECS[model_name]
    session = get_session(path)
    tensor = prepare_tensor(img, spec["size"], spec["norm"])
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})

    pred = outputs[0]
    while pred.ndim > 2:
        pred = pred[0]
    pred = pred.astype(np.float32)

    # u2net 系列输出 logits（有负值）→ sigmoid；IS-Net / BiRefNet 已在 [0,1]
    if float(pred.min()) < 0.0 or float(pred.max()) > 1.0 + 1e-6:
        pred = 1.0 / (1.0 + np.exp(-np.clip(pred, -30, 30)))

    lo, hi = float(pred.min()), float(pred.max())
    pred = (pred - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(pred)

    mask = Image.fromarray((pred * 255.0).astype(np.uint8), mode="L")
    mask = mask.resize(img.size, Image.LANCZOS)
    return np.asarray(mask).astype(np.float32) / 255.0


# --------------------------------------------------------- 质量增强
def _box(img: np.ndarray, r: int) -> np.ndarray:
    if CV2:
        return cv2.blur(img, (r * 2 + 1, r * 2 + 1))
    k = r * 2 + 1
    p = np.pad(img, r, mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / float(k * k)


def guided_filter(guide: np.ndarray, src: np.ndarray, radius: int = 8, eps: float = 1e-4) -> np.ndarray:
    """引导滤波：用原图灰度当引导，把蒙版边缘吸附到真实轮廓上。"""
    mean_i = _box(guide, radius)
    mean_p = _box(src, radius)
    cov_ip = _box(guide * src, radius) - mean_i * mean_p
    var_i = _box(guide * guide, radius) - mean_i * mean_i
    a = cov_ip / (var_i + eps)
    b = mean_p - a * mean_i
    return np.clip(_box(a, radius) * guide + _box(b, radius), 0.0, 1.0)


def estimate_background(rgb: np.ndarray, alpha: np.ndarray):
    """从透明区估计背景色（去白边用）。返回 (颜色, 均匀度) —— 越均匀越可信。"""
    h, w = alpha.shape
    border = np.zeros_like(alpha, dtype=bool)
    band = max(2, int(min(h, w) * 0.02))
    border[:band, :] = True
    border[-band:, :] = True
    border[:, :band] = True
    border[:, -band:] = True
    sample = (alpha < 0.15) & border
    if sample.sum() < 50:
        sample = alpha < 0.15
    if sample.sum() < 50:
        return None, 999.0
    pixels = rgb[sample].astype(np.float32)
    color = np.median(pixels, axis=0)
    spread = float(np.mean(np.std(pixels, axis=0)))
    return color, spread


def defringe(rgb: np.ndarray, alpha: np.ndarray, color: np.ndarray) -> np.ndarray:
    """半透明像素反解前景色：F = (C - (1-a)·B) / a，去掉白/灰描边。"""
    a = alpha[..., None]
    fg = (rgb.astype(np.float32) - (1.0 - a) * color[None, None, :]) / np.maximum(a, 1e-2)
    fg = np.clip(fg, 0.0, 255.0)
    edge = ((alpha > 0.02) & (alpha < 0.98))[..., None]
    out = np.where(edge, fg, rgb.astype(np.float32))
    return np.clip(out, 0, 255).astype(np.uint8)


def clean_mask(mask: np.ndarray, keep_largest: bool, fill_holes: bool) -> np.ndarray:
    if not CV2:
        return mask
    a = (mask * 255).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    a = cv2.morphologyEx(a, cv2.MORPH_OPEN, kernel, iterations=1)
    a = cv2.morphologyEx(a, cv2.MORPH_CLOSE, kernel, iterations=2)
    if keep_largest:
        count, labels, stats, _ = cv2.connectedComponentsWithStats((a > 127).astype(np.uint8), connectivity=8)
        if count > 2:
            biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            keep = (labels == biggest).astype(np.uint8)
            total = float(keep.sum())
            # 只丢小碎块（<2% 面积），保留披风/道具这类合理的分体
            for i in range(1, count):
                if i == biggest:
                    continue
                if stats[i, cv2.CC_STAT_AREA] >= total * 0.02:
                    keep = np.maximum(keep, (labels == i).astype(np.uint8))
            a = (a * keep).astype(np.uint8)
    if fill_holes:
        cnts, _ = cv2.findContours((a > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(a)
        cv2.drawContours(filled, cnts, -1, 255, thickness=cv2.FILLED)
        a = np.maximum(a, filled)
    return a.astype(np.float32) / 255.0


def flat_viability(rgb: np.ndarray, tolerance: int = 26):
    """
    判断「能不能用纯色引擎」，以及纯色引擎会抠掉多少。

    只看边框标准差是不够的：立绘常常裁得很紧，头发会顶到边框，
    标准差很大但背景依然是纯白。所以这里看三个更可靠的信号：
      · exact_ratio —— 有多少像素和背景色**几乎完全一致**（矢量图/白底会很高，照片很低）
      · border_frac —— 边框上有多少像素是背景色
      · removed     —— 连通域法会判定为背景的面积比例（要落在合理区间）
    """
    exact, removed, bg, spread, border_frac = color_stats(rgb, tolerance)
    ok = exact > 0.06 and border_frac > 0.45 and 0.02 < removed < 0.95
    return ok, {"exactRatio": round(exact, 3), "borderFrac": round(border_frac, 3), "removed": round(removed, 3), "bgSpread": round(spread, 1)}


def color_stats(rgb: np.ndarray, tolerance: int = 26):
    """返回 (exact 比例, 判为背景的比例, 背景色, 边框 std, 边框背景占比)。"""
    h, w, _ = rgb.shape
    bg, spread = border_stats(rgb)
    dist = np.sqrt(((rgb - bg[None, None, :]) ** 2).sum(axis=2))
    exact = float((dist < 6).mean())

    band = max(2, int(min(h, w) * 0.02))
    ring_dist = np.concatenate([
        dist[:band].ravel(), dist[-band:].ravel(),
        dist[:, :band].ravel(), dist[:, -band:].ravel(),
    ])
    border_frac = float((ring_dist <= tolerance * 1.6).mean())

    alpha, _bgc, _spread = color_alpha(rgb, tolerance)
    removed = float(1.0 - alpha.mean())
    return exact, removed, bg, spread, border_frac


def refine_mask(mask: np.ndarray, rgb: np.ndarray, args) -> np.ndarray:
    """引导滤波：用原图灰度当引导，把蒙版边缘吸附到真实轮廓上。"""
    if not args.refine:
        return mask
    gray = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]) / 255.0
    radius = max(4, int(round(min(mask.shape) / 160)))
    return guided_filter(gray, mask, radius=radius, eps=args.guided_eps)


def finish(rgba: Image.Image, rgb: np.ndarray, mask: np.ndarray, args, extra: dict) -> Image.Image:
    """统一的收尾：截断 → 清理 → 去白边 → 边缘柔化。"""
    if args.floor > 0:
        mask = np.clip((mask - args.floor) / max(1e-6, 1.0 - args.floor), 0.0, 1.0)
    mask = clean_mask(mask, not args.no_largest, args.fill_holes)

    if args.refine and args.defringe:
        bg, spread = estimate_background(rgb, mask)
        if bg is not None and spread < 90:
            rgb_out = defringe(rgb, mask, bg)
            out = Image.fromarray(np.dstack([rgb_out, (mask * 255).astype(np.uint8)]), mode="RGBA")
            extra["defringe"] = True
        else:
            out = rgba.copy()
            out.putalpha(Image.fromarray((mask * 255).astype(np.uint8), mode="L"))
            extra["defringe"] = False
    else:
        out = rgba.copy()
        out.putalpha(Image.fromarray((mask * 255).astype(np.uint8), mode="L"))
        extra["defringe"] = False

    if args.edge_soften > 0:
        out.putalpha(out.getchannel("A").filter(ImageFilter.GaussianBlur(args.edge_soften)))
    return out


def matting_ai(img: Image.Image, path: Path, model_name: str, args, fuse_mask=None, fuse_label: str = ""):
    """AI 抠图：模型 → 引导滤波 →（可选）与纯色引擎的蒙版取并集 → 收尾。"""
    t0 = time.monotonic()
    rgba = img.convert("RGBA")
    mask = predict_mask(rgba, path, model_name)
    infer_ms = int((time.monotonic() - t0) * 1000)
    rgb = np.asarray(rgba.convert("RGB")).astype(np.float32)

    mask = refine_mask(mask, rgb, args)
    if fuse_mask is not None:
        # 并集：AI 的平滑边缘 + 纯色引擎"轮廓内一定保留"的确定性，互补短板
        mask = np.maximum(mask, fuse_mask)

    extra = {"model": model_name, "inferMs": infer_ms, "guided": bool(args.refine)}
    if fuse_label:
        extra["fused"] = fuse_label
    return finish(rgba, rgb, mask, args, extra), extra


def matting_color(img: Image.Image, args):
    """纯色背景抠图（边框连通域），不需要模型、瞬间完成。"""
    t0 = time.monotonic()
    rgba = img.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB")).astype(np.float32)
    mask, bg, spread = color_alpha(rgb, args.tolerance)
    mask = refine_mask(mask, rgb, args)
    extra = {
        "model": "flat-color",
        "inferMs": int((time.monotonic() - t0) * 1000),
        "guided": bool(args.refine),
        "bgSpread": round(spread, 1),
    }
    return finish(rgba, rgb, mask, args, extra), extra


# ------------------------------------------------------------ simple 引擎
def matting_simple(img: Image.Image, tolerance: int, keep_largest: bool) -> Image.Image:
    """四角泛洪去背景：纯色/白底扁平插画用，不需要模型。"""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    rgb = rgba.convert("RGB")
    corners = [rgb.getpixel((0, 0)), rgb.getpixel((w - 1, 0)), rgb.getpixel((0, h - 1)), rgb.getpixel((w - 1, h - 1))]
    bg = np.median(np.array(corners, dtype=np.float32), axis=0)
    arr = np.asarray(rgb).astype(np.float32)
    dist = np.sqrt(((arr - bg) ** 2).sum(axis=2))
    mask = (dist > tolerance).astype(np.float32)
    mask = clean_mask(mask, keep_largest, True)
    mask_image = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    mask_image = mask_image.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    out = rgba.copy()
    out.putalpha(mask_image)
    return out


# ------------------------------------------------------------------ 后处理
def crop_ratios(img: Image.Image, top: float, bottom: float, left: float, right: float) -> Image.Image:
    if top <= 0 and bottom <= 0 and left <= 0 and right <= 0:
        return img
    w, h = img.size
    box = (int(round(w * left)), int(round(h * top)), int(round(w * (1 - right))), int(round(h * (1 - bottom))))
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return img
    return img.crop(box)


def trim_alpha(img: Image.Image, margin: float, alpha_min: int = 8) -> Image.Image:
    alpha = img.getchannel("A")
    bbox = alpha.point(lambda v: 255 if v > alpha_min else 0).getbbox()
    if not bbox:
        return img
    w, h = img.size
    pad = int(round(max(w, h) * margin))
    return img.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(w, bbox[2] + pad), min(h, bbox[3] + pad)))


def main() -> int:
    ap = argparse.ArgumentParser(description="dsh-whale-widget matting CLI")
    ap.add_argument("--input")
    ap.add_argument("--output")
    ap.add_argument("--engine", default="auto", choices=["auto", "ai", "best", "fast", "hybrid", "flat", "simple", "none"])
    ap.add_argument("--models-dir", default=str(DEFAULT_MODELS_DIR))
    ap.add_argument("--model", default="", help="直接指定模型名或 .onnx 路径（覆盖 --engine）")
    ap.add_argument("--list", action="store_true", help="列出模型与引擎可用情况（JSON）")
    ap.add_argument("--crop-top", type=float, default=0.0)
    ap.add_argument("--crop-bottom", type=float, default=0.0)
    ap.add_argument("--crop-left", type=float, default=0.0)
    ap.add_argument("--crop-right", type=float, default=0.0)
    ap.add_argument("--max-side", type=int, default=1536)
    ap.add_argument("--tolerance", type=int, default=26)
    ap.add_argument("--no-largest", action="store_true")
    ap.add_argument("--fill-holes", dest="fill_holes", action="store_true", default=True)
    ap.add_argument("--no-fill-holes", dest="fill_holes", action="store_false")
    ap.add_argument("--no-refine", dest="refine", action="store_false", default=True, help="关闭引导滤波与去白边")
    ap.add_argument("--guided-eps", type=float, default=1e-4)
    ap.add_argument("--defringe", dest="defringe", action="store_true", default=True)
    ap.add_argument("--no-defringe", dest="defringe", action="store_false")
    ap.add_argument("--edge-soften", type=float, default=0.5)
    ap.add_argument("--floor", type=float, default=0.04)
    ap.add_argument("--trim", action="store_true")
    ap.add_argument("--trim-margin", type=float, default=0.01)
    args = ap.parse_args()

    models_dir = Path(args.models_dir)

    if args.list:
        picks = {e: pick_model(models_dir, e)[0] for e in ("auto", "best", "fast")}
        print(json.dumps({
            "ok": True,
            "onnxruntime": onnx_available(),
            "opencv": CV2,
            "pillowNumpy": DEPS,
            "models": available_models(models_dir),
            "engines": {
                "auto": {"model": picks["auto"], "desc": "自动：纯色背景走融合，复杂背景走 IS-Net"},
                "hybrid": {"model": picks["auto"], "desc": "纯色引擎 + AI 融合"},
                "best": {"model": picks["best"], "desc": "IS-Net 1024 精细（纯 AI）"},
                "fast": {"model": picks["fast"], "desc": "u2netp 320 快速（纯 AI）"},
                "flat": {"model": None, "desc": "纯色背景（边框连通域，插画/白底最快最准）"},
                "simple": {"model": None, "desc": "颜色阈值（旧算法，兼容用）"},
                "none": {"model": None, "desc": "不抠图，仅转 PNG"},
            },
        }))
        return 0

    if not args.input or not args.output:
        print(json.dumps({"ok": False, "error": "需要 --input 和 --output"}))
        return 2

    src = Path(args.input)
    dst = Path(args.output)
    if not src.exists():
        print(json.dumps({"ok": False, "error": "输入不存在: %s" % src}))
        return 2

    if not DEPS:
        print(json.dumps({"ok": False, "error": "缺少 Pillow/numpy（pip install pillow numpy；抠图还需要 onnxruntime，可选 opencv-python）: " + DEPS_ERROR}))
        return 3

    img = Image.open(src)
    img = crop_ratios(img.convert("RGBA"), args.crop_top, args.crop_bottom, args.crop_left, args.crop_right)
    if args.max_side and max(img.size) > args.max_side:
        scale = args.max_side / float(max(img.size))
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)

    engine = "auto" if args.engine == "ai" else args.engine
    extra = {}
    rgba = img.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB")).astype(np.float32)
    _bg, bg_spread = border_stats(rgb)
    flat_ok, flat_info = flat_viability(rgb, args.tolerance)

    want_color = engine in ("flat", "auto", "hybrid")
    want_ai = engine in ("best", "fast", "auto", "hybrid")

    ai_mask = None
    if want_ai:
        if args.model:
            if args.model.endswith(".onnx"):
                path = Path(args.model)
                name = path.stem
                if name not in MODEL_SPECS:
                    MODEL_SPECS[name] = {"file": path.name, "size": 1024, "norm": "half", "desc": "自定义模型", "rank": 5}
            else:
                name = args.model
                path = model_path(models_dir, name)
            if not path.exists():
                print(json.dumps({"ok": False, "error": "找不到模型文件: %s" % path}))
                return 3
        else:
            name, path = pick_model(models_dir, engine if engine != "hybrid" else "auto")
        if not name:
            if engine in ("best", "fast"):
                print(json.dumps({"ok": False, "error": "没有可用的 AI 模型（先跑 tools/download_model.py）"}))
                return 3
            want_ai = False
        elif not onnx_available():
            print(json.dumps({"ok": False, "error": "缺少 onnxruntime"}))
            return 3
        else:
            t0 = time.monotonic()
            ai_mask = refine_mask(predict_mask(rgba, path, name), rgb, args)
            extra["model"] = name
            extra["inferMs"] = int((time.monotonic() - t0) * 1000)

    if engine in ("simple",):
        out = matting_simple(img, args.tolerance, not args.no_largest)
    elif engine == "none":
        out = img
    elif want_color and (flat_ok or engine in ("flat", "hybrid") or ai_mask is None):
        mask, _bgc, spread = color_alpha(rgb, args.tolerance)
        mask = refine_mask(mask, rgb, args)
        if ai_mask is not None and (flat_ok or engine == "hybrid"):
            # 纯色引擎 + AI 融合：AI 的平滑边缘 + 纯色法的"轮廓内一定保留"
            mask = np.maximum(mask, ai_mask)
            extra["fused"] = "flat+ai"
        elif not flat_ok and engine == "auto":
            extra["note"] = "背景不是纯色，但没有可用模型，已回退纯色引擎"
        extra["engineUsed"] = "flat"
        extra["flatInfo"] = flat_info
        out = finish(rgba, rgb, mask, args, extra)
    elif ai_mask is not None:
        extra["engineUsed"] = "ai"
        extra["flatInfo"] = flat_info
        out = finish(rgba, rgb, ai_mask, args, extra)
    else:
        # 既没有模型、背景也不是纯色：原图保存，并说清楚原因（全新克隆的默认处境）
        out = img
        extra["engineUsed"] = "none"
        extra["note"] = "没有可用的抠图模型，已按原图保存；先跑 tools/download_model.py 或在菜单里选「纯色背景」"

    if args.trim:
        out = trim_alpha(out, args.trim_margin)

    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "PNG")

    alpha = np.asarray(out.getchannel("A"))
    print(json.dumps({
        "ok": True,
        "engine": engine,
        "output": str(dst),
        "width": out.width,
        "height": out.height,
        "coverage": round(float((alpha > 32).mean()), 4),
        **extra,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
