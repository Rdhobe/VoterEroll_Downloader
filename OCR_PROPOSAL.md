# OCR Data Extraction Proposal — Electoral Roll Voter Data

> **Project**: ElectionCaffe — Voter Data Digitization
> **Prepared by**: DataCaffe Team
> **Date**: March 2026
> **Status**: Awaiting Approval

---

## 1. Executive Summary

We have successfully built an automated tool to **download electoral roll PDFs** from the Election Commission of India (ECI). We currently have **100,000+ PDF files** covering 20 states, ~4,100 Assembly Constituencies.

The next step is to **extract voter data from these PDFs** into a structured database (rows & columns) for analysis, search, and reporting. This document proposes using **Optical Character Recognition (OCR)** to convert PDF images into structured voter records.

### Goal
Convert unstructured PDF voter lists → structured database with searchable, queryable voter records.

### Expected Output

| Serial No | EPIC (Voter ID) | Voter Name | Father/Husband Name | House No | Age | Gender | State | District | AC | Part |
|-----------|-----------------|------------|---------------------|----------|-----|--------|-------|----------|----|------|
| 1 | ABC1234567 | Rajesh Kumar | Ram Kumar | 45/A | 32 | M | Tamil Nadu | Chennai | 1 | 5 |
| 2 | XYZ9876543 | Priya Devi | Suresh Singh | 12 | 28 | F | Tamil Nadu | Chennai | 1 | 5 |

---

## 2. What is OCR?

**OCR (Optical Character Recognition)** is a technology that converts images of text into machine-readable text. It works by:

```
┌──────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────┐
│  PDF     │ ──►  │  Convert to  │ ──►  │  OCR Engine  │ ──►  │ Structured│
│  (Image) │      │  Image (PNG) │      │  reads text  │      │ Text Data │
└──────────┘      └──────────────┘      └──────────────┘      └──────────┘
```

### How OCR reads a voter roll page:

```
┌─────────────────────────────────────────────────────┐
│  ELECTORAL ROLL — Part No. 5                         │
│  AC: 001 — Chennai North                             │
│                                                      │
│  ┌─────┬────────────┬──────────────┬─────┬────────┐ │
│  │ No  │ Voter ID   │ Name         │ Age │ Gender │ │
│  ├─────┼────────────┼──────────────┼─────┼────────┤ │
│  │ 1   │ ABC1234567 │ Rajesh Kumar │ 32  │ M      │ │
│  │ 2   │ XYZ9876543 │ Priya Devi   │ 28  │ F      │ │
│  └─────┴────────────┴──────────────┴─────┴────────┘ │
└─────────────────────────────────────────────────────┘
                         │
                    OCR Engine
                         │
                         ▼
        Row 1: {serial: 1, voter_id: "ABC1234567",
                name: "Rajesh Kumar", age: 32, gender: "M"}
        Row 2: {serial: 2, voter_id: "XYZ9876543",
                name: "Priya Devi", age: 28, gender: "F"}
```

---

## 3. Complete Pipeline — How It Works

### Phase 1: PDF to Images

Each PDF page is converted into a high-resolution image (300 DPI) for OCR processing.

```
input:  output_finalroll/Tamil_Nadu/Chennai/AC_1_Chennai_North/part_5.pdf
        → Page 1 image (PNG, 300 DPI)
        → Page 2 image (PNG, 300 DPI)
        → ...
```

**Tool**: `pdf2image` + Poppler (both free, open-source)

### Phase 2: OCR — Image to Text

The OCR engine scans each image, detects text regions, and extracts text with position information.

```
┌────────────────────────────────────────────────────────────────┐
│                        OCR ENGINE                              │
│                                                                │
│  Step 1: Pre-processing                                        │
│  ├── Deskew (fix tilted scans)                                │
│  ├── Denoise (remove speckles)                                │
│  ├── Binarize (convert to black & white)                      │
│  └── Enhance contrast                                          │
│                                                                │
│  Step 2: Text Detection                                        │
│  ├── Locate text regions on the page                          │
│  ├── Identify table structure (rows & columns)                │
│  └── Detect individual characters                              │
│                                                                │
│  Step 3: Character Recognition                                 │
│  ├── Match detected shapes to known characters                │
│  ├── Use language model for context (e.g., common names)      │
│  └── Output: text + confidence score per character            │
│                                                                │
│  Step 4: Post-processing                                       │
│  ├── Spell correction                                          │
│  ├── Format validation (voter ID pattern: 3 letters + 7 digits)│
│  └── Structured output (JSON/CSV)                              │
└────────────────────────────────────────────────────────────────┘
```

