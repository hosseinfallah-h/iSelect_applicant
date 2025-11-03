```markdown
# 🧠 I-SELECT — Intelligent Applicant Intake System

> **AI-powered resume intake, structured form filling, and job recommendation system**  
> Built with **Flask**, **Ollama (Gemma3 local models)**, and **LangDetect**, designed for **Persian + English** multi-lingual applicants.

---

## 🚀 Overview

**I-SELECT** automates the process of collecting and analyzing applicant information — from **voice or resume** — into a **structured dataset** ready for export to Excel.

It uses **local AI (Gemma3 via Ollama)** for:
- Automatic **data extraction** from voice, text, and resumes (PDF/DOCX)
- **Smart conversation flow** for multi-turn applicant interviews
- **Skill and interest mapping** using a hybrid rule-based + LLM extraction system
- **Job recommendation** and **summary generation** based on applicant profile

---

## 🧩 Key Features

### 🔹 Applicant Interaction
- **Form-based** and **voice-based** data entry  
- **Conversational intake** (multi-turn, LLM-assisted Persian dialogue)
- Auto-detects and translates English → Persian using `langdetect` + Ollama

### 🔹 Resume Parsing
- Supports `.pdf` and `.docx`
- Extracts key fields (name, gender, skills, interests, etc.)
- Auto-detects gender from name using a Persian name lexicon

### 🔹 AI Integration
- Local LLM via **Ollama + Gemma3**
- JSON-structured field extraction
- Skill deduplication and semantic matching
- AI-generated:
  - 🧭 Job recommendations  
  - 🧾 Applicant summaries

### 🔹 Data Management
- Auto-saves applicant info to `data/people.xlsx`
- Built-in CSV/Excel output compatible with HR workflows
- Persistent resume uploads in `data/uploads/`

---

## 🏗️ Project Structure

```

I-SELECT/
│
├── app.py                  # Main Flask app with AI integration
├── templates/
│   └── index.html          # Web interface for applicant data entry
├── data/
│   ├── people.xlsx         # Stored applicant records
│   ├── uploads/            # Temporary uploaded resumes
│   └── names_fa.csv        # Optional Persian name lexicon
│
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation

````

---

## ⚙️ Installation

### 1️⃣ Prerequisites
Ensure you have:
- **Python 3.9+**
- **Ollama** (with **Gemma3:1b** or **Gemma3:4b** pulled locally)
- Optionally:
  - `langdetect`
  - `python-docx`
  - `PyPDF2`

---

### 2️⃣ Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/I-SELECT.git
cd I-SELECT
````

