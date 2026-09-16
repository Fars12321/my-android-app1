#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ريندر فيديو اختبار من خطة الإنتاج JSON — Test Video Renderer
============================================================
يقرأ خطة إنتاج (مخرجات orchestrator.py) ويرسم فيديو MP4 عمودي/أفقي:
خلفية متحركة + ترجمة ديناميكية (2-4 كلمات) في منتصف الشاشة + شريط تقدم.

مثال:
  python render_test.py --plan test_plan.json --out test_video.mp4
"""

import argparse
import json
import math
import os
import subprocess
import sys
import wave

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

PALETTES = [
    ((30, 27, 75), (120, 40, 140)),
    ((10, 60, 90), (20, 140, 130)),
    ((90, 20, 40), (200, 90, 40)),
    ((20, 40, 100), (60, 180, 220)),
    ((60, 20, 90), (220, 60, 120)),
]


def _imports():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import arabic_reshaper
    from bidi.algorithm import get_display
    import imageio.v2 as imageio
    import imageio_ffmpeg
    return np, Image, ImageDraw, ImageFont, ImageFilter, arabic_reshaper, get_display, imageio, imageio_ffmpeg


def shape(text, reshaper, get_display):
    out = reshaper.reshape(text)
    # خط DejaVu لا يحوي محرف ﷲ (U+FDF2) ← نستبدله بصور الحروف العادية قبل العكس
    out = out.replace("ﷲ", "ﺍﻟﻠﻪ")
    return get_display(out)


def estimate_duration(text):
    import re
    if re.search(r"[\u0600-\u06FF]", text):
        chars = len(re.sub(r"\s+", "", text))
        return min(6.0, max(3.0, chars / 14))
    return min(6.0, max(3.0, len(text.split()) / 2.5))


def make_background(np, Image, ImageDraw, ImageFilter, W, H, palette, t, seed):
    """خلفية متدرجة متحركة مع توهجات عائمة."""
    top = np.array(palette[0], dtype=float)
    bottom = np.array(palette[1], dtype=float)
    shift = 0.5 + 0.5 * math.sin(t * 0.7 + seed)
    rows = np.linspace(0, 1, H)[:, None, None]
    rows = np.clip(rows + 0.12 * math.sin(t * 0.5 + seed) * (rows - 0.5) * 2, 0, 1)
    grad = top[None, None, :] * (1 - rows) + bottom[None, None, :] * rows
    frame = np.repeat(grad, W, axis=1)
    img = Image.fromarray(frame.astype("uint8"), "RGB")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i in range(3):
        cx = W * (0.5 + 0.32 * math.sin(t * (0.4 + 0.13 * i) + seed + i * 2.1))
        cy = H * (0.5 + 0.30 * math.cos(t * (0.3 + 0.11 * i) + i * 1.7))
        r = int(min(W, H) * (0.28 - 0.05 * i))
        alpha = 55 - i * 12
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    # تظليل الأطراف vignette
    yy, xx = np.mgrid[0:H, 0:W]
    dx = (xx - W / 2) / (W / 2)
    dy = (yy - H / 2) / (H / 2)
    vig = np.clip(1 - 0.32 * (dx ** 2 + dy ** 2) / 2, 0.55, 1.0)
    arr = np.asarray(img).astype(float)
    arr[..., :3] *= vig[..., None]
    return Image.fromarray(arr.astype("uint8"), "RGBA").convert("RGB")


def fit_caption(draw, ImageFont, text, W, reshaper, get_display, base_size=56):
    """اضبط الترجمة داخل الشاشة: تصغير تدريجي ثم التفاف على سطرين."""
    max_w = W - 90
    words = text.split()

    def measure(s, font):
        b = draw.textbbox((0, 0), s, font=font)
        return b[2] - b[0], b[3] - b[1]

    size = base_size
    font = ImageFont.truetype(FONT_BOLD, size)
    disp = shape(text, reshaper, get_display)
    w, _ = measure(disp, font)
    while w > max_w and size > 32:
        size -= 4
        font = ImageFont.truetype(FONT_BOLD, size)
        w, _ = measure(disp, font)
    if w <= max_w:
        return [disp], font
    # التفاف على سطرين مع إعادة التشكيل لكل سطر
    half = (len(words) + 1) // 2
    lines = [shape(" ".join(words[:half]), reshaper, get_display),
             shape(" ".join(words[half:]), reshaper, get_display)]
    while max(measure(s, font)[0] for s in lines) > max_w and size > 28:
        size -= 4
        font = ImageFont.truetype(FONT_BOLD, size)
    return lines, font


def draw_caption(Image, ImageDraw, ImageFont, base, captions, progress, W, H,
                 fonts, reshaper, get_display, scene_idx, total_scenes, keywords,
                 badge_text="اختبار", show_keywords=True):
    """ارسم الترجمة الحالية + شارة المشهد + شريط التقدم."""
    draw = ImageDraw.Draw(base, "RGBA")
    n = len(captions)
    idx = min(n - 1, int(progress * n))
    lines, font_cap = fit_caption(
        draw, ImageFont, captions[idx]["text"], W, reshaper, get_display,
        base_size=56 if W < H else 52,
    )
    bounds = [draw.textbbox((0, 0), s, font=font_cap) for s in lines]
    widths = [b[2] - b[0] for b in bounds]
    heights = [b[3] - b[1] for b in bounds]
    line_gap = 10
    block_h = sum(heights) + line_gap * (len(lines) - 1)
    tw = max(widths)
    cx, cy = W // 2, int(H * 0.52)
    pad_x, pad_y = 34, 24
    pill_top = cy - block_h // 2 - pad_y
    pill_bottom = cy + block_h // 2 + pad_y
    draw.rounded_rectangle(
        [cx - tw // 2 - pad_x, pill_top, cx + tw // 2 + pad_x, pill_bottom],
        radius=28, fill=(0, 0, 0, 165),
    )
    y = cy - block_h // 2
    for s, lh in zip(lines, heights):
        ly = y + lh // 2
        draw.text((cx + 2, ly + 3), s, font=font_cap, fill=(0, 0, 0, 200), anchor="mm")
        draw.text((cx, ly), s, font=font_cap, fill=(255, 255, 255, 255), anchor="mm")
        y += lh + line_gap
    # نقاط الكلمات
    dots_y = pill_bottom + 34
    for i in range(n):
        x = cx + (i - (n - 1) / 2) * 26
        r = 9 if i == idx else 6
        col = (255, 210, 60, 255) if i == idx else (255, 255, 255, 110)
        draw.ellipse([x - r, dots_y - r, x + r, dots_y + r], fill=col)
    # شارة المشهد
    badge = shape(f"مشهد {scene_idx + 1} / {total_scenes} — {badge_text}", reshaper, get_display)
    _bb = draw.textbbox((0, 0), badge, font=fonts["small"])
    _bw = (_bb[2] - _bb[0]) // 2 + 30
    draw.rounded_rectangle([W // 2 - _bw, 54, W // 2 + _bw, 108], radius=20, fill=(0, 0, 0, 120))
    draw.text((W // 2, 81), badge, font=fonts["small"], fill=(255, 255, 255, 230), anchor="mm")
    # الكلمات المفتاحية (صغيرة بالأعلى — للمعاينة فقط)
    if show_keywords:
        draw.text((W // 2, 130), keywords[:48], font=fonts["tiny"], fill=(255, 255, 255, 130), anchor="mm")
    # شريط التقدم
    bar_w, bar_h, bar_y = W - 120, 10, H - 70
    draw.rounded_rectangle([60, bar_y, 60 + bar_w, bar_y + bar_h], radius=5, fill=(255, 255, 255, 60))
    draw.rounded_rectangle([60, bar_y, 60 + int(bar_w * progress), bar_y + bar_h], radius=5, fill=(255, 210, 60, 255))
    return base


def write_audio_wav(np, wave, path, duration, sr=44100, silent=False):
    """مسار صوتي: وتر هادئ للمعاينة، أو صامت تماماً للمحتوى الملتزم (بدون معازف)."""
    n = int(duration * sr)
    if silent:
        stereo = np.zeros((n, 2))
    else:
        t = np.arange(n) / sr
        chord = (
            0.10 * np.sin(2 * np.pi * 220.0 * t)
            + 0.07 * np.sin(2 * np.pi * 277.18 * t)
            + 0.06 * np.sin(2 * np.pi * 329.63 * t)
        )
        fade = min(1.0, duration / 4)
        n_fade = int(fade * sr)
        chord[:n_fade] *= np.linspace(0, 1, n_fade)
        chord[-n_fade:] *= np.linspace(1, 0, n_fade)
        stereo = np.stack([chord, chord], axis=1)
    pcm = (np.clip(stereo, -1, 1) * 12000).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def main(argv=None):
    ap = argparse.ArgumentParser(description="ريندر فيديو اختبار من خطة JSON")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--max-scenes", type=int, default=0)
    ap.add_argument("--preview-dir", default="")
    ap.add_argument("--audio", default="pad", choices=["pad", "silent"],
                    help="pad=وتر معاينة، silent=بدون موسيقى (محتوى ملتزم)")
    ap.add_argument("--badge", default="اختبار", help="نص شارة المشهد")
    ap.add_argument("--hide-keywords", action="store_true", help="إخفاء سطر الكلمات المفتاحية")
    args = ap.parse_args(argv)

    np, Image, ImageDraw, ImageFont, ImageFilter, reshaper, get_display, imageio, imageio_ffmpeg = _imports()

    plan = json.load(open(args.plan, encoding="utf-8"))
    orientation = plan["video_metadata"].get("orientation", "vertical")
    scenes = plan["scenes"]
    if args.max_scenes:
        scenes = scenes[: args.max_scenes]

    W, H = (720, 1280) if orientation == "vertical" else (1280, 720)
    fonts = {
        "cap": ImageFont.truetype(FONT_BOLD, 56 if orientation == "vertical" else 52),
        "small": ImageFont.truetype(FONT_BOLD, 26),
        "tiny": ImageFont.truetype(FONT_REGULAR, 18),
    }

    durations = [estimate_duration(s["voiceover_text"]) for s in scenes]
    total_dur = sum(durations)
    print(f"المشاهد: {len(scenes)} | المدة الكلية: {total_dur:.1f}s | الأبعاد: {W}x{H}", flush=True)

    tmp_video = args.out + ".video_only.mp4"
    writer = imageio.get_writer(
        tmp_video, fps=args.fps, codec="libx264", quality=8,
        macro_block_size=None,
        ffmpeg_params=["-pix_fmt", "yuv420p"],
    )
    try:
        for si, (scene, dur) in enumerate(zip(scenes, durations)):
            palette = PALETTES[si % len(PALETTES)]
            n_frames = max(1, int(round(dur * args.fps)))
            for f in range(n_frames):
                t_global = sum(durations[:si]) + (f / args.fps)
                progress = (f + 1) / n_frames
                frame = make_background(np, Image, ImageDraw, ImageFilter, W, H, palette, t_global, seed=si * 1.7)
                frame = draw_caption(
                    Image, ImageDraw, ImageFont, frame, scene["captions"], progress,
                    W, H, fonts, reshaper, get_display, si, len(scenes), scene["search_keywords"],
                    badge_text=args.badge, show_keywords=not args.hide_keywords,
                )
                # تلاشي دخول/خروج عام
                a = np.asarray(frame).astype(float)
                t_in = sum(durations[:si]) + f / args.fps
                t_out = total_dur - t_in
                fade = min(1.0, t_in / 0.5, t_out / 0.5)
                writer.append_data(np.clip(a * max(0.0, fade), 0, 255).astype(np.uint8))
                if args.preview_dir and f == n_frames // 2:
                    frame.save(os.path.join(args.preview_dir, f"scene_{si + 1}.png"))
            print(f"  مشهد {si + 1}/{len(scenes)} تم ({dur:.1f}s)", flush=True)
    finally:
        writer.close()

    # الصوت + الدمج النهائي
    wav_path = args.out + ".audio.wav"
    write_audio_wav(np, wave, wav_path, total_dur, silent=(args.audio == "silent"))
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [ffmpeg, "-y", "-i", tmp_video, "-i", wav_path,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
         "-shortest", "-movflags", "+faststart", args.out],
        check=True, capture_output=True,
    )
    os.remove(tmp_video)
    os.remove(wav_path)
    size_mb = os.path.getsize(args.out) / 1e6
    print(f"تم ✅: {args.out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
