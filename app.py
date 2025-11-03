# -*- coding: utf-8 -*-
"""
I-SELECT (Applicant Intake) — Enhanced with improved capabilities extraction
"""

import os
import csv
import re
import json
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from flask import Flask, render_template, request, jsonify

# ---- Enhanced Dependencies ----
try:
    import ollama
except ImportError:
    ollama = None
    print("⚠️ Ollama not available. Install: pip install ollama")

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
except ImportError:
    detect = None
    print("⚠️ langdetect not available. Install: pip install langdetect")

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None
    print("⚠️ PyPDF2 not available. Install: pip install PyPDF2")

try:
    from docx import Document
except ImportError:
    Document = None
    print("⚠️ python-docx not available. Install: pip install python-docx")

# -----------------------------------------------------------------------------
# App config
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["DATA_FOLDER"] = "data"
app.config["EXCEL_PATH"] = os.path.join(app.config["DATA_FOLDER"], "people.xlsx")
app.config["UPLOAD_FOLDER"] = os.path.join(app.config["DATA_FOLDER"], "uploads")
app.config["NAME_LEXICON_PATH"] = os.path.join(app.config["DATA_FOLDER"], "names_fa.csv")
os.makedirs(app.config["DATA_FOLDER"], exist_ok=True)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")

# -----------------------------------------------------------------------------
# Enhanced Normalizers with Language Detection
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

def detect_and_translate(text: str) -> str:
    """Detect language and translate to Persian if needed"""
    if not text or not detect:
        return text
    
    try:
        lang = detect(text)
        if lang != 'fa':
            # Use Ollama for translation
            if ollama:
                response = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=[{
                        "role": "user", 
                        "content": f"Translate this to Persian: {text}"
                    }]
                )
                return response['message']['content']
    except Exception:
        pass
    
    return text

# -----------------------------------------------------------------------------
# Name Lexicon (Enhanced)
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
    n_l = n.lower()
    if n_l in {x.lower() for x in MALE_NAMES}: return "مرد"
    if n_l in {x.lower() for x in FEMALE_NAMES}: return "زن"
    return ""

# -----------------------------------------------------------------------------
# Enhanced Skill and Interest Mapping
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
    "Node.js": {"node","nodejs","node.js"},
    "Vue.js": {"vue","vuejs","vue.js"},
    "Angular": {"angular"},
    "Docker": {"docker","داکر"},
    "Kubernetes": {"kubernetes","k8s"},
    "AWS": {"aws","amazon web services"},
    "Azure": {"azure","مایکروسافت آزور"},
    "Git": {"git","گیت"},
    "Linux": {"linux","لینوکس"},
    "Java": {"java","جاوا"},
    "C++": {"c++","سی پلاس پلاس"},
    "C#": {"c#","سی شارپ"},
    "PHP": {"php","پی اچ پی"},
    "WordPress": {"wordpress","وردپرس"},
    "Photoshop": {"photoshop","فتوشاپ"},
    "UI/UX Design": {"ui","ux","design","طراحی"},
    "Project Management": {"project management","مدیریت پروژه"},
    "Data Analysis": {"data analysis","تحلیل داده"},
    "Business Intelligence": {"business intelligence","هوش تجاری"},
}

