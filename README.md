# ResTail - Agentic Job Application Pipeline

ResTail automatically scrapes job listings and tailors your resume to each job using AI. It runs entirely on your computer - nothing is sent to any server except the Anthropic API for AI processing.

## What it does

1. Scrapes LinkedIn, Indeed, Dice, Glassdoor, Interstride and Handshake for entry-level to senior-level jobs matching your titles.
2. Filters by location priority, date (last 7 days).
3. For each job: gathers company intelligence (domain, tech stack, culture signals, sponsorship verdict) then tailors your resume using 6 AI passes (tailor → grammar → verify → calibrate → validate → ATS audit).
4. Produces a formatted `.docx` resume for every passing job.
5. Lets you paste job URLs you found yourself to bypass scraping
6. Lets you paste job description you found yourself to bypass scraping.
7. Lets you run ATS scan.
8. Automatically identifies H1B-friendly employers using USCIS records to filter or flag opportunities based on historical data.
9. Detects visa sponsorship language in job descriptions and cross-references employers against USCIS H1B records, E-Verify participation data, and H1B Grader to flag or filter sponsorship-unlikely companies.
   
## Requirements

- Python 3.10 or higher
- Git
- An Anthropic API key (get one free at [console.anthropic.com](https://console.anthropic.com))

## Setup - Step by Step

### Step 1 - Install Git

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

### Step 2 - Install Python

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

### Step 3 - Clone the repository

```bash
git clone https://github.com/Hamju1999/AIResumeTailor.git
cd AIResumeTailor
```

### Step 4 - Install dependencies

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

### Step 5 - Get an Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Click **API Keys** in the left sidebar
4. Click **Create Key**
5. Copy the key (starts with `sk-ant-...`) - you will only see it once, save it somewhere safe

The API key is charged per use. A typical run of 10 jobs costs approximately $0.30–$0.60.

### Step 6 - Run the app

**Windows:**
```cmd
cd AIResumeTailor
python app.py
```

**Mac/Linux:**
```bash
cd AIResumeTailor
python3 app.py
```

Open your browser and go to: **http://localhost:5000**

On first run, the setup wizard opens automatically.

### Step 7 - Complete the setup wizard

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
| Experience level | Entry level / Mid / Senior - controls which jobs are scraped and how the resume is framed |
| Visa sponsorship | Off / Flag / Filter - uses USCIS public H1B data to label or remove unlikely sponsors |

After saving, your config is stored in `user_config.json` locally. You never need to fill this in again unless you want to change something.

## Preparing your files

### Master Resume file

**What it is:** Your complete professional record - every job, every project, every skill, every certification you have ever had. The AI uses this as the only source of truth. Nothing is invented - everything in the output must trace back to this file.

**Format:** Plain text file (`.txt`) is recommended. PDF works only if it has a text layer (not a scanned image).

**What to include:**

```
PERSONAL INFORMATION
Full name, city, phone, email, LinkedIn, GitHub, Portfolio

EDUCATION
 institution:
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
  
  Write freely and in detail - the AI will select and condense.
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
Group them however you like - the AI will regroup them by relevance.
Be exhaustive - do not leave skills out.

CERTIFICATIONS
For each certification:
  Certification name - Issuing organisation - Year completed

AWARDS AND RECOGNITION (if any)
  Award name - Issuing body - Year
```

**Important:** Write naturally and in detail. The AI reads this file to understand what you have actually done. Vague entries like "used Python" produce vague resumes. Specific entries like "built a Python ETL pipeline to process 5.7 million CSV records across 12 monthly files" produce specific, credible resumes.

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
1. Name - bold, 16pt, centered, ALL CAPS
2. Contact line - 10pt, centered (City | Phone | Email | LinkedIn | GitHub | Portfolio)
3. Summary - 2 sentences, first-person
4. Technical Skills - 3 lines grouped as you like:
   Programming & Engineering: [tools]
   Applied AI & NLP: [tools]
   Analytics & Visualization: [tools]
5. Professional Experience - role header bold 12pt, then 4-5 bullet points
6. Academic Projects - project title bold 12pt with colon, then 3 bullet points each
7. Education - institution bold 12pt, degree 11pt
8. Certifications - bulleted list, top 3 most relevant only (if applicable)

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

## Using the app

### Full scrape mode

1. Open **http://localhost:5000**
2. Click **Full scrape**
3. Set a limit (e.g. 3 for a test run, 0 for all jobs)
4. Optional before clicking Start:
  - Check Include certifications if the role values formal certifications
  - Set Visa sponsorship targeting to Flag or Filter if you need sponsorship
5. Click **Start**
6. Watch the live log stream while it runs
7. Download resumes from the **Results** panel when done

### My job links mode (recommended for fresh jobs)

1. Find a job on LinkedIn, Indeed, or any job board
2. Copy the URL
3. Go to the **My job links** tab
4. Paste the URL and click **Add**
5. Add more URLs if needed
6. Optional before clicking Start:
  - Check Include certifications if the role values formal certifications
  - Set Visa sponsorship targeting to Flag or Filter if you need sponsorship
7. Click **Start**

This skips scraping entirely and goes straight to AI tailoring. Useful for jobs posted hours ago.

### Job Description mode (when the link doesn't load)

1. Go to the **Job Description tab**
2. Enter the company name and job title
3. Paste the full job description text
4. Optional before clicking Start:
  - Check Include certifications if the role values formal certifications
  - Set Visa sponsorship targeting to Flag or Filter if you need sponsorship
5. Click **Start**

The AI uses the pasted text directly. Useful for JavaScript-rendered pages (Ashby, Greenhouse) that the scraper cannot access.

### History

Every run is saved. Click **History** to download resumes from previous runs.

## Changing your config

To update your name, files, locations, job titles, or API key:

1. Go to **http://localhost:5000**
2. Visit **http://localhost:5000/setup**
3. Edit whatever you want to change
4. Click **Save Configuration**

Files you don't re-upload are kept as-is.

## Keeping the code up to date

When the repo owner pushes updates:

```bash
cd AIResumeTailor
git pull
```

Then restart:
```bash
python app.py        # Windows
python3 app.py       # Mac/Linux
```

Your `user_config.json` and uploaded files are preserved across updates.

## Troubleshooting

**"No module named X" error:**
```bash
pip install -r requirements.txt          # Windows
pip3 install -r requirements.txt         # Mac/Linux
```

**"401 Invalid authentication credentials":**
Your API key is wrong or missing. Go to `/setup` and re-enter it.

**"All jobs failed"**: Open the manifest JSON in output/manifest_*.json and check the failures array for the specific reason. Common causes: JSON parse error (Claude output reasoning instead of JSON - rerun), rate limit timeout, or verification failure.

**App won't start - port already in use:**
Something else is running on port 5000. Either stop it, or change the port in `app.py` (last line: `port=5000`).

**Jobs scrape but no resumes produced:**
Check the live log for "Verification FAILED" or "Validation FAILED" messages with the specific reason.

## File structure

```
AIResumeTailor/
├── app.py                  ← Start here: python app.py
├── config.py               ← Reads from user_config.json
├── pipeline.py             ← Orchestrates all AI phases per job
├── scraper.py              ← Scrapes 6 job boards
├── tailor.py               ← Resume tailoring agent
├── verifier.py             ← Factual accuracy checker
├── validator.py            ← Format rules checker
├── calibrator.py           ← Tone and credibility calibrator
├── grammar_fixer.py        ← Grammar and punctuation pass
├── format_parser.py        ← Reads format template dynamically
├── company_intel.py        ← Gathers company context before tailoring
├── visa_sponsors.py        ← H1B / STEM OPT / E-Verify checks
├── ats_scorer.py           ← Dynamic ATS keyword scoring
├── resume_builder.py       ← Renders .docx from tailored resume
├── llm_client.py           ← Anthropic SDK wrapper with rate limiting
├── models.py               ← Pydantic data models
├── prompts.py              ← All LLM system prompts
├── pdf_reader.py           ← Extracts text from PDF uploads
├── main.py                 ← CLI entry point
├── user_config.json        ← Your personal settings (gitignored)
├── master_resume.txt       ← Your resume source file (uploaded in setup)
├── format_template.txt     ← Format spec (uploaded in setup)
├── output/
│   ├── resumes/<run_id>/   ← .docx files per run
│   ├── manifest_*.json     ← Full run audit trail
│   └── job_links_*.csv     ← Job links per run
├── templates/
│   ├── index.html          ← Main UI
│   └── setup.html          ← Setup wizard
└── requirements.txt        ← Python dependencies
```

## Privacy

- Everything runs on your computer
- Your master resume never leaves your machine except in API calls to Anthropic
- `user_config.json` is gitignored - it is never pushed to GitHub
- The app is only accessible at `localhost:5000` - not visible to anyone else on the internet

## Cost estimate

Each job processed uses approximately 36,000–40,000 input tokens across 7 AI passes (including company intelligence gathering and ATS keyword extraction). With a large master resume (70k+ chars) the token estimate per job is higher and the rate limiter will add automatic pauses between calls.
At Anthropic's current pricing for claude-sonnet-4-6:

| Jobs | Estimated cost |
|------|---------------|
| 5    | ~$0.20       |
| 20   | ~$0.80        |
| 50   | ~$2.00        |
| 100  | ~$4.00        |

Use `--limit 3` or the limit field in the UI to test before running large batches.

## CLI (advanced)

```bash
python app.py                           # start web UI
python main.py --dry-run                # scrape only, no API cost
python main.py --limit 5               # test with 5 jobs
python main.py                          # full run without UI
```

## Author

**Mohammad Hamza Piracha** |
Data Scientist | 
[LinkedIn](https://www.linkedin.com/in/hamza-piracha) | hamzapiracha9022@gmail.com
