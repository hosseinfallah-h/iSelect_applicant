# I-SELECT – People Intake (Voice/Form → Excel)

A tiny Flask app that lets users enter **personal info via voice or manual form**, shows it for confirmation, and **appends each submission to an Excel file** (`data/people.xlsx`). Every restart keeps prior rows — new rows go **after** existing ones.

## Fields
- نام
- نام خانوادگی
- سن
- جنسیت
- تعداد سال سابقه کار
- شهر محل سکونت
- وضعیت سربازی (دارد / ندارد)
- مهارت های کلیدی
- علایق

## Voice Flow
1. User clicks 🎤, speaks in Persian (fa-IR).
2. Browser transcribes (Web Speech API).
3. App sends the transcript to `/nlp/parse`.
4. Basic NLP extracts the fields (age, city, gender, etc.).
5. Form is filled automatically — user can edit.
6. On submit, row is appended to `data/people.xlsx`.

> Works without voice too: type into the voice box, then “پردازش و پرکردن فرم”.

---

## Run locally (Windows / PowerShell)

```powershell
# 1) Get the code
cd D:\projects
git clone https://github.com/<YOUR-USERNAME>/iSelectPeopleIntake.git
cd iSelectPeopleIntake

# 2) Python env + deps
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3) Start
python app.py
# Open http://127.0.0.1:5001
