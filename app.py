# -*- coding: utf-8 -*-
"""
I-SELECT (Applicant Intake) — Flask app
- Persian-aware voice parser (names, age, gender, experience, city, military, skills, interests)
- Excel append with headers (data/people.xlsx)
"""

import os
import re
import csv
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
# Name lexicon (built-in) + optional CSV
# CSV format (with or without header): first_name,gender   gender ∈ {"مرد","زن"}
# =========================================
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
                    g = "مرد" if "مرد" in g_raw else ("زن" if "زن" in g_raw else "")
                    if not first or not g:
                        continue
                    (male if g == "مرد" else female).add(first)
        except Exception as e:
            print("⚠️ name lexicon load error:", e)
    return male, female

MALE_NAMES, FEMALE_NAMES = load_name_lexicon()

def guess_gender_from_first_name(first_name: str) -> str:
    n = norm(first_name)
    if not n:
        return ""
    if n in MALE_NAMES: return "مرد"
    if n in FEMALE_NAMES: return "زن"
    n_l = n.lower()
    if n_l in {x.lower() for x in MALE_NAMES}: return "مرد"
    if n_l in {x.lower() for x in FEMALE_NAMES}: return "زن"
    return ""

# =========================================
# Domain heuristics (regex, anchors, lists)
# =========================================
CITY_HINT_WORDS = r"(?:در|توی|ساکن\s*در|محل\s*سکونت\s*|از\s*شهر\s*)"
MIL_HAVE = r"(?:پایان\s*خدمت|کارت\s*پایان\s*خدمت|کارت|دار(?:د|م|ی)|انجام\s*داده|تموم\s*کرد[ه|م|ی])"
MIL_NOT  = r"(?:معاف|ندار(?:د|م|ی)|نخورده|نرفته|معافیت)"

SKILL_ANCHORS = [
    r"مهارت(?:‌|\s*)های?\s*کلیدی", r"مهارت(?:‌|\s*)ها", r"مهارت", r"skills?", r"key\s*skills?"
]
INTEREST_ANCHORS = [
    r"علاق(?:ه|ق)", r"علایق", r"علاقمند(?:ی|ی‌ها)?", r"interest(?:s)?"
]

LIST_SPLIT = r"[,\u060C،;؛]| و "

# === Skill dictionary & scanner (extend as you wish) ===
BUILTIN_SKILLS = {
    "python": {"python","پایتون"},
    "sql": {"sql","اس‌کیوال","اس کیو ال"},
    "machine learning": {"machine learning","ml","یادگیری ماشین","ماشین لرنینگ"},
    "deep learning": {"deep learning","یادگیری عمیق","دیپ لرنینگ"},
    "ai": {"ai","هوش مصنوعی"},
    "excel": {"excel","اکسل"},
    "power bi": {"power bi","پاور بی‌آی","پاور بی ای","powerbi"},
    "plc": {"plc","پی ال سی"},
    "javascript": {"javascript","جاوااسکریپت","js"},
    "react": {"react","ری‌اکت","ری اکت"},
}

SKILL_PRETTY = {
    "python":"Python","sql":"SQL","machine learning":"یادگیری ماشین",
    "deep learning":"یادگیری عمیق","ai":"هوش مصنوعی","excel":"Excel",
    "power bi":"Power BI","plc":"PLC","javascript":"JavaScript","react":"React",
}

def normalize_token(t: str) -> str:
    t = normalize_spaces(normalize_digits(t)).lower()
    t = t.replace("‌", " ")
    return t

def scan_known_skills(full_text: str) -> list:
    t = normalize_token(full_text)
    hits = []
    for canon, synonyms in BUILTIN_SKILLS.items():
        for syn in synonyms:
            if re.search(rf"(?<![آ-یa-z0-9]){re.escape(syn)}(?![آ-یa-z0-9])", t):
                hits.append(canon)
                break
    # pretty print & de-dup
    seen = set()
    out = []
    for h in hits:
        p = SKILL_PRETTY.get(h, h)
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out

# =========================================
# Regex helpers
# =========================================
PERS_LET = r"آ-یA-Za-z"

def has_token(pattern: str, text: str) -> bool:
    """Match token with pseudo word-boundaries for Persian/Latin."""
    return re.search(rf"(?<![{PERS_LET}])(?:{pattern})(?![{PERS_LET}])", text) is not None