### Phase 3: Parsing — Raw Text to Structured Fields

OCR gives raw text. We need custom parsing logic to extract specific fields:

```
Raw OCR Output:
"1 TN/01/005/0001 ABC1234567 राजेश कुमार Rajesh Kumar
पिता का नाम Father's Name राम कुमार Ram Kumar
मकान संख्या House No 45/A आयु Age 32 लिंग Gender पुरुष Male"

                    ▼ Parser ▼

Structured Record:
{
  "serial_no": 1,
  "voter_id": "ABC1234567",
  "voter_name": "Rajesh Kumar",
  "voter_name_regional": "राजेश कुमार",
  "father_husband_name": "Ram Kumar",
  "house_no": "45/A",
  "age": 32,
  "gender": "M",
  "section_no": "0001",
  "part_no": 5,
  "ac_no": 1,
  "ac_name": "Chennai North",
  "district": "Chennai",
  "state": "Tamil Nadu"
}
```

### Phase 4: Database Insert

Parsed records are inserted into the database in bulk (1000 records per batch).

```
Parsed JSON ──► Validation ──► Deduplication ──► Bulk INSERT ──► SQLite/PostgreSQL
                    │                │
                    ▼                ▼
              Reject invalid    Skip if voter_id
              records            already exists
```

### Full Pipeline Summary

```
100,000+ PDFs
    │
    ▼
[PDF to Image]  ──► ~500,000+ page images
    │
    ▼
[OCR Engine]    ──► Raw text with positions
    │
    ▼
[Parser]        ──► Structured voter records
    │
    ▼
[Validator]     ──► Clean, validated records
    │
    ▼
[Database]      ──► 50M-150M searchable voter rows
```

---

## 4. OCR Engine Options (All Free & Open-Source)

### Option A: PaddleOCR (Recommended)

| Aspect | Detail |
|--------|--------|
| **Developer** | Baidu (open-source, Apache 2.0 license) |
| **Cost** | Free |
| **Table Detection** | Built-in table structure recognition |
| **Indian Languages** | Hindi, Tamil, Bengali, Kannada, Telugu, Malayalam, Marathi, Gujarati, Punjabi |
| **English Accuracy** | 95-98% on clean prints |
| **Regional Language Accuracy** | 85-92% on clean prints |
| **Speed** | ~2-5 seconds per page (with GPU), ~8-15 seconds (CPU only) |
| **Table Extraction** | Automatic row/column detection — ideal for voter rolls |
| **GPU Required** | No (but 3-5x faster with GPU) |

**Why recommended**: Best free option for structured table documents with Indian language support.

### Option B: Tesseract OCR

| Aspect | Detail |
|--------|--------|
| **Developer** | Google (open-source) |
| **Cost** | Free |
| **Table Detection** | No built-in table detection (needs custom logic) |
| **Indian Languages** | All major Indian languages supported |
| **English Accuracy** | 90-95% on clean prints |
| **Regional Language Accuracy** | 75-85% on clean prints |
| **Speed** | ~3-8 seconds per page |
| **Table Extraction** | Manual — requires coordinate-based extraction |

**Downside**: No table awareness. We'd need to manually define column boundaries.

### Option C: EasyOCR

| Aspect | Detail |
|--------|--------|
| **Developer** | JaidedAI (open-source) |
| **Cost** | Free |
| **Indian Languages** | Hindi, Tamil, Bengali, Kannada, Telugu, Marathi |
| **English Accuracy** | 92-96% on clean prints |
| **Speed** | ~5-10 seconds per page |
| **Table Extraction** | No built-in table detection |

### Recommendation

