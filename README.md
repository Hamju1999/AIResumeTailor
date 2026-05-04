# ResTail — Agentic Job Application Pipeline

ResTail automatically scrapes job listings and tailors your resume to each job using AI. It runs entirely on your computer — nothing is sent to any server except the Anthropic API for AI processing.

---

## What it does

1. Scrapes LinkedIn, Indeed, Dice, and Glassdoor for entry-level jobs matching your titles
2. Filters by location priority, date (last 7 days), seniority (entry-level only)
3. For each job: tailors your resume using 5 AI passes (tailor → grammar → verify → calibrate → validate)
4. Produces a formatted `.docx` resume for every passing job
5. Lets you paste job URLs you found yourself to bypass scraping

---

## Requirements

- Python 3.10 or higher
- Git
- An Anthropic API key (get one free at [console.anthropic.com](https://console.anthropic.com))

---

## Setup — Step by Step

### Step 1 — Install Git

**Windows:** Download from [git-scm.com](https://git-scm.com/download/win) and install with all defaults.

**Mac:** Open Terminal and run:
```bash
xcode-select --install
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install git -y
```

Verify:
```bash
git --version
```

---

### Step 2 — Install Python

**Windows:** Download Python 3.11 from [python.org/downloads](https://www.python.org/downloads). During install, **tick "Add Python to PATH"**.

**Mac:** 
```bash
brew install python
```
If you don't have Homebrew: [brew.sh](https://brew.sh)

**Linux:**
```bash
sudo apt install python3 python3-pip -y
```

Verify:
```bash
python --version        # Windows
python3 --version       # Mac/Linux
```

---

### Step 3 — Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/ResTail.git
cd ResTail
```

Replace `YOUR_USERNAME` with the GitHub username who shared this with you.

---

### Step 4 — Install dependencies

**Windows:**
```cmd
pip install -r requirements.txt
```

**Mac/Linux:**
```bash
pip3 install -r requirements.txt
```

If you see a permissions error on Mac/Linux:
```bash
pip3 install --user -r requirements.txt
```

---

### Step 5 — Get an Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Click **API Keys** in the left sidebar
4. Click **Create Key**
5. Copy the key (starts with `sk-ant-...`) — you will only see it once, save it somewhere safe

The API key is charged per use. A typical run of 10 jobs costs approximately $0.30–$0.60.

---

### Step 6 — Run the app

**Windows:**
```cmd
cd ResTail
python app.py
```

**Mac/Linux:**
```bash
cd ResTail
python3 app.py
```

Open your browser and go to: **http://localhost:5000**

On first run, the setup wizard opens automatically.

---

### Step 7 — Complete the setup wizard

The wizard asks for:

| Field | What to enter |
|-------|---------------|
| Full Name | Your full legal name as it should appear on the resume |
| City & State | e.g. `Chicago, IL` or `London, UK` |
| Phone | Your phone number |
| Email | Your email address |
| LinkedIn URL | Your full LinkedIn profile URL |
| GitHub URL | Your GitHub profile URL (or leave blank) |
| Portfolio URL | Your portfolio website (or leave blank) |
| Master Resume | Your complete professional record file (see below) |
| Format Template | The resume format description file (see below) |
| Locations | Cities to search, in priority order |
| Job Titles | Job titles to search for |
| API Key | Your Anthropic API key |

After saving, your config is stored in `user_config.json` locally. You never need to fill this in again unless you want to change something.

---

## Preparing your files

### Master Resume file

**What it is:** Your complete professional record — every job, every project, every skill, every certification you have ever had. The AI uses this as the only source of truth. Nothing is invented — everything in the output must trace back to this file.

**Format:** Plain text file (`.txt`) is recommended. PDF works only if it has a text layer (not a scanned image).

**What to include:**

```
PERSONAL INFORMATION
Full name, city, phone, email, LinkedIn, GitHub, Portfolio

EDUCATION
For each institution:
  Institution name, city, country
  Degree name - Graduation date
  GPA (if above 3.5), honors, awards (Dean's List, Silver Medalist, etc.)

PROFESSIONAL EXPERIENCE
For each role:
  Job title - Company name, City, State | Start date - End date
  
  What you did:
  - Describe every significant task, tool used, and outcome
  - Include specific technologies, frameworks, libraries, APIs
  - Include numbers where you have them (records processed, files handled, % improvement)
  - Include the scope (team size, dataset size, time frame)
  
  Write freely and in detail — the AI will select and condense.
  More detail is better than less.

ACADEMIC PROJECTS
For each project:
  Project name
  
  What it was:
  - What problem it solved
  - What you personally built or contributed
  - What technologies, tools, libraries you used
  - What the outcome or result was
  - Dataset sizes, record counts, performance metrics if applicable

TECHNICAL SKILLS
List every tool, language, framework, library, and method you have used.
Group them however you like — the AI will regroup them by relevance.
Be exhaustive — do not leave skills out.

CERTIFICATIONS
For each certification:
  Certification name - Issuing organisation - Year completed

AWARDS AND RECOGNITION (if any)
  Award name - Issuing body - Year
```

**Important:** Write naturally and in detail. The AI reads this file to understand what you have actually done. Vague entries like "used Python" produce vague resumes. Specific entries like "built a Python ETL pipeline to process 5.7 million CSV records across 12 monthly files" produce specific, credible resumes.

---

### Format Template file

**What it is:** A description of the 1-page resume format you want. The AI follows this when structuring the output.

**Format:** Plain text file (`.txt`).

**What to include:**

```
RESUME FORMAT SPECIFICATION

Page: US Letter (8.5 x 11 inches), 1 page maximum
Margins: 0.55 inches all sides
Font: Calibri

SECTIONS AND ORDER:
1. Name — bold, 16pt, centered, ALL CAPS
2. Contact line — 10pt, centered (City | Phone | Email | LinkedIn | GitHub | Portfolio)
3. Summary — 2 sentences, first-person
4. Technical Skills — 3 lines grouped as:
   Programming & Engineering: [tools]
   Applied AI & NLP: [tools]
   Analytics & Visualization: [tools]
5. Professional Experience — role header bold 12pt, then 4-5 bullet points
6. Academic Projects — project title bold 12pt with colon, then 3 bullet points each
7. Education — institution bold 12pt, degree 11pt
8. Certifications — bulleted list, top 3 most relevant only (if applicable)

BULLET FORMAT:
- Each bullet starts with an action verb
- No first-person "I"
- 15 words maximum per bullet
- One idea per bullet

TONE:
Clear, specific, and readable. Avoid buzzwords and abstraction.
Describe what was built and how it works.
```

You can customise this to match your preferred format. The AI will follow whatever structure you describe.

---

## Using the app

### Full scrape mode

1. Open **http://localhost:5000**
2. Click **Full scrape**
3. Set a limit (e.g. 5 for a test run, 0 for all jobs)
4. Click **Start**
5. Watch the live log stream while it runs
6. Download resumes from the **Results** panel when done

### My job links mode (recommended for fresh jobs)

1. Find a job on LinkedIn, Indeed, or any job board
2. Copy the URL
3. Go to the **My job links** tab
4. Paste the URL and click **Add**
5. Add more URLs if needed
6. Click **Start**

This skips scraping entirely and goes straight to AI tailoring. Useful for jobs posted hours ago.

### History

Every run is saved. Click **History** to download resumes from previous runs.

---

## Changing your config

To update your name, files, locations, job titles, or API key:

1. Go to **http://localhost:5000**
2. Visit **http://localhost:5000/setup**
3. Edit whatever you want to change
4. Click **Save Configuration**

Files you don't re-upload are kept as-is.

---

## Keeping the code up to date

When the repo owner pushes updates:

```bash
cd ResTail
git pull
```

Then restart:
```bash
python app.py        # Windows
python3 app.py       # Mac/Linux
```

Your `user_config.json` and uploaded files are preserved across updates.

---

## Troubleshooting

**"No module named X" error:**
```bash
pip install -r requirements.txt          # Windows
pip3 install -r requirements.txt         # Mac/Linux
```

**"401 Invalid authentication credentials":**
Your API key is wrong or missing. Go to `/setup` and re-enter it.

**"No .docx files — nothing to zip" (all jobs failed):**
Open the manifest JSON in `output/manifest_*.json` and check the `failures` array for the specific reason.

**App won't start — port already in use:**
Something else is running on port 5000. Either stop it, or change the port in `app.py` (last line: `port=5000`).

**Jobs scrape but no resumes produced:**
Check the live log for "Verification FAILED" or "Validation FAILED" messages with the specific reason.

---

## File structure

```
ResTail/
├── app.py                  ← Start here: python app.py
├── config.py               ← Reads from user_config.json
├── user_config.json        ← Your personal settings (created by setup wizard)
├── master_resume.txt       ← Your resume source file (uploaded in setup)
├── format_template.txt     ← Format spec (uploaded in setup)
├── output/                 ← All generated resumes and run data
│   └── resumes/<run_id>/   ← .docx files per run
├── templates/
│   ├── index.html          ← Main UI
│   └── setup.html          ← Setup wizard
└── requirements.txt        ← Python dependencies
```

---

## Privacy

- Everything runs on your computer
- Your master resume never leaves your machine except in API calls to Anthropic
- `user_config.json` is gitignored — it is never pushed to GitHub
- The app is only accessible at `localhost:5000` — not visible to anyone else on the internet

---

## Cost estimate

Each job processed uses approximately 33,000 input tokens across 5 AI passes.
At Anthropic's current pricing for claude-sonnet-4-6:

| Jobs | Estimated cost |
|------|---------------|
| 5    | ~$0.15        |
| 20   | ~$0.60        |
| 50   | ~$1.50        |
| 100  | ~$3.00        |

Use `--limit 3` or the limit field in the UI to test before running large batches.

---

## CLI (advanced)

```bash
python app.py                           # start web UI
python main.py --dry-run                # scrape only, no API cost
python main.py --limit 5               # test with 5 jobs
python main.py                          # full run without UI
```