INTEREST_CATEGORIES = {
    "هوش مصنوعی و یادگیری ماشین": {"هوش مصنوعی", "یادگیری ماشین", "ai", "machine learning", "deep learning"},
    "برنامه نویسی و توسعه نرم افزار": {"برنامه نویسی", "توسعه نرم افزار", "programming", "software development", "coding"},
    "تحلیل داده و داده کاوی": {"تحلیل داده", "داده کاوی", "data analysis", "data mining", "big data"},
    "طراحی و توسعه وب": {"طراحی وب", "توسعه وب", "web design", "web development", "frontend", "backend"},
    "مدیریت پروژه و کسب و کار": {"مدیریت پروژه", "کسب و کار", "project management", "business", "استارتاپ"},
    "امنیت اطلاعات": {"امنیت", "امنیت اطلاعات", "cybersecurity", "security", "حریم خصوصی"},
    "اینترنت اشیا": {"اینترنت اشیا", "iot", "internet of things"},
    "رباتیک و اتوماسیون": {"رباتیک", "اتوماسیون", "robotics", "automation"},
    "بلاکچین و ارز دیجیتال": {"بلاکچین", "ارز دیجیتال", "blockchain", "cryptocurrency"},
    "رایانش ابری": {"رایانش ابری", "cloud computing", "cloud"},
    "توسعه موبایل": {"توسعه موبایل", "mobile development", "android", "ios"},
    "بازی سازی": {"بازی سازی", "game development", "gaming"},
}

def extract_detailed_skills_and_interests(text: str) -> Dict[str, List[str]]:
    """Use LLM to extract detailed skills and interests from text"""
    if not ollama:
        return {"skills": [], "interests": []}
    
    prompt = f"""
    از متن زیر، مهارت‌های فنی و علایق حرفه‌ای را استخراج کن:
    
    "{text}"
    
    مهارت‌ها باید شامل تکنولوژی‌ها، ابزارها، زبان‌های برنامه‌نویسی و توانایی‌های فنی باشد.
    علایق باید شامل زمینه‌های کاری، صنایع، موضوعات حرفه‌ای و حوزه‌های مورد علاقه باشد.
    
    پاسخ را به صورت JSON زیر برگردان:
    {{
        "skills": ["لیست مهارت‌های فنی"],
        "interests": ["لیست علایق حرفه‌ای"]
    }}
    
    فقط JSON برگردان.
    """
    
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1}
        )
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', response['message']['content'], re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "skills": data.get("skills", []),
                "interests": data.get("interests", [])
            }
    except Exception as e:
        print("Skills/Interests extraction error:", e)
    
    return {"skills": [], "interests": []}

def prettify_and_dedup_list(items):
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

def categorize_interests(interests: List[str]) -> List[str]:
    """Categorize interests into broader categories"""
    categorized = set()
    for interest in interests:
        interest_lower = interest.lower()
        for category, keywords in INTEREST_CATEGORIES.items():
            if any(keyword in interest_lower for keyword in keywords):
                categorized.add(category)
    
    return list(categorized)

def list_to_csv(items):
    return ", ".join([x for x in (items or []) if str(x).strip()])

