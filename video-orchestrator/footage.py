#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تحميل مقاطع B-roll الحقيقية من Pexels و Pixabay — Real Footage Downloader
=========================================================================
يقرأ خطة الإنتاج JSON ويحمّل مقطعاً حقيقياً لكل مشهد حسب search_keywords.

يعمل على أي جهاز بإنترنت مفتوح (الحاسوب الشخصي / Termux على أندرويد):
  export PEXELS_API_KEY="..." PIXABAY_API_KEY="..."
  pip install requests
  python footage.py --plan story_long_plan.json --out-dir footage

ملاحظة: Pexels أولاً ثم Pixabay تلقائياً، مع فلترة أولية مناسبة للمحتوى الملتزم
(أفقي 16:9، بدون بحث عن أشخاص — راجع المقاطع قبل النشر).
"""

import argparse
import json
import os
import sys
import time

import requests

PEXELS_URL = "https://api.pexels.com/videos/search"
PIXABAY_URL = "https://pixabay.com/api/videos/"


def _download(url, path, timeout=120):
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in r.iter_content(1024 * 256):
                fh.write(chunk)
    return path


def pexels_clip(api_key, keywords, timeout=30):
    """ابحث في Pexels وأعد أفضل ملف أفقي HD."""
    r = requests.get(
        PEXELS_URL,
        headers={"Authorization": api_key},
        params={"query": keywords, "orientation": "landscape",
                "size": "medium", "per_page": 5},
        timeout=timeout,
    )
    if r.status_code == 401:
        raise RuntimeError("مفتاح Pexels غير صالح (401)")
    r.raise_for_status()
    best, best_score = None, -1
    for item in r.json().get("videos", []):
        for f in item.get("video_files", []):
            w, h, link = f.get("width", 0), f.get("height", 0), f.get("link")
            if not link or w < 1280 or h >= w:
                continue
            score = w * h
            if score > best_score:
                best, best_score = {"url": link, "w": w, "h": h,
                                    "page": item.get("url")}, score
    return ("pexels", best) if best else ("pexels", None)


def pixabay_clip(api_key, keywords, timeout=30):
    """ابحث في Pixabay وأعد أفضل ملف أفقي."""
    r = requests.get(
        PIXABAY_URL,
        params={"key": api_key, "q": keywords, "per_page": 5,
                "min_width": 1280, "safesearch": "true"},
        timeout=timeout,
    )
    r.raise_for_status()
    best, best_score = None, -1
    for item in r.json().get("hits", []):
        for v in item.get("videos", {}).values():
            w, h, url = v.get("width", 0), v.get("height", 0), v.get("url")
            if not url or w < 1280 or h >= w:
                continue
            score = w * h
            if score > best_score:
                best, best_score = {"url": url, "w": w, "h": h,
                                    "page": item.get("pageURL")}, score
    return ("pixabay", best) if best else ("pixabay", None)


def fetch_scene_clip(keywords, scene_no, out_dir, delay=1.0):
    """حمّل مقطع مشهد واحد (Pexels ثم Pixabay) وأعد مساره."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{scene_no}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 100_000:
        return {"scene": scene_no, "path": out, "cached": True}
    errors = {}
    if os.environ.get("PEXELS_API_KEY"):
        try:
            src, clip = pexels_clip(os.environ["PEXELS_API_KEY"], keywords)
            if clip:
                _download(clip["url"], out)
                return {"scene": scene_no, "path": out, "source": src,
                        "page": clip["page"], "res": f"{clip['w']}x{clip['h']}"}
            errors["pexels"] = "لا نتائج أفقية"
        except Exception as exc:  # noqa: BLE001
            errors["pexels"] = str(exc)[:150]
    else:
        errors["pexels"] = "PEXELS_API_KEY مفقود"
    time.sleep(delay)
    if os.environ.get("PIXABAY_API_KEY"):
        try:
            src, clip = pixabay_clip(os.environ["PIXABAY_API_KEY"], keywords)
            if clip:
                _download(clip["url"], out)
                return {"scene": scene_no, "path": out, "source": src,
                        "page": clip["page"], "res": f"{clip['w']}x{clip['h']}"}
            errors["pixabay"] = "لا نتائج أفقية"
        except Exception as exc:  # noqa: BLE001
            errors["pixabay"] = str(exc)[:150]
    else:
        errors["pixabay"] = "PIXABAY_API_KEY مفقود"
    return {"scene": scene_no, "path": None, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser(description="تحميل مقاطع حقيقية لكل مشهد")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out-dir", default="footage")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--max", type=int, default=0)
    args = ap.parse_args(argv)
    plan = json.load(open(args.plan, encoding="utf-8"))
    scenes = plan["scenes"][: args.max or None]
    report = []
    for s in scenes:
        print(f"مشهد {s['scene_number']}: {s['search_keywords'][:60]}...",
              flush=True)
        rep = fetch_scene_clip(s["search_keywords"], s["scene_number"],
                               args.out_dir, args.delay)
        report.append(rep)
        print("  ←", rep.get("source", rep.get("errors")), flush=True)
    ok = sum(1 for r in report if r.get("path"))
    json.dump(report, open(os.path.join(args.out_dir, "_report.json"), "w",
                           encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"تم: {ok}/{len(scenes)} مقطعاً في {args.out_dir}/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
