# -*- coding: utf-8 -*-
"""
I-SELECT (Applicant Intake) — Gemma-only extraction backend

Workflow:
  1) Frontend records voice and stops after ~3s silence (frontend).
  2) Frontend sends transcription text to /nlp/parse.
  3) Backend calls Gemma (Ollama) to extract a strict JSON profile.
  4) Backend post-processes & returns fields to pre-fill form.
  5) On submit, record is appended to Excel (data/people.xlsx).

ENV (optional):
  OLLAMA_MODEL=gemma3:1b   # or gemma3:4b, etc.
"""

import os
import csv
import re
import json
from datetime import datetime

import pandas as pd
from flask import Flask, render_template, request, jsonify

# ---- Ollama (required for this workflow) ------------------------------------
try:
    import ollama  # pip install ollama
except Exception as e:
    ollama = None
    print("⚠️ Ollama not available. Install `pip install ollama` and run the Ollama server.")

# -----------------------------------------------------------------------------
# App config
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["DATA_FOLDER"] = "data"
app.config["EXCEL_PATH"] = os.path.join(app.config["DATA_FOLDER"], "people.xlsx")
app.config["NAME_LEXICON_PATH"] = os.path.join(app.config["DATA_FOLDER"], "names_fa.csv")  # optional CSV
os.makedirs(app.config["DATA_FOLDER"], exist_ok=True)

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")

# -----------------------------------------------------------------------------
# Normalizers
# -----------------------------------------------------------------------------
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS  = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def norm(s: str) -> str:
    if s is None:
        return ""
    return str(s).strip()

def normalize_digits(s: str) -> str:
    s = str(s or "")
    return s.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)