**PaddleOCR** is the best choice because:
1. Built-in table structure recognition (critical for voter roll format)
2. Best accuracy for Indian languages among free tools
3. Actively maintained with regular updates
4. Can run on CPU (no expensive GPU required)

---

## 5. Accuracy Analysis

### 5.1 Overall Accuracy Expectations

| Data Field | Expected Accuracy | Notes |
|-----------|-------------------|-------|
| **Voter ID (EPIC)** | **97-99%** | Alphanumeric, fixed format (3 letters + 7 digits), easy to validate |
| **Serial Number** | **98-99%** | Simple numbers, sequential — easy to validate |
| **Voter Name (English)** | **93-97%** | Printed text, good accuracy |
| **Voter Name (Regional)** | **82-90%** | Depends on print quality & language complexity |
| **Father/Husband Name** | **90-95%** | Same as voter name |
| **Age** | **95-98%** | 2-3 digit number, easy to validate (range: 18-120) |
| **Gender** | **98-99%** | Single character (M/F), easy to validate |
| **House Number** | **88-93%** | Mixed alphanumeric, sometimes handwritten — harder |
| **Photo** | N/A | Cannot extract, not needed for database |

### 5.2 Accuracy by Language

| Language | Script | OCR Accuracy | Notes |
|----------|--------|-------------|-------|
| **English** | Latin | **95-98%** | Best accuracy, clean prints |
| **Hindi** | Devanagari | **88-93%** | Good support in PaddleOCR |
| **Tamil** | Tamil | **85-90%** | Complex script, decent accuracy |
| **Bengali** | Bengali | **85-90%** | Similar to Hindi accuracy |
| **Telugu** | Telugu | **83-88%** | Complex script |
| **Kannada** | Kannada | **83-88%** | Complex script |
| **Malayalam** | Malayalam | **80-87%** | Most complex South Indian script |
| **Marathi** | Devanagari | **88-93%** | Same script as Hindi |
| **Gujarati** | Gujarati | **85-90%** | Moderate complexity |
| **Punjabi** | Gurmukhi | **85-90%** | Moderate complexity |

### 5.3 Accuracy by PDF Quality

| PDF Quality | Accuracy Impact | Prevalence |
|-------------|----------------|------------|
| **Clean digital PDF** (text-based) | 98-99% | ~20% of PDFs |
| **High-quality scan** (300 DPI) | 93-97% | ~50% of PDFs |
| **Medium-quality scan** (150-200 DPI) | 85-92% | ~25% of PDFs |
| **Low-quality scan** (blurry/tilted) | 70-82% | ~5% of PDFs |

### 5.4 Validation & Error Correction

We can automatically validate and correct many errors:

| Validation Rule | What It Catches | Recovery Rate |
|----------------|-----------------|---------------|
| Voter ID format: `[A-Z]{3}[0-9]{7}` | Misread characters in EPIC | ~95% correctable |
| Age range: 18-120 | OCR errors in age field | ~99% correctable |
| Gender: M/F only | Misread gender character | ~99% correctable |
| Serial numbers: sequential | Gaps or duplicates in serial | ~90% detectable |
| State/AC metadata from filename | Wrong state/AC assignment | 100% accurate (from filename) |
| Duplicate voter ID check | Same voter scanned twice | 100% detectable |

### 5.5 Realistic End-to-End Accuracy

After OCR + validation + error correction:

| Metric | English PDFs | Regional Language PDFs |
|--------|-------------|----------------------|
| **Record-level accuracy** (all fields correct) | **90-95%** | **78-88%** |
| **Field-level accuracy** (individual field correct) | **95-98%** | **85-93%** |
| **Voter ID accuracy** (most critical field) | **97-99%** | **95-98%** |
| **Usable records** (enough fields to identify voter) | **97-99%** | **92-96%** |

> **Note**: "Usable record" means voter ID + name + AC are correct, even if minor fields like house number have errors.

---

## 6. Data Volume Estimates

### 6.1 Input Data