# -----------------------------------------------------------------------------
# Multi-turn Conversation System
# -----------------------------------------------------------------------------
class ConversationManager:
    def __init__(self):
        self.sessions = {}
        self.required_fields = [
            "first_name", "last_name", "age", "gender", 
            "experience_years", "city", "skills", "military_status", "interests"
        ]
        self.field_questions = {
            "first_name": "لطفاً نام خود را بگویید:",
            "last_name": "لطفاً نام خانوادگی خود را بگویید:",
            "age": "سن شما چند سال است؟",
            "gender": "جنسیت شما چیست؟ (مرد/زن)",
            "experience_years": "چند سال سابقه کار دارید؟",
            "city": "در کدام شهر ساکن هستید؟",
            "skills": "مهارت‌های اصلی و فنی شما چیست؟ (مثلاً: Python، SQL، طراحی وب)",
            "military_status": "وضعیت سربازی شما چگونه است؟ (دارد/ندارد/معاف/در حال خدمت)",
            "interests": "به چه زمینه‌ها و موضوعاتی علاقه دارید؟ (مثلاً: هوش مصنوعی، توسعه نرم‌افزار، تحلیل داده)"
        }
    
    def start_session(self, session_id: str):
        self.sessions[session_id] = {
            'collected_data': {},
            'current_field_index': 0,
            'completed': False
        }
        return self.get_next_question(session_id)
    
    def get_next_question(self, session_id: str) -> str:
        session = self.sessions.get(session_id)
        if not session or session['completed']:
            return "ممنون! اطلاعات شما کامل شد."
        
        for i, field in enumerate(self.required_fields):
            if field not in session['collected_data']:
                session['current_field_index'] = i
                return self.field_questions[field]
        
        session['completed'] = True
        return "ممنون! اطلاعات شما کامل شد."
    
    def process_response(self, session_id: str, user_message: str) -> Dict:
        session = self.sessions.get(session_id)
        if not session or session['completed']:
            return {"question": "ممنون! اطلاعات شما کامل شد.", "completed": True}
        
        current_field = self.required_fields[session['current_field_index']]
        
        # Extract field value using LLM
        extracted_data = self.extract_field_value(current_field, user_message)
        if extracted_data:
            session['collected_data'].update(extracted_data)
        
        next_question = self.get_next_question(session_id)
        
        return {
            "question": next_question,
            "update_fields": extracted_data,
            "completed": session['completed']
        }
    
    def extract_field_value(self, field: str, text: str) -> Dict:
        """Use LLM to extract specific field value from text"""
        if not ollama:
            return {}
        
        prompt = f"""
        از متن زیر فقط مقدار مربوط به "{self.field_questions[field]}" را استخراج کن:
        متن: {text}
        
        فقط مقدار استخراج شده را برگردان بدون توضیح اضافی.
        """
        
        try:
            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            value = response['message']['content'].strip()
            
            # Post-process based on field type
            if field in ['age', 'experience_years']:
                value = to_int_or_empty(value)
            elif field == 'gender':
                value = 'مرد' if 'مرد' in value else 'زن' if 'زن' in value else ''
            elif field == 'military_status':
                if 'دارد' in value:
                    value = 'دارد'
                elif 'ندارد' in value:
                    value = 'ندارد'
                elif 'معاف' in value:
                    value = 'معاف'
                elif 'خدمت' in value:
                    value = 'در حال خدمت'
                else:
                    value = ''
            
            return {field: value}
        except Exception as e:
            print(f"Field extraction error for {field}:", e)
            return {}

conversation_manager = ConversationManager()

# -----------------------------------------------------------------------------
# Document Parser
# -----------------------------------------------------------------------------
def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file"""
    if not PyPDF2:
        return ""
    
    try:
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
    except Exception as e:
        print("PDF extraction error:", e)
        return ""

def extract_text_from_docx(file_path: str) -> str:
    """Extract text from DOCX file"""
    if not Document:
        return ""
    
    try:
        doc = Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text
    except Exception as e:
        print("DOCX extraction error:", e)
        return ""

def parse_resume_content(text: str) -> Dict:
    """Use LLM to extract structured data from resume text"""
    if not ollama:
        return {}
    
    prompt = f"""
    متن رزومه زیر را تحلیل کن و اطلاعات زیر را استخراج کن:
    
    {text}
    
    اطلاعات زیر را به صورت JSON برگردان:
    - first_name (نام)
    - last_name (نام خانوادگی) 
    - age (سن)
    - gender (جنسیت)
    - experience_years (سال سابقه کار)
    - city (شهر)
    - military_status (وضعیت سربازی)
    - skills (مهارت‌ها)
    - interests (علایق)
    
    فقط JSON خالص برگردان.
    """
    
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', response['message']['content'], re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return postprocess_llm_profile(data)
    except Exception as e:
        print("Resume parsing error:", e)
    
    return {}

# -----------------------------------------------------------------------------
# Enhanced LLM Extraction with Better Capabilities Detection
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
  "military_status": "دارد" | "ندارد" | "معاف" | "در حال خدمت" | "",
  "skills": string[],        // فهرست دقیق مهارت‌های فنی، ابزارها، تکنولوژی‌ها
  "interests": string[]      // فهرست دقیق علایق حرفه‌ای و زمینه‌های کاری
}
قواعد:
- برای skills: تمام مهارت‌های فنی، زبان‌های برنامه‌نویسی، ابزارها و تکنولوژی‌ها را استخراج کن
- برای interests: علایق حرفه‌ای، زمینه‌های کاری مورد علاقه، صنایع و حوزه‌های تخصصی را استخراج کن
- اگر جنسیت صراحتا ذکر نشده بود ولی از نام کوچک بتوان حدس زد، مقدار مناسب قرار بده.
- اگر چیزی معلوم نبود، مقدار خالی "" یا آرایه خالی [] بده.
- فقط JSON نتیجه را چاپ کن.
"""

