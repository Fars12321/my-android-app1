# محرك إنتاج الفيديو الذكي — AI Video Orchestrator 🎬

مهارة برمجية متكاملة مستوحاة من Invideo AI: تحويل أي فكرة فيديو إلى
**خطة إنتاج JSON** جاهزة لأداة المونتاج، مع جلب مقاطع B-roll من
**Pexels** و **Pixabay** وتوليد ترجمة ديناميكية.

## القواعد الإلزامية المطبقة

1. **تحليل الطلب**: الموضوع + النبرة (حماسية/تعليمية/درامية/هادئة) +
   الأبعاد (`vertical` بـ 9:16 لـ Shorts/TikTok أو `horizontal` ب��� 16:9 ليوتيوب).
2. **السيناريو**: مشاهد قصيرة، المدة النطقية لكل مشهد **3-6 ثوانٍ**.
3. **الكلمات المفتاحية**: إنجليزية حصراً، دقيقة ووصفية (3 كلمات على الأقل).
4. **الترجمة**: **2-4 كلمات** لكل سطر، متزامنة في منتصف الشاشة.

## التثبيت

```bash
cd video-orchestrator
pip install -r requirements.txt
cp .env.example .env   # ثم ضع المفتاحين الحقيقيين داخل .env
export PEXELS_API_KEY="..."
export PIXABAY_API_KEY="..."
```

> ⚠️ لا تخزّن المفاتيح في الكود أبداً. ملف `.env` مستثنى من Git.

## الأوامر

```bash
# 1) تأكيد المفاتيح
python orchestrator.py verify

# 2) جلب B-roll (Pexels أولاً، ثم fallback تلقائي إلى Pixabay)
python orchestrator.py fetch --keywords "futuristic city neon lights night" --orientation vertical

# 3) تقسيم نص إلى ترجمة ديناميكية
python orchestrator.py split --text "تم تفعيل محرك إنتاج الفيديو الذكي بنجاح"

# 4) بناء خطة الإنتاج من ملف مشاهد
python orchestrator.py build --topic "موضوع الفيديو" --orientation vertical \
  --scenes scenes.json --out plan.json
```

ملف `scenes.json` المدخل:

```json
[
  {
    "voiceover_text": "نص التعليق الصوتي الكامل للمشهد.",
    "search_keywords": "descriptive english keywords footage"
  }
]
```

## هيكل المخرج الإلزامي (مثال حي: `example_output.json`)

```json
{
  "video_metadata": {
    "topic": "موضوع الفيديو هنا",
    "orientation": "vertical",
    "total_estimated_scenes": "10"
  },
  "scenes": [
    {
      "scene_number": 1,
      "voiceover_text": "نص التعليق الصوتي الكامل.",
      "search_keywords": "english search keywords for footage",
      "captions": [
        {"text": "الكلمة الأولى والثانية", "display_order": 1},
        {"text": "الكلمة الثالثة والرابعة", "display_order": 2}
      ]
    }
  ]
}
```

## خط المونتاج المقترح (لأداة التنفيذ)

1. اقرأ `plan.json` → لكل مشهد استدعِ `fetch` بالكلمات المفتاحية.
2. حمّل أفضل مقطع → قص/وسّط حسب الأبعاد (عمودي: 1080x1920).
3. ولّد التعليق الصوتي (TTS) من `voiceover_text`.
4. ركّب `captions` كلمة-بكلمة في منتصف الشاشة (مثال: `ffmpeg` + `drawtext`/`ass`).
5. ادمج المشاهد بالترتيب → الفيديو النهائي جاهز للنشر.
