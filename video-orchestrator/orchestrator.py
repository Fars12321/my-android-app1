#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محرك إنتاج الفيديو الذكي — AI Video Orchestrator Skill
=====================================================
مهارة برمجية متكاملة: توليد خطة الإنتاج (JSON) + جلب مقاطع B-roll
من Pexels و Pixabay + تقسيم الترجمة الديناميكية + التحقق من المفاتيح.

المفاتيح تُقرأ من متغيرات البيئة فقط (لا تُخزَّن في الكود أبداً):
  PEXELS_API_KEY
  PIXABAY_API_KEY

الاستخدام:
  python orchestrator.py verify
  python orchestrator.py fetch --keywords "neon city night" --orientation vertical
  python orchestrator.py split --text "نص التعليق الصوتي هنا"
  python orchestrator.py build --topic "..." --orientation vertical --scenes scenes.json --out plan.json
"""

import argparse
import json
import os
import re
import sys

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_VIDEO_SEARCH_URL = "https://pixabay.com/api/videos/"

ORIENTATIONS = ("vertical", "horizontal")
DIMENSIONS = {"vertical": "1080x1920 (9:16)", "horizontal": "1920x1080 (16:9)"}
TONES = ("حماسية", "تعليمية", "درامية", "هادئة", "energetic", "educational", "dramatic", "calm")

# سرعة النطق التقريبية للتحقق من قاعدة 3-6 ثوانٍ لكل مشهد
ARABIC_CHARS_PER_SECOND = 14
ENGLISH_WORDS_PER_SECOND = 2.5

_ENGLISH_KEYWORDS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\s,\-']*$")


def _require_requests():
    try:
        import requests  # type: ignore
        return requests
    except ImportError:
        raise SystemExit(
            "مكتبة requests غير مثبتة. ثبّتها عبر: pip install -r requirements.txt"
        )


def split_captions(voiceover_text, max_words=4, min_words=2):
    """قسّم نص التعليق الصوتي إلى ترجمة ديناميكية (2-4 كلمات لكل سطر)."""
    words = voiceover_text.split()
    if not words:
        return []
    chunks, current = [], []
    for word in words:
        current.append(word)
        if len(current) == max_words:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    # إصلاح الخانة الأخيرة إذا كانت كلمة واحدة: اسحب كلمة من السابقة
    if len(chunks) > 1 and len(chunks[-1]) < min_words:
        while len(chunks[-1]) < min_words and len(chunks[-2]) > min_words:
            chunks[-1].insert(0, chunks[-2].pop())
        if len(chunks[-1]) < min_words:  # دمج نهائي عند الضرورة
            chunks[-2].extend(chunks[-1])
            chunks.pop()
    return [
        {"text": " ".join(chunk), "display_order": i + 1}
        for i, chunk in enumerate(chunks)
    ]


def estimate_duration_seconds(voiceover_text):
    """تقدير المدة النطقية بالثواني (عربي حسب الأحرف، إنجليزي حسب الكلمات)."""
    if re.search(r"[\u0600-\u06FF]", voiceover_text):
        chars = len(re.sub(r"\s+", "", voiceover_text))
        return round(chars / ARABIC_CHARS_PER_SECOND, 1)
    return round(len(voiceover_text.split()) / ENGLISH_WORDS_PER_SECOND, 1)


def validate_keywords(search_keywords):
    """الكلمات المفتاحية يجب أن تكون إنجليزية حصراً ومحددة (3 كلمات على الأقل)."""
    if not _ENGLISH_KEYWORDS_RE.match(search_keywords or ""):
        return False, "search_keywords يجب أن تكون بالإنجليزية حصراً"
    if len(search_keywords.split()) < 3:
        return False, "search_keywords يجب أن تكون وصفية (3 كلمات على الأقل)"
    return True, "ok"


def build_scene(scene_number, voiceover_text, search_keywords):
    """ابنِ مشهداً واحداً مطابقاً للهيكل الإلزامي مع فحص القواعد."""
    ok, reason = validate_keywords(search_keywords)
    if not ok:
        raise ValueError(f"المشهد {scene_number}: {reason}")
    duration = estimate_duration_seconds(voiceover_text)
    if not 3 <= duration <= 6.5:
        print(
            f"تحذير: المشهد {scene_number} مدته التقديرية {duration}s "
            f"(خارج نطاق 3-6 ثوانٍ)",
            file=sys.stderr,
        )
    return {
        "scene_number": scene_number,
        "voiceover_text": voiceover_text,
        "search_keywords": search_keywords,
        "captions": split_captions(voiceover_text),
    }


def build_plan(topic, orientation, scenes_input):
    """ابنِ خطة الإنتاج النهائية (JSON) بالهيكل الإلزامي حرفياً."""
    if orientation not in ORIENTATIONS:
        raise ValueError("orientation يجب أن تكون vertical أو horizontal")
    scenes = [
        build_scene(i + 1, s["voiceover_text"], s["search_keywords"])
        for i, s in enumerate(scenes_input)
    ]
    return {
        "video_metadata": {
            "topic": topic,
            "orientation": orientation,
            "total_estimated_scenes": str(len(scenes)),
        },
        "scenes": scenes,
    }


# ---------------------------------------------------------------- APIs ---
def verify_pexels(api_key, timeout=20):
    """تحقق من مفتاح Pexels عبر بحث تجريبي."""
    requests = _require_requests()
    if not api_key:
        return {"service": "pexels", "ok": False, "detail": "المفتاح مفقود"}
    try:
        resp = requests.get(
            PEXELS_VIDEO_SEARCH_URL,
            headers={"Authorization": api_key},
            params={"query": "nature", "per_page": 1},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return {"service": "pexels", "ok": True, "detail": "المفتاح يعمل"}
        if resp.status_code == 401:
            return {"service": "pexels", "ok": False, "detail": "مفتاح غير صالح (401)"}
        return {
            "service": "pexels",
            "ok": False,
            "detail": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"service": "pexels", "ok": False, "detail": f"خطأ اتصال: {exc}"}


def verify_pixabay(api_key, timeout=20):
    """تحقق من مفتاح Pixabay عبر بحث تجريبي (per_page الأدنى = 3)."""
    requests = _require_requests()
    if not api_key:
        return {"service": "pixabay", "ok": False, "detail": "المفتاح مفقود"}
    try:
        resp = requests.get(
            PIXABAY_VIDEO_SEARCH_URL,
            params={"key": api_key, "q": "nature", "per_page": 3},
            timeout=timeout,
        )
        data = resp.json() if resp.status_code == 200 else {}
        if resp.status_code == 200 and "totalHits" in data:
            return {"service": "pixabay", "ok": True, "detail": "المفتاح يعمل"}
        return {
            "service": "pixabay",
            "ok": False,
            "detail": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"service": "pixabay", "ok": False, "detail": f"خطأ اتصال: {exc}"}


def _best_variant(variants, orientation):
    """اختر أفضل نسخة فيديو متاحة حسب الاتجاه المطلوب."""
    if not variants:
        return None
    vertical = orientation == "vertical"
    ranked = sorted(
        variants,
        key=lambda v: (
            0 if (vertical == ((v.get("height", 0) > v.get("width", 0)))) else 1,
            -(v.get("width", 0) * v.get("height", 0)),
        ),
    )
    return ranked[0]


def search_pexels(api_key, keywords, orientation="vertical", per_page=3, timeout=20):
    """ابحث في Pexels Videos API وأعد مقاطع موحدة البنية."""
    requests = _require_requests()
    resp = requests.get(
        PEXELS_VIDEO_SEARCH_URL,
        headers={"Authorization": api_key},
        params={
            "query": keywords,
            "orientation": "portrait" if orientation == "vertical" else "landscape",
            "per_page": per_page,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    clips = []
    for item in resp.json().get("videos", []):
        files = [
            {
                "width": f.get("width", 0),
                "height": f.get("height", 0),
                "url": f.get("link"),
            }
            for f in item.get("video_files", [])
        ]
        best = _best_variant([f for f in files if f["url"]], orientation)
        if not best:
            continue
        clips.append(
            {
                "source": "pexels",
                "id": item.get("id"),
                "duration": item.get("duration"),
                "width": best["width"],
                "height": best["height"],
                "video_url": best["url"],
                "preview_url": item.get("image"),
                "page_url": item.get("url"),
            }
        )
    return clips


def search_pixabay(api_key, keywords, orientation="vertical", per_page=3, timeout=20):
    """ابحث في Pixabay Videos API وأعد مقاطع موحدة البنية."""
    requests = _require_requests()
    resp = requests.get(
        PIXABAY_VIDEO_SEARCH_URL,
        params={"key": api_key, "q": keywords, "per_page": max(3, per_page)},
        timeout=timeout,
    )
    resp.raise_for_status()
    clips = []
    for item in resp.json().get("hits", []):
        variants = [
            {
                "width": v.get("width", 0),
                "height": v.get("height", 0),
                "url": v.get("url"),
            }
            for v in item.get("videos", {}).values()
        ]
        best = _best_variant([v for v in variants if v["url"]], orientation)
        if not best:
            continue
        clips.append(
            {
                "source": "pixabay",
                "id": item.get("id"),
                "duration": item.get("duration"),
                "width": best["width"],
                "height": best["height"],
                "video_url": best["url"],
                "preview_url": best.get("thumbnail") or item.get("previewURL"),
                "page_url": item.get("pageURL"),
                "tags": item.get("tags"),
            }
        )
    vertical = orientation == "vertical"
    clips.sort(
        key=lambda c: 0
        if (vertical == (c["height"] > c["width"]))
        else 1
    )
    return clips


def fetch_broll(keywords, orientation="vertical", per_page=3):
    """اجلب B-roll مع fallback تلقائي: Pexels أولاً ثم Pixabay."""
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
    errors = {}
    if pexels_key:
        try:
            clips = search_pexels(pexels_key, keywords, orientation, per_page)
            if clips:
                return {"keywords": keywords, "source_used": "pexels", "clips": clips}
            errors["pexels"] = "لا نتائج"
        except Exception as exc:  # noqa: BLE001
            errors["pexels"] = str(exc)[:200]
    else:
        errors["pexels"] = "PEXELS_API_KEY مفقود"
    if pixabay_key:
        try:
            clips = search_pixabay(pixabay_key, keywords, orientation, per_page)
            if clips:
                return {"keywords": keywords, "source_used": "pixabay", "clips": clips}
            errors["pixabay"] = "لا نتائج"
        except Exception as exc:  # noqa: BLE001
            errors["pixabay"] = str(exc)[:200]
    else:
        errors["pixabay"] = "PIXABAY_API_KEY مفقود"
    return {"keywords": keywords, "source_used": None, "clips": [], "errors": errors}


# ----------------------------------------------------------------- CLI ---
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="محرك إنتاج الفيديو الذكي — AI Video Orchestrator"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify", help="تحقق من مفاتيح Pexels و Pixabay")

    p_fetch = sub.add_parser("fetch", help="اجلب مقاطع B-roll لكلمات مفتاحية")
    p_fetch.add_argument("--keywords", required=True)
    p_fetch.add_argument("--orientation", default="vertical", choices=list(ORIENTATIONS))
    p_fetch.add_argument("--per-page", type=int, default=3)

    p_split = sub.add_parser("split", help="قسّم نصاً إلى ترجمة ديناميكية")
    p_split.add_argument("--text", required=True)
    p_split.add_argument("--max-words", type=int, default=4)

    p_build = sub.add_parser("build", help="ابنِ خطة الإنتاج JSON من ملف مشاهد")
    p_build.add_argument("--topic", required=True)
    p_build.add_argument("--orientation", default="vertical", choices=list(ORIENTATIONS))
    p_build.add_argument("--scenes", required=True, help="ملف JSON: قائمة voiceover_text + search_keywords")
    p_build.add_argument("--out", default="", help="مسار الحفظ (اختياري)")

    args = parser.parse_args(argv)

    if args.command == "verify":
        report = {
            "pexels": verify_pexels(os.environ.get("PEXELS_API_KEY", "")),
            "pixabay": verify_pixabay(os.environ.get("PIXABAY_API_KEY", "")),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(v["ok"] for v in report.values()) else 1

    if args.command == "fetch":
        print(
            json.dumps(
                fetch_broll(args.keywords, args.orientation, args.per_page),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "split":
        print(
            json.dumps(
                split_captions(args.text, args.max_words),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "build":
        with open(args.scenes, encoding="utf-8") as fh:
            scenes_input = json.load(fh)
        plan = build_plan(args.topic, args.orientation, scenes_input)
        output = json.dumps(plan, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(output + "\n")
        print(output)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