def build_llm_user_prompt(transcript: str) -> str:
    txt = normalize_spaces(normalize_digits(transcript or ""))
    
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
            "input": "I am Sara Mohammadi, 25 years old with 3 years experience in web development. I know JavaScript, React, and Node.js. Interested in AI and data science.",
            "output": {
                "first_name":"سارا","last_name":"محمدی","age":25,"gender":"زن",
                "experience_years":3,"city":"","military_status":"",
                "skills":["JavaScript","React","Node.js"],"interests":["هوش مصنوعی","علم داده"]
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
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("No JSON block found")
    return json.loads(m.group(0))

def llm_extract(transcript: str) -> dict:
    if not ollama:
        raise RuntimeError("Ollama module not available.")
    
    # Language detection and translation
    translated_text = detect_and_translate(transcript)
    
    resp = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": LLM_SYSTEM.strip()},
            {"role": "user", "content": build_llm_user_prompt(translated_text)}
        ],
        options={"temperature": 0.1}
    )
    raw = (resp["message"]["content"] or "").strip()
    return extract_json_block(raw)

def postprocess_llm_profile(obj: dict) -> dict:
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

    # Smart error correction for gender
    if profile["gender"] == "":
        g = gender_from_first_name(profile["first_name"])
        if g:
            profile["gender"] = g

    # Enhanced skills and interests extraction
    if not profile["skills"] or not profile["interests"]:
        # Combine all text for better extraction
        combined_text = f"{profile['first_name']} {profile['last_name']} {profile['experience_years']} سال سابقه"
        detailed_extraction = extract_detailed_skills_and_interests(combined_text)
        
        if not profile["skills"] and detailed_extraction["skills"]:
            profile["skills"] = detailed_extraction["skills"]
        
        if not profile["interests"] and detailed_extraction["interests"]:
            profile["interests"] = detailed_extraction["interests"]

    # Pretty & dedup lists
    profile["skills"] = prettify_and_dedup_list(profile["skills"])
    profile["interests"] = prettify_and_dedup_list(profile["interests"])
    
    # Categorize interests for better recommendations
    if profile["interests"]:
        categorized = categorize_interests(profile["interests"])
        if categorized:
            profile["interests"] = categorized

    # Convert lists to CSV for the form inputs in UI
    profile["skills"] = list_to_csv(profile["skills"])
    profile["interests"] = list_to_csv(profile["interests"])
    return profile

# -----------------------------------------------------------------------------
# Enhanced AI Job Recommendations and Summary Generation
# -----------------------------------------------------------------------------
def generate_job_recommendations(profile: Dict) -> str:
    """Generate detailed job recommendations based on skills and experience"""
    if not ollama:
        return "سرویس پیشنهاد شغلی در دسترس نیست."
    
    skills = profile.get('skills', '')
    experience = profile.get('experience_years', 0)
    interests = profile.get('interests', '')
    
    prompt = f"""
    بر اساس مشخصات زیر، ۳-۴ پیشنهاد شغلی دقیق و مناسب ارائه کن:
    
    مهارت‌ها: {skills}
    سابقه کار: {experience} سال
    علایق: {interests}
    
    برای هر پیشنهاد:
    - عنوان شغلی دقیق
    - صنعت مربوطه
    - مهارت‌های کلیدی مورد نیاز
    - مسیر رشد شغلی
    
    پیشنهادها را به صورت فهرست نقطه‌ای و به فارسی ارائه کن.
    """
    
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.7}
        )
        return response['message']['content']
    except Exception as e:
        print("Job recommendations error:", e)
        return "پیشنهاد شغلی در دسترس نیست."

