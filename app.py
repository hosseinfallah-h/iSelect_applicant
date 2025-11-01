import os
import re
import json
from datetime import datetime

import pandas as pd
from flask import Flask, render_template, request, jsonify

# -------------------------------
# App config
# -------------------------------
app = Flask(__name__)
app.config["DATA_FOLDER"] = "data"
app.config["EXCEL_PATH"] = os.path.join(app.config["DATA_FOLDER"], "people.xlsx")
os.makedirs(app.config["DATA_FOLDER"], exist_ok=True)

# -------------------------------
# Utils
# -------------------------------
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

# -------------------------------
# NLP (very lightweight, Persian-friendly)
# -------------------------------
def parse_voice_utterance(utter: str) -> dict:
    """
    Extracts: first_name, last_name, age, gender, experience_years, city, military_status, skills, interests
    - Very tolerant of Persian/Arabic numerals.
    - Uses heuristics; user can still edit before submit.
    """
    s = normalize_digits(utter or "")
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

    # Name (simple heuristics like: "نام من علی ...", "من علی ...", "نام خانوادگی ...")
    m = re.search(r"(?:نام\s*من|من)\s+([آ-یA-Za-z]+)", s)
    if m:
        out["first_name"] = m.group(1)

    m = re.search(r"(?:نام\s*خانوادگی|فامیلی)\s+([آ-یA-Za-z]+)", s)
    if m:
        out["last_name"] = m.group(1)

    # Age: "سن 28" / "28 ساله" / "سن 25 تا 32" (we store *single* exact age if provided;
    # if a range is spoken, keep empty and let user edit — this app wants a single age)
    # single age first:
    m = re.search(r"(?:سن\s*)?(\d{1,3})\s*(?:سال(?:ه)?)", s)
    if m:
        out["age"] = to_int_or_none(m.group(1)) or ""
    else:
        m = re.search(r"سن\s*(\d{1,3})\b", s)
        if m:
            out["age"] = to_int_or_none(m.group(1)) or ""

    # Experience: "سابقه 4 سال" / "۴ سال سابقه" / "تجربه 3 سال"
    m = re.search(r"(?:سابقه(?:\s*کاری)?|تجربه)\s*(\d{1,2})\s*سال", s)
    if not m:
        m = re.search(r"(\d{1,2})\s*سال(?:ه)?\s*(?:سابقه(?:\s*کاری)?|تجربه)", s)
    if m:
        out["experience_years"] = to_int_or_none(m.group(1)) or ""

    # City: "در تهران / توی شیراز"
    m = re.search(r"(?:در|توی)\s+([آ-یA-Za-z]+)", s)
    if m:
        out["city"] = m.group(1)

    # Gender
    if re.search(r"(خانم|زن)", s):
        out["gender"] = "زن"
    if re.search(r"(آقا|مرد)", s):
        out["gender"] = "مرد"

    # Military
    if re.search(r"(پایان خدمت|کارت|دار[هید])", s):
        out["military_status"] = "دارد"
    if re.search(r"(معاف|ندارد|نخورده|نرفته)", s):
        out["military_status"] = "ندارد"

    # Skills: after "مهارت" / "مهارت‌های کلیدی" followed by comma-separated list
    m = re.search(r"(?:مهارت(?:های)?(?:\s*کلیدی)?)[:：]?\s*([^\n،,]+(?:[،,]\s*[^\n،,]+)*)", s)
    if m:
        out["skills"] = m.group(1).strip()

    # Interests: after "علایق:" (or similar)
    m = re.search(r"(?:علاقه|علایق)[:：]?\s*([^\n،,]+(?:[،,]\s*[^\n،,]+)*)", s)
    if m:
        out["interests"] = m.group(1).strip()

    return out

# -------------------------------
# Excel I/O
# -------------------------------
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

# -------------------------------
# Routes
# -------------------------------
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

if __name__ == "__main__":
    # Run on 5001 to avoid clashing with your other app
    app.run(debug=True, port=5001)