| Metric | Estimate |
|--------|----------|
| Total PDF files | ~100,000+ |
| Average pages per PDF | 10-30 pages |
| Total pages to process | ~500,000 - 1,500,000 pages |
| Voters per page | ~20-50 |
| **Total voter records** | **50,000,000 - 150,000,000 (5-15 Crore)** |

### 6.2 Processing Time Estimates

| Hardware | Speed (per page) | Total Time (1M pages) | Total Time (500K pages) |
|----------|------------------|-----------------------|------------------------|
| CPU only (i5/i7) | ~10-15 sec | ~115-175 days | ~58-87 days |
| CPU only (parallel, 4 cores) | ~3-4 sec | ~35-46 days | ~17-23 days |
| GPU (RTX 3060 or similar) | ~1-2 sec | ~12-23 days | ~6-12 days |
| GPU (RTX 4090 or high-end) | ~0.5-1 sec | ~6-12 days | ~3-6 days |
| **Cloud GPU (4x T4)** | ~0.3 sec | ~3-4 days | ~1.5-2 days |

> **Recommendation**: Start with CPU processing for one state to validate accuracy. Scale to GPU or cloud for full processing.

### 6.3 Storage Requirements

| Component | Size Estimate |
|-----------|--------------|
| Source PDFs (already downloaded) | ~50-200 GB |
| Temporary page images | ~500 GB - 1.5 TB (can delete after processing) |
| SQLite database (final) | ~15-50 GB |
| PostgreSQL database (final) | ~20-60 GB |

---

## 7. Database Schema

### Primary Table: `voters`

```sql
CREATE TABLE voters (
    id              BIGINT PRIMARY KEY AUTOINCREMENT,

    -- Location
    state_cd        VARCHAR(5)    NOT NULL,    -- S22, S25, etc.
    state_name      VARCHAR(50)   NOT NULL,    -- Tamil Nadu, West Bengal
    district_name   VARCHAR(100),              -- Chennai, Kolkata
    ac_no           INT           NOT NULL,    -- Assembly Constituency number
    ac_name         VARCHAR(100),              -- Constituency name
    part_no         INT           NOT NULL,    -- Part number

    -- Voter Identity
    serial_no       INT,                       -- Serial within the part
    voter_id        VARCHAR(20)   UNIQUE,      -- EPIC number (primary identifier)

    -- Personal Details
    voter_name      VARCHAR(150),              -- Name in English
    voter_name_local VARCHAR(150),             -- Name in regional language
    relation_type   VARCHAR(20),               -- Father / Husband / Mother
    relation_name   VARCHAR(150),              -- Relation's name
    house_no        VARCHAR(50),               -- House / Door number
    age             INT,                       -- Age
    gender          CHAR(1),                   -- M / F / O

    -- Metadata
    year            INT           NOT NULL,    -- Electoral roll year
    roll_type       VARCHAR(30),               -- FinalRoll, Supplement, etc.
    section_no      VARCHAR(20),               -- Section within part
    polling_station VARCHAR(200),              -- Polling station name

    -- Processing Info
    source_pdf      VARCHAR(200),              -- Source PDF filename
    page_no         INT,                       -- Page number in PDF
    confidence      FLOAT,                     -- OCR confidence score (0-100)
    extracted_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes for fast search
    INDEX idx_voter_id (voter_id),
    INDEX idx_state_ac (state_cd, ac_no),
    INDEX idx_name (voter_name),
    INDEX idx_district (district_name)
);
```

### Summary Table: `extraction_log`

