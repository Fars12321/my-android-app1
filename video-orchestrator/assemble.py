#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
التجميع النهائي — Final Assembler (مقاطع حقيقية + تعليق صوتي + ترجمة)
=====================================================================
لكل مشهد: مقطع حقيقي (إن وُجد في --clips-dir) وإلا صورة سينمائية
بتأثير Ken Burns، مع ترجمة ديناميكية وتعليق صوتي متزامن.

  python assemble.py --plan story_long_plan.json --audio-dir audio \
      --stills-dir stills --clips-dir footage --out musa_pharaoh_long.mp4 \
      --badge "موسى وفرعون" --preview-dir previews_long

أسماء المقاطع الحقيقية: N.mp4 أو scene_NN.mp4 (مثال: 5.mp4).
"""

import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STILLS_MAP = {
    1: "s01_nile.jpg", 2: "s02_storm.jpg", 3: "s03_basket.jpg",
    4: "s04_sunrise.jpg", 5: "s05_palace.jpg", 6: "s04_sunrise.jpg",
    7: "s07_temple.jpg", 8: "s08_oasis.jpg", 9: "s09_sinai.jpg",
    10: "s10_valley.jpg", 11: "s11_staff.jpg", 12: "s12_light.jpg",
    13: "s13_throne.jpg", 14: "s14_footprints.jpg", 15: "s12_light.jpg",
    16: "s04_sunrise.jpg", 17: "s17_locust.jpg", 18: "s18_moon.jpg",
    19: "s19_parted.jpg", 20: "s20_waves.jpg", 21: "s04_sunrise.jpg",
}

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _imports():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    import arabic_reshaper
    from bidi.algorithm import get_display
    import imageio.v2 as imageio
    import imageio_ffmpeg
    from render_test import shape, fit_caption
    return np, Image, ImageDraw, ImageFont, arabic_reshaper, get_display, imageio, imageio_ffmpeg, shape, fit_caption


def probe_duration(ffmpeg, path):
    p = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    if not m:
        raise RuntimeError(f"تعذر قراءة مدة {path}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def find_clip(clips_dir, scene_no):
    if not clips_dir:
        return None
    for name in (f"{scene_no}.mp4", f"scene_{scene_no:02d}.mp4"):
        p = os.path.join(clips_dir, name)
        if os.path.exists(p) and os.path.getsize(p) > 100_000:
            return p
    return None


def build_bg_clip(ffmpeg, still_path, scene_frames, fps, out_path, variant):
    """حوّل الصورة إلى مقطع Ken Burns (تقريب/إبعاد/تحريك)."""
    n = scene_frames
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if variant == 0:      # تقريب
        z, x, y = f"1+0.12*on/{n}", cx, cy
    elif variant == 1:    # إبعاد
        z, x, y = f"1.12-0.12*on/{n}", cx, cy
    else:                 # تحريك أفقي
        z, x, y = "1.12", f"(iw-iw/zoom)*on/{n}", cy
    vf = (f"scale=2560:-2,zoompan=z='{z}':x='{x}':y='{y}':d=1:s=1280x720")
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-loop", "1", "-framerate", str(fps),
         "-i", still_path, "-vf", vf, "-frames:v", str(n),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         out_path],
        check=True,
    )


def build_bg_real(ffmpeg, clip_path, scene_dur, fps, out_path):
    """جهّز المقطع الحقيقي: تكرار/قص + توحيد الأبعاد والإطارات."""
    clip_dur = probe_duration(ffmpeg, clip_path)
    pre = ["-stream_loop", "-1"] if clip_dur < scene_dur else []
    vf = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24"
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", *pre, "-i", clip_path, "-t",
         f"{scene_dur:.2f}", "-vf", vf, "-an", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "veryfast", out_path],
        check=True,
    )


def render_overlays(Image, ImageDraw, ImageFont, W, H, captions, badge_text,
                    scene_idx, total, reshaper, get_display, shape, fit_caption):
    """ارسم طبقات الترجمة والشارة مسبقاً (مرة واحدة لكل مشهد)."""
    f_cap = 52
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    chunk_layers = []
    for cap in captions:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        lines, font = fit_caption(ld, ImageFont, cap["text"], W, reshaper,
                                  get_display, base_size=f_cap)
        bounds = [ld.textbbox((0, 0), s, font=font) for s in lines]
        widths = [b[2] - b[0] for b in bounds]
        heights = [b[3] - b[1] for b in bounds]
        gap = 10
        block_h = sum(heights) + gap * (len(lines) - 1)
        tw = max(widths)
        cx, cy = W // 2, int(H * 0.60)
        px, py = 34, 24
        top, bottom = cy - block_h // 2 - py, cy + block_h // 2 + py
        ld.rounded_rectangle([cx - tw // 2 - px, top, cx + tw // 2 + px, bottom],
                             radius=28, fill=(0, 0, 0, 170))
        y = cy - block_h // 2
        for s, lh in zip(lines, heights):
            ly = y + lh // 2
            ld.text((cx + 2, ly + 3), s, font=font, fill=(0, 0, 0, 200), anchor="mm")
            ld.text((cx, ly), s, font=font, fill=(255, 255, 255, 255), anchor="mm")
            y += lh + gap
        dots_y = bottom + 30
        for i in range(len(captions)):
            x = cx + (i - (len(captions) - 1) / 2) * 24
            on = (captions[i]["text"] == cap["text"])
            r = 8 if on else 5
            col = (255, 210, 60, 255) if on else (255, 255, 255, 110)
            ld.ellipse([x - r, dots_y - r, x + r, dots_y + r], fill=col)
        chunk_layers.append(layer)
    badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge_layer)
    badge = shape(f"مشهد {scene_idx + 1} / {total} — {badge_text}", reshaper, get_display)
    f_small = ImageFont.truetype(FONT_BOLD, 24)
    bb = bd.textbbox((0, 0), badge, font=f_small)
    bw = (bb[2] - bb[0]) // 2 + 28
    bd.rounded_rectangle([W // 2 - bw, 40, W // 2 + bw, 90], radius=18, fill=(0, 0, 0, 120))
    bd.text((W // 2, 65), badge, font=f_small, fill=(255, 255, 255, 230), anchor="mm")
    return chunk_layers, badge_layer


def main(argv=None):
    ap = argparse.ArgumentParser(description="التجميع النهائي للفيديو")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--stills-dir", required=True)
    ap.add_argument("--clips-dir", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--badge", default="موسى وفرعون")
    ap.add_argument("--preview-dir", default="")
    ap.add_argument("--lead", type=float, default=0.3)
    ap.add_argument("--tail", type=float, default=0.5)
    args = ap.parse_args(argv)

    (np, Image, ImageDraw, ImageFont, reshaper, get_display, imageio,
     imageio_ffmpeg, shape, fit_caption) = _imports()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    W, H = 1280, 720

    plan = json.load(open(args.plan, encoding="utf-8"))
    scenes = plan["scenes"]
    tmp = tempfile.mkdtemp(prefix="assemble_")

    # 1) المدد من التعليق الصوتي الفعلي
    durs, tts_paths = [], []
    for s in scenes:
        n = s["scene_number"]
        tp = os.path.join(args.audio_dir, f"scene_{n:02d}.mp3")
        if not os.path.exists(tp):
            raise SystemExit(f"التعليق مفقود للمشهد {n}: {tp}")
        tts_paths.append(tp)
        d = probe_duration(ffmpeg, tp)
        durs.append(args.lead + d + args.tail)
    total_dur = sum(durs)
    total_frames = sum(max(1, int(round(d * args.fps))) for d in durs)
    print(f"المشاهد: {len(scenes)} | المدة: {total_dur:.1f}s | {W}x{H}", flush=True)

    # تظليل جاهز + كاتب الفيديو
    yy, xx = np.mgrid[0:H, 0:W]
    vig = np.clip(1 - 0.30 * (((xx - W / 2) / (W / 2)) ** 2 +
                              ((yy - H / 2) / (H / 2)) ** 2) / 2, 0.6, 1.0)
    tmp_video = os.path.join(tmp, "video.mp4")
    writer = imageio.get_writer(tmp_video, fps=args.fps, codec="libx264",
                                quality=8, macro_block_size=None,
                                ffmpeg_params=["-pix_fmt", "yuv420p"])
    gframe = 0
    try:
        for si, (s, dur) in enumerate(zip(scenes, durs)):
            n = s["scene_number"]
            n_frames = max(1, int(round(dur * args.fps)))
            seg = os.path.join(tmp, f"seg_{n:02d}.mp4")
            clip = find_clip(args.clips_dir, n)
            if clip:
                build_bg_real(ffmpeg, clip, dur, args.fps, seg)
                src = "مقطع حقيقي"
            else:
                still = os.path.join(args.stills_dir, STILLS_MAP[n])
                build_bg_clip(ffmpeg, still, n_frames, args.fps, seg, si % 3)
                src = "مشهد سينمائي"
            layers, badge_layer = render_overlays(
                Image, ImageDraw, ImageFont, W, H, s["captions"], args.badge,
                si, len(scenes), reshaper, get_display, shape, fit_caption)
            reader = imageio.get_reader(seg)
            got = 0
            for fi, frame in enumerate(reader):
                if fi >= n_frames:
                    break
                prog = (fi + 1) / n_frames
                base = Image.fromarray(frame).convert("RGBA")
                arr = np.asarray(base).astype(float)
                arr[..., :3] *= (vig * 0.92)[..., None]
                base = Image.fromarray(arr.astype("uint8"), "RGBA")
                ci = min(len(layers) - 1, int(prog * len(layers)))
                base = Image.alpha_composite(base, layers[ci])
                base = Image.alpha_composite(base, badge_layer)
                ov = ImageDraw.Draw(base, "RGBA")
                bw_, bh_, by_ = W - 160, 8, H - 46
                ov.rounded_rectangle([80, by_, 80 + bw_, by_ + bh_], radius=4,
                                     fill=(255, 255, 255, 55))
                gp = (gframe + 1) / total_frames
                ov.rounded_rectangle([80, by_, 80 + int(bw_ * gp), by_ + bh_],
                                     radius=4, fill=(255, 210, 60, 255))
                out = np.asarray(base.convert("RGB")).astype(float)
                edge = min(1.0, fi / 6, (n_frames - 1 - fi) / 6,
                           gframe / 10, (total_frames - 1 - gframe) / 10)
                writer.append_data(np.clip(out * max(0.0, edge), 0, 255).astype(np.uint8))
                if args.preview_dir and fi == n_frames // 2:
                    base.convert("RGB").save(os.path.join(args.preview_dir, f"scene_{n:02d}.png"))
                gframe += 1
                got += 1
            reader.close()
            print(f"  مشهد {n}/{len(scenes)} ({dur:.1f}s) ← {src}", flush=True)
    finally:
        writer.close()

    # 2) المسار الصوتي: تعليق كل مشهد في موضعه
    segs = []
    for tp, dur in zip(tts_paths, durs):
        seg_a = os.path.join(tmp, os.path.basename(tp) + ".m4a")
        subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", tp, "-af",
             f"adelay={int(args.lead * 1000)}|{int(args.lead * 1000)},apad",
             "-t", f"{dur:.2f}", "-c:a", "aac", seg_a], check=True)
        segs.append(seg_a)
    lst = os.path.join(tmp, "alist.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in segs))
    full_a = os.path.join(tmp, "full.m4a")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", full_a], check=True)
    subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", tmp_video, "-i", full_a,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
         "-movflags", "+faststart", args.out], check=True)
    print(f"تم ✅: {args.out} ({os.path.getsize(args.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