def normalize_spaces(s: str) -> str:
    # ZWNJ -> space; collapse spaces
    s = (s or "").replace("\u200c", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def to_int_or_empty(v):
    if v in (None, "", "null"):
        return ""
    try:
        return int(float(str(v)))
    except Exception:
        return ""

# -----------------------------------------------------------------------------
# Optional name lexicon for gender fallback (no regex on utterance; just post fix)
# -----------------------------------------------------------------------------
BUILTIN_MALE = {
    "علی","حسین","محمد","رضا","مهدی","امیر","حمید","سعید","هادی","حامد","وحید","مصطفی","حسن","مجتبی",
    "مجید","میلاد","احمد","کاظم","بهزاد","روح‌الله","روح الله","یاسر","محسن","نیما","کیان","پارسا",
}
BUILTIN_FEMALE = {
    "زهرا","فاطمه","مریم","سارا","سمیرا","مینا","مهسا","نازنین","الهام","پریسا","نیلوفر","ریحانه","نگار","هدیه",
    "راضیه","معصومه","شبنم","ثنا","ملیکا","حدیث","حدیثه","فرشته","سوگند","ستایش","نرگس","آتنا","آیناز",
}

def load_name_lexicon():
    male = set(BUILTIN_MALE)
    female = set(BUILTIN_FEMALE)
    path = app.config["NAME_LEXICON_PATH"]
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    first = (row[0] or "").strip()
                    g_raw = (row[1] if len(row) > 1 else "").strip()
                    if not first or not g_raw:
                        continue
                    if "مرد" in g_raw:
                        male.add(first)
                    elif "زن" in g_raw:
                        female.add(first)
        except Exception as e:
            print("⚠️ name lexicon load error:", e)
    return male, female

MALE_NAMES, FEMALE_NAMES = load_name_lexicon()

def gender_from_first_name(first_name: str) -> str:
    n = norm(first_name)
    if not n:
        return ""
    if n in MALE_NAMES: return "مرد"
    if n in FEMALE_NAMES: return "زن"
    # latin-insensitive
    n_l = n.lower()
    if n_l in {x.lower() for x in MALE_NAMES}: return "مرد"
    if n_l in {x.lower() for x in FEMALE_NAMES}: return "زن"
    return ""

# -----------------------------------------------------------------------------
# Skill pretty mapping (post-format only; extraction is done by Gemma)
# -----------------------------------------------------------------------------
BUILTIN_SKILL_SYNS = {
    "Python": {"python","پایتون"},
    "SQL": {"sql","اس کیو ال","اس‌کیوال"},
    "یادگیری ماشین": {"machine learning","ml","یادگیری ماشین","ماشین لرنینگ"},
    "یادگیری عمیق": {"deep learning","دیپ لرنینگ","یادگیری عمیق"},
    "هوش مصنوعی": {"ai","هوش مصنوعی"},
    "Excel": {"excel","اکسل"},
    "Power BI": {"power bi","powerbi","پاور بی‌آی","پاور بی ای"},
    "PLC": {"plc","پی ال سی"},
    "JavaScript": {"javascript","جاوااسکریپت","js"},
    "React": {"react","ری اکت","ری‌اکت"},
}

def prettify_and_dedup_list(items):
    # Expect list[str]; normalize, map synonyms to pretty labels, dedup
    seen = set()
    out = []
    for it in (items or []):
        t = normalize_spaces(normalize_digits(str(it))).lower()
        if not t:
            continue
        pretty = None
        for label, syns in BUILTIN_SKILL_SYNS.items():
            if any(re.search(rf"(?<![آ-یa-z0-9]){re.escape(s)}(?![آ-یa-z0-9])", t) for s in syns):
                pretty = label
                break
        final = pretty or it.strip()
        key = final.lower()
        if key not in seen:
            seen.add(key)
            out.append(final)
    return out

def list_to_csv(items):
    return ", ".join([x for x in (items or []) if str(x).strip()])

# -----------------------------------------------------------------------------
# Gemma (Ollama) — JSON-only extractor
# -----------------------------------------------------------------------------
LLM_SYSTEM = """
تو یک استخراج‌گر اطلاعات پروفایل هستی. فقط یک JSON خالص و معتبر برگردان؛ هیچ متن اضافی ننویس.
فیلدها دقیقا این‌ها هستند:
{
  "first_name": string,
  "last_name": string,
  "age": number | "",
  "gender": "مرد" | "زن" | "",
  "experience_years": number | "",
  "city": string | "",
  "military_status": "دارد" | "ندارد" | "",
  "skills": string[],        // فهرست کوتاه مهارت‌ها، یکتا و تمیز
  "interests": string[]      // فهرست کوتاه علایق
}
قواعد:
- اگر جنسیت صراحتا ذکر نشده بود ولی از نام کوچک بتوان حدس زد، مقدار مناسب قرار بده.
- اگر چیزی معلوم نبود، مقدار خالی "" یا آرایه خالی [] بده.
- فقط JSON نتیجه را چاپ کن.
"""

def build_llm_user_prompt(transcript: str) -> str:
    txt = normalize_spaces(normalize_digits(transcript or ""))
    # Give a couple of in-context examples (very short) to bias format
    examples = [
        {
            "input": "من علی رضایی ۲۸ سالمه، ۴ سال سابقه کار دارم، ساکن تهران. مهارت‌هام پایتون و SQL. علایق: هوش مصنوعی.",
            "output": {
                "first_name":"علی","last_name":"رضایی","age":28,"gender":"مرد",
                "experience_years":4,"city":"تهران","military_status":"",
                "skills":["Python","SQL"],"interests":["هوش مصنوعی"]
            }
        },
        {
            "input": "من زهرا احمدی هستم. سه سال تجربه، شهر اصفهان. یادگیری ماشین و اکسل بلدم. به داده‌کاوی علاقه دارم.",
            "output": {
                "first_name":"زهرا","last_name":"احمدی","age":"",
                "gender":"زن","experience_years":3,"city":"اصفهان","military_status":"",
                "skills":["یادگیری ماشین","Excel"],"interests":["داده‌کاوی"]
            }
        }
    ]
    return (
        "رونوشت گفتار کاربر:\n"
        + txt
        + "\n\nنمونه‌های قالب درست (برای راهنمایی):\n"
        + json.dumps(examples, ensure_ascii=False)
        + "\n\nاکنون فقط JSON نتیجه برای این ورودی را چاپ کن."
    )

def extract_json_block(text: str) -> dict:
    # tolerant to stray tokens—keep first {...} block
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON block found")
    return json.loads(m.group(0))

def llm_extract(transcript: str) -> dict:
    if not ollama:
        raise RuntimeError("Ollama module not available.")
    resp = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": LLM_SYSTEM.strip()},
            {"role": "user", "content": build_llm_user_prompt(transcript)}
        ],
        options={"temperature": 0.1}
    )
    raw = (resp["message"]["content"] or "").strip()
    return extract_json_block(raw)

