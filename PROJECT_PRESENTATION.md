# ElectionCaffe — ECI Electoral Roll Downloader

> **Automated bulk download tool for India's Electoral Rolls from the Election Commission of India (ECI)**
>
> A project by **DataCaffe** | [DataCaffe.ai](https://datacaffe.ai)

---

## What is this Project?

The **ECI Electoral Roll Downloader** is a full-stack web application that automates the download of electoral roll PDFs from the Election Commission of India's official portal ([voters.eci.gov.in](https://voters.eci.gov.in)).

India has **28 states, 8 union territories, ~4,100+ Assembly Constituencies (ACs)**, and each AC has multiple parts (ranging from 10 to 400+ parts). Downloading these PDFs manually — one part at a time with captcha verification — would take weeks of effort. This tool reduces that to **minutes per state** with fully automated captcha solving and concurrent downloads.

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Automated Captcha Solving** | Uses `ddddocr` OCR engine to automatically solve ECI captcha challenges |
| **Bulk Download** | Download entire states, districts, or specific ACs in one click |
| **Multi-AC Concurrent Downloads** | Run multiple download tasks simultaneously from different browser tabs |
| **Smart Retry & Resume** | Failed parts are tracked and can be retried; already-downloaded PDFs are skipped |
| **Real-time Progress Dashboard** | Live stats showing download speed, ETA, per-AC progress, and failed part numbers |
| **File Browser** | Browse, search, and preview downloaded PDFs directly in the browser |
| **District-organized Storage** | PDFs saved in `State / District / AC_Name / *.pdf` folder hierarchy |
| **Dual Download Strategy** | Tries direct ZIP download first (faster), falls back to captcha-based API |

---

## How It Works

### Download Flow (Architecture)

```
User (Browser)
    │
    ▼
┌─────────────────┐
│  React Frontend  │  (Vite + TypeScript + Tailwind CSS)
│  Port 5173       │
└────────┬────────┘
         │ API calls
         ▼
┌─────────────────┐
│  Flask Backend   │  (Python, Port 5000)
│  browse.py       │
└────────┬────────┘
         │ Spawns background thread
         ▼
┌─────────────────────────────────────────────┐
│  Download Engine (downloader.py)             │
│  ┌─────────────┐  ┌──────────────────────┐  │
│  │ Strategy 1:  │  │ Strategy 2:          │  │
│  │ Direct ZIP   │  │ Captcha API → PDF    │  │
│  │ (No auth)    │  │ (ddddocr solver)     │  │
│  └─────────────┘  └──────────────────────┘  │
│           │                    │              │
│           ▼                    ▼              │
│     voters.eci.gov.in    gateway APIs        │
└─────────────────────────────────────────────┘
         │
         ▼
   📁 output_finalroll/
       └── State_Name/
           └── District_Name/
               └── AC_No_AC_Name/
                   └── *.pdf
```

### Step-by-Step Download Process

1. **User selects**: State → Year → Roll Type → ACs (or "All") → Language
2. **Backend fetches metadata** from ECI API:
   - Roll types available for that state/year
   - List of Assembly Constituencies
   - Part numbers for each AC
3. **Download Strategy 1 — Direct ZIP** (tried first):
   - Attempts to download a pre-packaged ZIP file from `voters.eci.gov.in/eroll/`
   - No captcha or authentication needed
   - If ZIP exists, extract PDFs directly
4. **Download Strategy 2 — Captcha API** (fallback):
   - Fetch captcha image from ECI gateway
   - Solve captcha automatically using `ddddocr` OCR
   - POST `generate-published-eroll` with captcha solution
   - Receive a UUID for the generated PDF
   - GET the PDF via external gateway (`gateway-vpd.eci.gov.in`)
   - Base64-decode the response → valid PDF file
5. **Progress tracking**: Real-time stats streamed to frontend via polling

### Captcha Solving

```
ECI Gateway                          Our Server
    │                                     │
    │  GET /captcha-service/              │
    │  generateCaptcha/eroll              │
    │ ◄───────────────────────────────────│
    │                                     │
    │  { captcha: "base64_jpeg",          │
    │    id: "captcha_uuid" }             │
    │ ────────────────────────────────────►│
    │                                     │
    │                              ┌──────┴──────┐
    │                              │  ddddocr    │
    │                              │  OCR Engine │
    │                              │  → "a5x2"   │
    │                              └──────┬──────┘
    │                                     │
    │  POST generate-published-eroll      │
    │  { captcha: "a5x2",                │
    │    captchaId: "...", ... }          │
    │ ◄───────────────────────────────────│
    │                                     │
    │  { payload: ["file-uuid"] }         │
    │ ────────────────────────────────────►│
```

- Captcha accuracy is ~60-80%, so the system retries up to 8 times per part
- Average: ~2-3 attempts per successful download
- Speed: ~20-40 PDFs per minute with 20 concurrent connections

---

## Technologies Used

### Backend (Python)

| Technology | Version | Purpose |
|-----------|---------|---------|
| **Python** | 3.11+ | Core language |
| **Flask** | 3.0+ | Web server / REST API |
| **aiohttp** | 3.9+ | Async HTTP client for concurrent downloads |
| **ddddocr** | 1.5.5 | OCR engine for captcha solving (v1.6.0 is broken!) |
| **Pillow** | 10.0+ | Image processing for captcha images |
| **asyncio** | stdlib | Async concurrency (event loop per download task) |
| **threading** | stdlib | Background download threads, thread-safe locks |
| **requests** | 2.31+ | Sync HTTP calls (metadata APIs) |
| **tqdm** | 4.66+ | CLI progress bars |
| **colorlog** | 6.7+ | Colored terminal logging |

### Frontend (TypeScript/React)

| Technology | Version | Purpose |
|-----------|---------|---------|
| **React** | 18.3 | UI framework |
| **TypeScript** | 5.6 | Type-safe JavaScript |
| **Vite** | 6.0 | Build tool & dev server |
| **Tailwind CSS** | 4.0 | Utility-first CSS framework |
| **React Router** | 6.28 | Client-side routing |
| **TanStack Query** | 5.62 | Server state management & API caching |
| **Framer Motion** | 12.36 | Animations & transitions |
| **react-pdf** | 9.2 | In-browser PDF preview |
| **pdfjs-dist** | 4.9 | PDF rendering engine |

### APIs Used (ECI Government)

| API Endpoint | Purpose |
|-------------|---------|
| `gateway-voters.eci.gov.in` | Main gateway — metadata, captcha, download generation |
| `gateway-vpd.eci.gov.in` | External gateway — fetch generated PDF files (no auth) |
| `voters.eci.gov.in/eroll/` | Direct ZIP download (when available) |

---

## Project Structure

```
eci-eroll-downloader/
│
├── browse.py              # Flask server — file browser + download API
├── downloader.py          # Core async download engine
├── api.py                 # ECI API calls (roll types, ACs, parts, languages)
├── captcha.py             # Captcha fetcher + ddddocr OCR solver
├── config.py              # API URLs, headers, state/language maps
├── utils.py               # Helpers (filename builder, directory builder, PDF validator)
├── progress.py            # Download progress tracking & persistence
├── district_names.json    # Curated district code → name mapping (597 districts)
├── requirements.txt       # Python dependencies
│
├── frontend-app/          # React + TypeScript frontend
│   ├── src/
│   │   ├── pages/
│   │   │   ├── DownloadPage.tsx   # Main download UI with progress dashboard
│   │   │   └── BrowsePage.tsx     # File browser & PDF viewer
│   │   ├── components/
│   │   │   ├── layout/            # Navbar, Footer, PageShell
│   │   │   └── browse/            # File browser components
│   │   ├── types/
│   │   │   └── api.ts             # TypeScript interfaces
│   │   └── index.css              # Tailwind theme & custom animations
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
└── output_finalroll/      # Downloaded PDFs (auto-created)
    └── State_Name/
        └── District_Name/
            └── AC_No_AC_Name/
                └── *.pdf
```

---

## How to Start the Application

### Prerequisites

- **Python 3.11+** installed
- **Node.js 18+** and **npm** installed
- Windows / Linux / macOS

### Step 1: Install Backend Dependencies

```bash
cd d:\ElectionCaffe\VoterData\eci-eroll-downloader
pip install -r requirements.txt
```

### Step 2: Install Frontend Dependencies

```bash
cd frontend-app
npm install
```

### Step 3: Start the Backend Server

```bash
cd d:\ElectionCaffe\VoterData\eci-eroll-downloader
python browse.py --port 5000
```

This starts the Flask server on **http://localhost:5000**

### Step 4: Start the Frontend Dev Server

Open a **new terminal**:

```bash
cd d:\ElectionCaffe\VoterData\eci-eroll-downloader\frontend-app
npm run dev
```

This starts the Vite dev server on **http://localhost:5173**

### Step 5: Open in Browser

Go to **http://localhost:5173** — you'll see the ElectionCaffe UI with two pages:
- **Download** — Select state, roll type, ACs, and start downloading
- **Browse** — Browse and preview already-downloaded PDFs

### Production Build (Optional)

```bash
cd frontend-app
npm run build
```

Built files go to `frontend-app/dist/` — served automatically by Flask at `http://localhost:5000`

---

## Data Coverage

| Metric | Value |
|--------|-------|
| **States supported** | 20 (all major states + NCT of Delhi) |
| **Total ACs** | ~4,100+ |
| **Total parts** | ~100,000+ across all states |
| **Languages** | English + regional (Tamil, Hindi, Bengali, Kannada, Malayalam, Telugu, Marathi, Gujarati, Punjabi) |
| **Roll types** | Final Roll, Supplement, Draft, etc. |

---

## Concurrency & Performance

- **20 concurrent connections** per download task (configurable)
- **Multiple simultaneous downloads** supported (one per browser tab)
- **Rate limiter**: Minimum 0.6s between requests to avoid overwhelming ECI servers
- **Exponential backoff**: On errors, waits 2s → 4s → 8s → ... up to 60s
- **Smart skip**: Already-downloaded PDFs are detected and skipped automatically
- **Typical speed**: ~20-40 PDFs/minute depending on captcha accuracy and network

---

## Real-time Dashboard

The download dashboard shows:
- **Total parts** to download vs already done vs in-progress
- **Download speed** (parts per minute)
- **ETA** (estimated time remaining)
- **Captcha accuracy** percentage
- **Per-AC breakdown**: each AC's status, progress bar, and failed part numbers
- **Current district & AC** being processed

---

## Key Design Decisions

1. **Dual download strategy**: ZIP first (fast, no captcha) → captcha API fallback (reliable)
2. **Thread-per-task**: Each download runs in its own thread with its own asyncio event loop — no cross-thread lock issues
3. **Thread-safe captcha solver**: Single shared ddddocr instance with threading.Lock for serialized inference
4. **District names from curated JSON**: ECI API doesn't return district names, so we maintain a local mapping of 597 districts
5. **Folder structure**: `State / District / AC` — easy to navigate and backup

---

## Challenges Solved

| Challenge | Solution |
|-----------|----------|
| ECI API requires captcha for every PDF | Automated OCR with ddddocr, retry up to 8 times |
| ECI doesn't provide district names | Curated `district_names.json` with 597 entries |
| asyncio.Lock bound to event loop errors | Replaced with threading.Lock for cross-thread safety |
| ddddocr not thread-safe | Added threading.Lock around OCR classification |
| Multiple concurrent downloads crash | Each task gets own RateLimiter + event loop |
| Windows file system issues | Retry loop for `os.replace()`, ASCII-safe print output |

---

## About

**ElectionCaffe** is a project by **DataCaffe** focused on election data extraction and voter data analysis for India.

- Website: [DataCaffe.ai](https://datacaffe.ai)
- Tech Stack: Python + React + TypeScript
- License: Internal use

---

*Last updated: March 2026*
