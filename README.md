# web-browser-pubs-openai

# Publication Harvester Agent — Instruction Manual

This document defines how the ChatGPT Atlas Agent should operate when connected to
the Publication Harvester backend. The goal is to automate large‑scale crawling,
PDF extraction, Gemini-based Markdown conversion, and pgvector storage.

---

## 1. Agent Responsibilities

The Agent should:

1. Receive user requests such as:
   - "Crawl DESY P05 + P07 and index all open-access PDFs from 2007–2025."
   - "Harvest all OA papers from these archive URLs."
   - "Reprocess papers for a specific year."

2. Use the backend Action **/crawl** to start a job.

3. Monitor job progress via **/job-status/{job_id}**.

4. Handle browser automation when needed:
   - Logging into portals.
   - Accepting cookie banners.
   - Navigating JavaScript-heavy sites.
   - Extracting lists of publication links or PDFs when simple HTTP scraping fails.

5. Provide stable summaries of running jobs WITHOUT spamming calls.

---

## 2. Workflow Overview

### Step A — Interpret User Request
The Agent extracts:
- List of publication source URLs
- Year range (optional)
- Special constraints (open-access only, specific domains, etc.)

### Step B — Call Backend to Start Crawl
Using the Action:

```
POST /crawl
{
  "sources": [...],
  "year_min": ...,
  "year_max": ...
}
```

The backend:
- Crawls all specified sources
- Finds all available years
- Identifies open-access PDFs
- Downloads PDFs
- Sends each to Gemini for full Markdown extraction
- Splits markdown into section/subsection chunks
- Embeds each chunk
- Stores everything in Postgres + pgvector

### Step C — Monitor Progress
Use:

```
GET /job-status/{job_id}
```

Show:
- Total PDFs discovered
- PDFs processed
- Remaining PDFs
- Any errors

### Step D — Use Browser When Necessary
If the backend cannot scrape a site due to:
- Authentication
- Dynamic content
- JS-rendered archives
- CSRF protections

Then the Agent:
- Navigates with browser commands
- Extracts necessary data
- Sends extracted PDF URLs to backend via an additional endpoint:
  `/manual-pdf-submit`

---

## 3. Agent Behavior Rules

### 3.1 When to Use Backend Actions
Use Actions whenever the operation is related to:
- Starting a crawl
- Checking crawl progress
- Submitting manually obtained links

### 3.2 When to Use Browser Control
Use browser navigation only when:
- Login or forms are required
- Content is hidden behind JS
- PDF links are not present in the page HTML

### 3.3 Avoid
- Repeating Actions too frequently
- Starting duplicate jobs for the same URLs
- Attempting to scrape inside ChatGPT instead of using the backend

---

## 4. Expected Outputs to User
The Agent should provide:
- Progress updates ("17 / 63 papers processed")
- Final summary:
  - Total papers indexed
  - Years covered
  - Number of sections/chunks stored
- Clear success confirmation or error report

---

## 5. Example User Requests

### Example 1
"Index all open-access publications from DESY P05 from 2015–2024."

### Example 2
"Log in to this publisher portal, extract all PDF links from 2020–2021 issues, and index them."

### Example 3
"Check if yesterday's crawl finished."

---

## 6. Future Expansion
The Agent design allows for eventual:
- Automatic rate limiting
- Scheduling recurring crawls
- Automatic retry of failed PDFs
- Synchronization with lab internal datasets

---

## Setup and Deployment

### Prerequisites
- Docker and Docker Compose
- PostgreSQL 16
- Gemini API key
- OpenAI API key

### Running the Backend

1. Clone this repository
2. Set your API keys in `docker-compose.yml`
3. Run:
```bash
docker-compose up -d
```

The backend will be available at `http://localhost:8000`

### API Endpoints

- `POST /crawl` - Start a new crawl job
- `GET /job-status/{job_id}` - Check job status
- `POST /manual-pdf-submit` - Submit manually extracted PDF URLs