### 3️⃣ Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate     # (Linux/macOS)
.venv\Scripts\activate        # (Windows)
```

### 4️⃣ Install dependencies

```bash
pip install -r requirements.txt
```

If you don’t have `requirements.txt`, you can install manually:

```bash
pip install flask pandas openpyxl ollama langdetect python-docx PyPDF2
```

---

## ⚡ Run Locally

1. **Start Ollama** (make sure Gemma3 is available)

   ```bash
   ollama run gemma3:1b
   ```

   or just have the Ollama service running in the background.

2. **Run the Flask server**

   ```bash
   python app.py
   ```

3. Open your browser at:
   👉 [http://localhost:5001](http://localhost:5001)

---

## 🗣️ Voice & Conversation Features

* The web interface includes a **live conversational mode**:

  * AI asks structured questions (name, age, city, skills, etc.)
  * Voice input → Speech-to-Text → LLM extraction → auto-fills form fields
  * Session auto-terminates if no response for 8 seconds

---

## 🧠 AI & NLP Pipeline

| Stage                  | Module              | Description                                  |
| ---------------------- | ------------------- | -------------------------------------------- |
| **Speech Input**       | Whisper / STT       | Converts applicant speech to text            |
| **Language Detection** | `langdetect`        | Detects and translates to Persian if English |
| **Extraction**         | Gemma3 (via Ollama) | Parses text into structured JSON             |
| **Post-Processing**    | Custom rules        | Normalizes digits, deduplicates skills       |
| **Recommendations**    | LLM prompt          | Generates job titles and summaries           |
| **Storage**            | Pandas + Excel      | Appends data to `people.xlsx`                |

---

## 📊 Saved Data Fields

| Field               | Description             |
| ------------------- | ----------------------- |
| نام                 | First Name              |
| نام خانوادگی        | Last Name               |
| سن                  | Age                     |
| جنسیت               | Gender                  |
| تعداد سال سابقه کار | Work Experience (Years) |
| شهر محل سکونت       | City                    |
| وضعیت سربازی        | Military Service        |
| مهارت های کلیدی     | Key Skills              |
| علایق               | Interests / Domains     |
| ثبت در              | Timestamp               |

---

## 📡 API Endpoints

| Endpoint                | Method   | Description                          |
| ----------------------- | -------- | ------------------------------------ |
| `/`                     | GET/POST | Form interface                       |
| `/nlp/parse`            | POST     | Parse free-text into structured JSON |
| `/conversation/start`   | POST     | Start new applicant conversation     |
| `/conversation/respond` | POST     | Respond to AI question               |
| `/parse/resume`         | POST     | Upload and parse resume (PDF/DOCX)   |
| `/ai/recommend-jobs`    | POST     | Generate job recommendations         |
| `/ai/generate-summary`  | POST     | Generate applicant summary           |

---

## 🧱 Environment Variables

| Variable        | Default            | Description                          |
| --------------- | ------------------ | ------------------------------------ |
| `OLLAMA_MODEL`  | `gemma3:1b`        | Ollama model for extraction and chat |
| `DATA_FOLDER`   | `data`             | Folder for Excel and uploads         |
| `UPLOAD_FOLDER` | `data/uploads`     | Resume upload path                   |
| `EXCEL_PATH`    | `data/people.xlsx` | Excel output file                    |

---

## 🛠️ Error Handling & Recovery

* All AI calls wrapped in `try/except` to avoid crashes
* Automatic fallback if `ollama` or `langdetect` is not available
* Empty structured outputs returned for failed extractions

---

## 💡 Example Output

**JSON Extraction Example:**

```json
{
  "first_name": "علی",
  "last_name": "رضایی",
  "age": 28,
  "gender": "مرد",
  "experience_years": 4,
  "city": "تهران",
  "military_status": "دارد",
  "skills": "Python, SQL, Excel",
  "interests": "هوش مصنوعی و یادگیری ماشین"
}
```

---

## 🧩 Future Improvements

* [ ] Integrate **Whisper.cpp** for offline speech-to-text
* [ ] Add **admin dashboard** for viewing and filtering applicants
* [ ] Add **tagging and rating system** per applicant
* [ ] Add **Excel export with labels and filters**
* [ ] Build RESTful backend for multi-tenant RMS version

---

## 🧑‍💻 Author

**Hossein Fallah**
AI Engineer & Full-Stack Developer
💼 Projects: [AI_RMS](https://github.com/hosseinfallah-h/AI_RMS), [iPo Support], [SmartDriver]
📧 Contact: `hosseinfallah.h@gmail.com`

---

## 📜 License

This project is licensed under the **MIT License** — feel free to use and modify it for your own local AI applicant management systems.

---

## 🧠 Credits

* [Ollama](https://ollama.ai) — Local LLM runtime
* [Gemma3](https://ai.google.dev/gemma) — Lightweight multilingual model
* [Flask](https://flask.palletsprojects.com/) — Web framework
* [Pandas + OpenPyXL](https://pandas.pydata.org/) — Excel I/O
* [LangDetect](https://pypi.org/project/langdetect/) — Language detection

---

> ⚙️ *"Built to make resume intake smarter, faster, and fully local."*

```
```