def generate_applicant_summary(profile: Dict) -> str:
    """Generate a professional summary of the applicant"""
    if not ollama:
        return "سرویس تولید خلاصه در دسترس نیست."
    
    prompt = f"""
    یک خلاصه حرفه‌ای یک پاراگرافی به فارسی برای این فرد بنویس که شامل:
    - معرفی کلی
    - تخصص‌های اصلی
    - زمینه‌های علاقه‌مندی
    - پتانسیل‌های رشد
    
    مشخصات:
    نام: {profile.get('first_name', '')} {profile.get('last_name', '')}
    سن: {profile.get('age', '')}
    سابقه کار: {profile.get('experience_years', '')} سال
    مهارت‌ها: {profile.get('skills', '')}
    علایق: {profile.get('interests', '')}
    
    خلاصه باید حرفه‌ای، جذاب و مختصر باشد.
    """
    
    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3}
        )
        return response['message']['content']
    except Exception as e:
        print("Summary generation error:", e)
        return "خلاصه در دسترس نیست."

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
            merged = df_row
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
    """Enhanced NLP parsing with better capabilities extraction"""
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
        empty = {
            "first_name":"", "last_name":"", "age":"", "gender":"", "experience_years":"",
            "city":"", "military_status":"", "skills":"", "interests":""
        }
        return jsonify(empty), 200

@app.route("/conversation/start", methods=["POST"])
def start_conversation():
    """Start a new conversation session"""
    session_id = request.remote_addr  # Simple session ID
    question = conversation_manager.start_session(session_id)
    return jsonify({"question": question})

@app.route("/conversation/respond", methods=["POST"])
def conversation_respond():
    """Process user response in conversation"""
    session_id = request.remote_addr
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "")
    
    result = conversation_manager.process_response(session_id, user_message)
    return jsonify(result)

@app.route("/parse/resume", methods=["POST"])
def parse_resume():
    """Parse uploaded resume file"""
    if 'resume' not in request.files:
        return jsonify({"success": False, "error": "No file uploaded"}), 400
    
    file = request.files['resume']
    if file.filename == '':
        return jsonify({"success": False, "error": "No file selected"}), 400
    
    # Save uploaded file
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    
    try:
        # Extract text based on file type
        if file.filename.lower().endswith('.pdf'):
            text = extract_text_from_pdf(file_path)
        elif file.filename.lower().endswith(('.doc', '.docx')):
            text = extract_text_from_docx(file_path)
        else:
            return jsonify({"success": False, "error": "Unsupported file format"}), 400
        
        if not text.strip():
            return jsonify({"success": False, "error": "Could not extract text from file"}), 400
        
        # Parse resume content
        fields = parse_resume_content(text)
        
        # Clean up uploaded file
        os.remove(file_path)
        
        return jsonify({"success": True, "fields": fields})
        
    except Exception as e:
        print("Resume parsing error:", e)
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/ai/recommend-jobs", methods=["POST"])
def recommend_jobs():
    """Generate job recommendations based on profile"""
    data = request.get_json(silent=True) or {}
    recommendations = generate_job_recommendations(data)
    return jsonify({"recommendations": recommendations})

@app.route("/ai/generate-summary", methods=["POST"])
def generate_summary():
    """Generate applicant summary"""
    data = request.get_json(silent=True) or {}
    summary = generate_applicant_summary(data)
    return jsonify({"summary": summary})

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("🚀 I-SELECT Enhanced Server Starting...")
    print("📝 Features: Multi-turn Conversation, Real-time STT, Document Parsing, AI Recommendations")
    print("🔊 Make sure Ollama is running with Gemma model")
    app.run(debug=True, port=5001)