def postprocess_llm_profile(obj: dict) -> dict:
    # shape defaults
    obj = obj or {}
    profile = {
        "first_name": norm(obj.get("first_name")),
        "last_name": norm(obj.get("last_name")),
        "age": to_int_or_empty(obj.get("age")),
        "gender": norm(obj.get("gender")),
        "experience_years": to_int_or_empty(obj.get("experience_years")),
        "city": norm(obj.get("city")),
        "military_status": norm(obj.get("military_status")),
        "skills": list(obj.get("skills") or []),
        "interests": list(obj.get("interests") or []),
    }

    # Pretty & dedup lists
    profile["skills"] = prettify_and_dedup_list(profile["skills"])
    profile["interests"] = prettify_and_dedup_list(profile["interests"])

    # Gender fallback via name lexicon (only if missing)
    if profile["gender"] == "":
        g = gender_from_first_name(profile["first_name"])
        if g:
            profile["gender"] = g

    # Convert lists to CSV for the form inputs in UI
    profile["skills"] = list_to_csv(profile["skills"])
    profile["interests"] = list_to_csv(profile["interests"])
    return profile

# -----------------------------------------------------------------------------
# Excel I/O
# -----------------------------------------------------------------------------
COLUMNS = [
    "نام", "نام خانوادگی", "سن", "جنسیت",
    "تعداد سال سابقه کار", "شهر محل سکونت", "وضعیت سربازی",
    "مهارت های کلیدی", "علایق", "ثبت در"
]

def append_record_to_excel(row: dict, xlsx_path: str):
    df_row = pd.DataFrame([{
        "نام": row.get("first_name", ""),
        "نام خانوادگی": row.get("last_name", ""),
        "سن": row.get("age", ""),
        "جنسیت": row.get("gender", ""),
        "تعداد سال سابقه کار": row.get("experience_years", ""),
        "شهر محل سکونت": row.get("city", ""),
        "وضعیت سربازی": row.get("military_status", ""),
        "مهارت های کلیدی": row.get("skills", ""),
        "علایق": row.get("interests", ""),
        "ثبت در": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }], columns=COLUMNS)

    if os.path.exists(xlsx_path):
        try:
            old = pd.read_excel(xlsx_path)
            merged = pd.concat([old, df_row], ignore_index=True)
        except Exception:
            merged = df_row  # if file is corrupted, overwrite
    else:
        merged = df_row

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        merged.to_excel(writer, index=False)

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    last_record = None
    success = False

    if request.method == "POST":
        payload = {
            "first_name": norm(request.form.get("first_name")),
            "last_name": norm(request.form.get("last_name")),
            "age": to_int_or_empty(request.form.get("age")),
            "gender": norm(request.form.get("gender")),
            "experience_years": to_int_or_empty(request.form.get("experience_years")),
            "city": norm(request.form.get("city")),
            "military_status": norm(request.form.get("military_status")),
            "skills": norm(request.form.get("skills")),
            "interests": norm(request.form.get("interests")),
        }
        append_record_to_excel(payload, app.config["EXCEL_PATH"])
        last_record = payload
        success = True

    return render_template(
        "index.html",
        success=success,
        last_record=last_record,
        excel_rel_path=os.path.relpath(app.config["EXCEL_PATH"]).replace("\\", "/"),
    )

@app.route("/nlp/parse", methods=["POST"])
def nlp_parse():
    """
    POST JSON: { "utterance": "<transcribed text>" }
    -> Uses Gemma (Ollama) ONLY to extract structured fields.
    -> Returns JSON for pre-filling the form.
    """
    if not ollama:
        return jsonify({"error": "ollama_not_available"}), 500

    data = request.get_json(silent=True) or {}
    utter = normalize_spaces(normalize_digits(norm(data.get("utterance"))))
    if not utter:
        return jsonify({"error": "empty utterance"}), 400

    try:
        raw_profile = llm_extract(utter)
        profile = postprocess_llm_profile(raw_profile)
        return jsonify(profile), 200
    except Exception as e:
        print("⚠️ LLM extraction error:", e)
        # Return safe empty profile so UI can still show the form
        empty = {
            "first_name":"", "last_name":"", "age":"", "gender":"", "experience_years":"",
            "city":"", "military_status":"", "skills":"", "interests":""
        }
        return jsonify(empty), 200

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Run on 5001 to avoid clashing with the other app
    app.run(debug=True, port=5001)