def extract_name_tokens(s: str):
    """
    Heuristics for first/last:
      - "من علی رضایی هستم" / "نام من علی رضایی است"
      - "نام خانوادگی من رضایی است" (last only)
      - Fallback: first two Persian/Latin words (ignoring obvious stop-words)
    """
    first, last = "", ""

    m = re.search(r"(?:نام\s*خانوادگی|فامیلی)\s+(?P<last>[آ-یA-Za-z]+)", s)
    if m:
        last = m.group("last")

    m = re.search(r"(?:نام\s*من|من)\s+(?P<n1>[آ-یA-Za-z]+)(?:\s+(?P<n2>[آ-یA-Za-z]+))?", s)
    if m:
        n1 = m.group("n1")
        n2 = m.group("n2") or ""
        if n2 and not last:
            first, last = n1, n2
        elif n1 and not first:
            first = n1

    if not last:
        m = re.search(r"\b([آ-یA-Za-z]+)\s+([آ-یA-Za-z]+)\s+(?:هستم|می\s*باشم|استم)\b", s)
        if m:
            first = first or m.group(1)
            last = m.group(2)

    if not first:
        tokens = re.findall(r"[آ-یA-Za-z]+", s)
        bad = {"من","نام","اسم","اینجانب","این","هستم","هست","میباشم","می‌باشم"}
        tokens = [t for t in tokens if t not in bad]
        if tokens:
            first = tokens[0]
            if len(tokens) > 1 and not last:
                last = tokens[1]
    return first, last

def extract_age(s: str):
    # "۲۸ ساله" / "28 سال" / "سن 28"
    m = re.search(r"(?:سن\s*)?(\d{1,3})\s*سال(?:ه)?", s)
    if m:
        return to_int_or_none(m.group(1))
    m = re.search(r"سن\s*(\d{1,3})\b", s)
    if m:
        return to_int_or_none(m.group(1))
    return None

def extract_experience_years(s: str):
    # "سابقه ... X سال" | "X سال سابقه" | "تجربه X سال"
    m = re.search(r"(?:سابقه(?:\s*کاری)?|تجربه)\s*(?:حدود|نزدیک|حداقل|حداکثر|بیش\s*از|کمتر\s*از)?\s*(\d{1,2})\s*سال", s)
    if not m:
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
    """
    for a in anchors:
        m = re.search(rf"(?:{a})[:：]?\s*([^\n]+)", s, flags=re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            raw = re.split(r"[.!؟\n]", raw)[0]  # stop at sentence end
            parts = re.split(LIST_SPLIT, raw)
            parts = [normalize_spaces(p).strip() for p in parts if normalize_spaces(p).strip()]
            # de-dup preserve order
            seen = set(); out = []
            for p in parts:
                key = p.lower()
                if key not in seen:
                    seen.add(key)
                    out.append(p)
            return ", ".join(out)
    return ""

def merge_csv_like(a: str, b_list: list) -> str:
    """Merge 'a' (CSV string) with items from 'b_list' (list of strings), de-dup."""
    a_parts = [x.strip() for x in (a.split(",") if a else []) if x.strip()]
    seen = {p.lower() for p in a_parts}
    for item in (b_list or []):
        if item and item.lower() not in seen:
            a_parts.append(item)
            seen.add(item.lower())
    return ", ".join(a_parts)

def post_infer_gender(first_name: str, current_gender: str) -> str:
    # explicit beats inference
    if current_gender in {"مرد","زن"}:
        return current_gender
    return guess_gender_from_first_name(first_name) or current_gender

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
    out["first_name"], out["last_name"] = fn, ln

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

    # Gender — use true token boundaries (no 'زن' inside 'زندگی')
    if has_token(r"(خانم|زن)", s):
        out["gender"] = "زن"
    elif has_token(r"(آقا|مرد)", s):
        out["gender"] = "مرد"

    # Fallback infer from first name
    out["gender"] = post_infer_gender(out["first_name"], out["gender"])

    # Military
    out["military_status"] = extract_military(s)

    # Skills & Interests
    anchored_skills = extract_list_after_anchors(s, SKILL_ANCHORS)
    scanned_skills = scan_known_skills(s)  # full-text dictionary scan
    out["skills"] = merge_csv_like(anchored_skills, scanned_skills)

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
    GET -> show form
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
