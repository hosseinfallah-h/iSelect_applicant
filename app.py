# -*- coding: utf-8 -*-
import os
import re
import csv
import json
from datetime import datetime

import pandas as pd
from flask import Flask, render_template, request, jsonify

# =========================================
# App config
# =========================================
app = Flask(__name__)
app.config["DATA_FOLDER"] = "data"
app.config["EXCEL_PATH"] = os.path.join(app.config["DATA_FOLDER"], "people.xlsx")
app.config["NAME_LEXICON_PATH"] = os.path.join(app.config["DATA_FOLDER"], "names_fa.csv")  # optional CSV
os.makedirs(app.config["DATA_FOLDER"], exist_ok=True)

# =========================================
# Normalization utils
# =========================================
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS  = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def norm(s: str) -> str:
    if s is None:
        return ""
    return str(s).strip()

def normalize_digits(s: str) -> str:
    s = str(s or "")
    return s.translate(PERSIAN_DIGITS).translate(ARABIC_DIGITS)

def to_int_or_none(s):
    try:
        return int(float(str(s)))
    except Exception:
        return None

def normalize_spaces(s: str) -> str:
    # normalize weird spaces/half-spaces
    s = s.replace("\u200c", " ")  # ZWNJ -> space
    s = re.sub(r"\s+", " ", s)
    return s.strip()