```sql
CREATE TABLE extraction_log (
    id              INT PRIMARY KEY AUTOINCREMENT,
    pdf_file        VARCHAR(200),
    state_cd        VARCHAR(5),
    ac_no           INT,
    part_no         INT,
    total_pages     INT,
    records_extracted INT,
    records_failed  INT,
    avg_confidence  FLOAT,
    processing_time_sec FLOAT,
    status          VARCHAR(20),    -- success / partial / failed
    error_message   TEXT,
    processed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 8. Technology Stack (All Free)

| Layer | Technology | Cost |
|-------|-----------|------|
| OCR Engine | PaddleOCR | Free (Apache 2.0) |
| PDF to Image | pdf2image + Poppler | Free |
| Image Pre-processing | OpenCV + Pillow | Free |
| Programming Language | Python 3.11+ | Free |
| Data Processing | pandas | Free |
| Database | SQLite (small) or PostgreSQL (large) | Free |
| ORM / DB Access | SQLAlchemy or raw SQL | Free |
| Progress Tracking | tqdm | Free |
| **Total Cost** | | **$0** |

### Python Packages Required

```
paddlepaddle          # PaddleOCR deep learning backend
paddleocr             # OCR engine with table detection
pdf2image             # PDF page to image conversion
opencv-python         # Image pre-processing
Pillow                # Image handling
pandas                # Data structuring
sqlalchemy            # Database ORM (optional)
tqdm                  # Progress bars
```

### System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Windows 10 / Linux | Windows 11 / Ubuntu 22+ |
| Python | 3.9+ | 3.11+ |
| RAM | 8 GB | 16 GB |
| Disk | 100 GB free | 500 GB free |
| CPU | 4 cores | 8+ cores |
| GPU | Not required | NVIDIA GPU (CUDA) for 3-5x speed |
| Poppler | Required | Pre-built binaries available |

---

## 9. Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Low-quality PDFs reduce accuracy | Medium | Medium | Pre-processing (deskew, denoise, contrast) |
| Regional scripts misread | Medium | High | Use PaddleOCR (best regional support), validate with patterns |
| Processing takes too long (CPU only) | Low | High | Start with 1 state, parallelize, upgrade to GPU later |
| Disk space shortage (temp images) | Low | Medium | Process and delete page images in batches |
| Voter ID misread → duplicate/missing records | High | Low | Format validation (3 letters + 7 digits), dedup check |
| Table structure not detected | High | Low | PaddleOCR has built-in table detection, fallback to coordinate-based |
| Different PDF formats across states | Medium | High | Build per-state parser templates, test each state separately |

---

## 10. Implementation Phases

### Phase 1: Proof of Concept (1-2 weeks)
- Set up PaddleOCR environment
- Process 1 state, 1 AC, 1 part (single PDF)
- Validate extracted data manually against PDF
- Measure accuracy per field
- **Deliverable**: Accuracy report for one PDF

### Phase 2: Single State Pipeline (2-3 weeks)
- Build full pipeline for one state (English PDFs)
- Create database schema and insert logic
- Add validation rules and error correction
- Process all PDFs for that state
- **Deliverable**: Complete voter database for 1 state

### Phase 3: Multi-State Expansion (3-4 weeks)
- Adapt parser for different state PDF formats
- Add regional language support
- Parallelize processing across CPU cores
- Process remaining states
- **Deliverable**: Full database across all downloaded states

### Phase 4: Quality Assurance (1-2 weeks)
- Random sampling: manually verify 1000 records across states
- Identify and fix systematic errors
- Generate quality report
- **Deliverable**: Accuracy report with confidence metrics

---

## 11. Expected Deliverables

| Deliverable | Description |
|-------------|-------------|
| SQLite/PostgreSQL database | 50M-150M voter records, searchable |
| Extraction accuracy report | Per-state, per-language accuracy metrics |
| Quality dashboard | Web UI showing extraction stats and errors |
| Re-processing tool | Re-run OCR on failed/low-confidence PDFs |
| Search API | Query voters by name, voter ID, AC, district |

---

## 12. Summary

| Aspect | Detail |
|--------|--------|
| **What** | Extract voter data from 100,000+ ECI electoral roll PDFs into a structured database |
| **How** | PaddleOCR (free, open-source) + Python pipeline |
| **Accuracy** | 90-95% for English, 78-88% for regional languages (before validation) |
| **Voter ID Accuracy** | 97-99% (most critical field) |
| **Cost** | $0 (all open-source tools) |
| **Time** | 8-12 weeks for full pipeline (all states) |
| **Output** | 50-150 Million voter records in searchable database |
| **Hardware** | Runs on existing machine (CPU), optional GPU for speed |

---

## Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Prepared by | | March 2026 | |
| Reviewed by | | | |
| Approved by | | | |

---

*Document version: 1.0 | ElectionCaffe by DataCaffe*