# =========================================
# Small Persian name lexicon (built-in) + optional CSV
# CSV format (no header needed or use header): first_name,gender
# gender ∈ {"مرد","زن"}
# =========================================
BUILTIN_MALE = {
    "علی","حسین","محمد","رضا","مهدی","امیر","حمید","سعید","رضوان","هادی","حامد","وحید","مصطفی","حسن","مجتبی",
    "مجید","رضیان","میلاد","احمد","کاظم","بهزاد","روح‌الله","روح الله","یاسر","محسن","نیما","کیان","پارسا",
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
                    # support both with/without header; try to parse
                    first = row[0].strip() if len(row) > 0 else ""
                    g = (row[1].strip() if len(row) > 1 else "").replace("زن","زن").replace("مرد","مرد")
                    if not first:
                        continue
                    if g == "مرد":
                        male.add(first)
                    elif g == "زن":
                        female.add(first)
        except Exception as e:
            print("⚠️ name lexicon load error:", e)
    return male, female

MALE_NAMES, FEMALE_NAMES = load_name_lexicon()

def guess_gender_from_first_name(first_name: str) -> str:
    n = norm(first_name)
    if not n:
        return ""
    # exact match first
    if n in MALE_NAMES:
        return "مرد"
    if n in FEMALE_NAMES:
        return "زن"
    # case-insensitive/fuzzy (latin)
    n_l = n.lower()
    if n_l in {x.lower() for x in MALE_NAMES}:
        return "مرد"
    if n_l in {x.lower() for x in FEMALE_NAMES}:
        return "زن"
    return ""

# =========================================
# Domain heuristics
# =========================================
CITY_HINT_WORDS = r"(?:در|توی|ساکن\s*در|محل\s*سکونت\s*|از\s*شهر\s*)"
MIL_HAVE = r"(?:پایان\s*خدمت|کارت\s*پایان\s*خدمت|کارت|دار(?:د|م|ی)|انجام\s*داده|تموم\s*کرده)"
MIL_NOT  = r"(?:معاف|ندار(?:د|م|ی)|نخورده|نرفته|نرفته‌ام|معافیت)"

# Skills/Interests anchors and synonyms
SKILL_ANCHORS = [
    r"مهارت(?:‌|\s*)های?\s*کلیدی", r"مهارت(?:‌|\s*)ها", r"مهارت", r"skills?", r"key\s*skills?"
]
INTEREST_ANCHORS = [
    r"علاق(?:ه|ق)", r"علایق", r"علاقمند(?:ی|ی‌ها)?", r"interest(?:s)?"
]

# token splitters for comma-like lists
LIST_SPLIT = r"[,\u060C،;؛]| و "

def extract_name_tokens(s: str):
    """
    Heuristics for first/last name:
    - "من علی رضایی هستم"
    - "نام من علی رضایی است"
    - "من علی هستم" (first name only)
    - "نام خانوادگی من رضایی است"
    - Falls back: if we see two adjacent Persian tokens early, assume first + last
    """
    first = ""
    last = ""

    # explicit "نام خانوادگی ..."
    m = re.search(r"(?:نام\s*خانوادگی|فامیلی)\s+(?P<last>[آ-یA-Za-z]+)", s)
    if m:
        last = m.group("last")

    # "نام من X Y" or "من X Y هستم"
    m = re.search(r"(?:نام\s*من|من)\s+(?P<n1>[آ-یA-Za-z]+)(?:\s+(?P<n2>[آ-یA-Za-z]+))?", s)
    if m:
        n1 = m.group("n1")
        n2 = m.group("n2") or ""
        if n2 and not last:
            first, last = n1, n2
        elif n1 and not first:
            first = n1

    # If still missing last name: look for pattern "X Y هستم|هستم|هستم"
    if not last:
        m = re.search(r"\b([آ-یA-Za-z]+)\s+([آ-یA-Za-z]+)\s+(?:هستم|می\s*باشم|استم)\b", s)
        if m:
            first = first or m.group(1)
            last = m.group(2)

    # Fallback early-bigram: take first two Persian words at the beginning (avoid numbers/keywords)
    if not first:
        tokens = re.findall(r"[آ-یA-Za-z]+", s)
        # filter obvious non-name starters
        bad = {"من","نام","اسم","اینجانب","اینجا","این","هستم","هست"}
        tokens = [t for t in tokens if t not in bad]
        if tokens:
            first = tokens[0]
            if len(tokens) > 1 and not last:
                last = tokens[1]

    return first, last

def extract_age(s: str):
    """
    Finds a single age in years:
    - "۲۸ ساله" / "28 سال" / "سن 28"
    If there is a range, we pick the single number if context says "ساله".
    """
    # explicit "X ساله"
    m = re.search(r"(?:سن\s*)?(\d{1,3})\s*سال(?:ه)?", s)
    if m:
        return to_int_or_none(m.group(1))
    # "سن 28"
    m = re.search(r"سن\s*(\d{1,3})\b", s)
    if m:
        return to_int_or_none(m.group(1))
    return None

def extract_experience_years(s: str):
    """
    Extracts a single number of experience years:
    - "۴ سال سابقه / سابقه 4 سال / تجربه 3 سال"
    - also catches "حدود ۳ سال سابقه"
    """
    # "سابقه ... X سال"
    m = re.search(r"(?:سابقه(?:\s*کاری)?|تجربه)\s*(?:حدود|نزدیک|حداقل|حداکثر|بیش\s*از|کمتر\s*از)?\s*(\d{1,2})\s*سال", s)
    if not m:
        # "X سال سابقه"
        m = re.search(r"(\d{1,2})\s*سال(?:ه)?\s*(?:سابقه(?:\s*کاری)?|تجربه)", s)
    if m:
        return to_int_or_none(m.group(1))
    return None

def extract_city(s: str):
    m = re.search(rf"{CITY_HINT_WORDS}\s*([آ-یA-Za-z]+)", s)
    return m.group(1) if m else ""

def extract_military(s: str):
    if re.search(MIL_HAVE, s):
        return "دارد"
    if re.search(MIL_NOT, s):
        return "ندارد"
    return ""

def extract_list_after_anchors(s: str, anchors):
    """
    Extracts a comma/،/;/؛/ 'و' separated list after any of the anchor phrases.
    Returns a clean comma-separated string.
    """
    for a in anchors:
        m = re.search(rf"(?:{a})[:：]?\s*([^\n]+)", s, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            # cut at a sentence boundary if present
            raw = re.split(r"[.!؟\n]", raw)[0]
            parts = re.split(LIST_SPLIT, raw)
            parts = [normalize_spaces(p).strip() for p in parts if normalize_spaces(p).strip()]
            # de-dup while preserving order
            seen = set()
            out = []
            for p in parts:
                if p.lower() not in seen:
                    seen.add(p.lower())
                    out.append(p)
            return ", ".join(out)
    return ""

def post_infer_gender(first_name: str, current_gender: str) -> str:
    # explicit gender words beat lexicon
    if current_gender in {"مرد","زن"}:
        return current_gender
    # otherwise infer from first name
    g = guess_gender_from_first_name(first_name)
    return g or current_gender

# =========================================
# NLP: main voice parser (pure local, Persian-aware)
# =========================================
def parse_voice_utterance(utter: str) -> dict:
    s = normalize_spaces(normalize_digits(utter or ""))
    out = {
        "first_name": "",
        "last_name": "",
        "age": "",
        "gender": "",
        "experience_years": "",
        "city": "",
        "military_status": "",  # دارد | ندارد
        "skills": "",
        "interests": "",
    }

    # Names
    fn, ln = extract_name_tokens(s)
    out["first_name"] = fn
    out["last_name"] = ln

    # Age
    age = extract_age(s)
    if age is not None and 0 < age < 120:
        out["age"] = age

    # Experience
    exp = extract_experience_years(s)
    if exp is not None and 0 <= exp < 60:
        out["experience_years"] = exp

    # City
    out["city"] = extract_city(s)

    # Gender (explicit first)
    if re.search(r"(خانم|زن)", s):
        out["gender"] = "زن"
    if re.search(r"(آقا|مرد)", s):
        out["gender"] = "مرد"
    # Fallback infer
    out["gender"] = post_infer_gender(out["first_name"], out["gender"])

    # Military
    out["military_status"] = extract_military(s)

    # Skills & Interests (listy)
    out["skills"] = extract_list_after_anchors(s, SKILL_ANCHORS)
    out["interests"] = extract_list_after_anchors(s, INTEREST_ANCHORS)

    return out

# =========================================
# Excel I/O
# =========================================
COLUMNS = [
    "نام", "نام خانوادگی", "سن", "جنسیت",
    "تعداد سال سابقه کار", "شهر محل سکونت", "وضعیت سربازی",
    "مهارت های کلیدی", "علایق", "ثبت در"
]

def append_record_to_excel(row: dict, xlsx_path: str):
    """
    Appends the row (dict) to the Excel file, creating it with headers if it doesn't exist.
    """
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

# =========================================
# Routes
# =========================================
@app.route("/", methods=["GET", "POST"])
def index():
    """
    GET -> show form (empty)
    POST -> save record, show success panel and the last record
    """
    last_record = None
    success = False

    if request.method == "POST":
        payload = {
            "first_name": norm(request.form.get("first_name")),
            "last_name": norm(request.form.get("last_name")),
            "age": to_int_or_none(request.form.get("age")) or "",
            "gender": norm(request.form.get("gender")),
            "experience_years": to_int_or_none(request.form.get("experience_years")) or "",
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
    POST JSON: { utterance: "..." }
    -> returns parsed fields to fill the form (user can edit before submit)
    """
    data = request.get_json(silent=True) or {}
    utter = norm(data.get("utterance"))
    if not utter:
        return jsonify({"error": "empty utterance"}), 400

    parsed = parse_voice_utterance(utter)
    return jsonify(parsed), 200

# =========================================
# Entrypoint
# =========================================
if __name__ == "__main__":
    # Run on 5001 to avoid clashing with your other app
    app.run(debug=True, port=5001)
