# mt-downloader

Multi-threaded chunked file downloader implemented in Python.

## 📌 Overview

This project implements a **parallel file downloading system** using multiple threads, where each thread downloads a distinct byte range of a file using HTTP Range requests.


## ⚙️ Features

- Multi-threaded downloading using HTTP `Range` headers
- Dynamic chunk partitioning
- Shared progress tracking with thread-safe updates
- Retry mechanism with exponential backoff
- HEAD → Range fallback for robust server probing
- Integrity checks:
  - Per-chunk completeness
  - Final file size verification
- Local testing using a Range-supporting HTTP server

---

## 🧠 Design

### Threading Model

- One thread per chunk
- Main thread orchestrates:
  - probe → partition → spawn → join
- Shared state protected via `threading.Lock`
- Cancellation via `threading.Event`

---

### File Writing Model

- File is pre-allocated to total size
- Each thread:
  - seeks to its assigned offset
  - writes its chunk directly

> Note: This uses seek-based writes; correctness is ensured via disjoint chunk regions.

---

### Network Model

- Uses `urllib` (low-level control, no abstraction)
- Supports:
  - HEAD-based probing
  - Fallback to `Range: bytes=0-0` probe
- Enforces:
  - HTTP 206 Partial Content
  - Content-Range validation

---

## 📁 Project Structure

```

mt-downloader/
├── src/mt_downloader/
│   ├── main.py        # CLI entry
│   ├── core.py        # Orchestrator
│   ├── worker.py      # Thread logic
│   ├── network.py     # Server probing
│   ├── chunking.py    # Chunk partitioning
│   ├── state.py       # Shared structures
│   ├── monitor.py     # Progress tracking
│   └── utils.py       # Helpers
│
├── tests/
├── pyproject.toml
└── README.md

````

---

## 🚀 Usage

### Run downloader

```bash
uv run mt-downloader <url> -t <num_threads>
````

Example:

```bash
uv run mt-downloader http://localhost:8000/test.bin -t 4
```

---

## 🧪 Local Testing Setup

Due to unreliable public servers, we recommend testing locally.

### 1. Install dev dependency

```bash
uv add --dev rangehttpserver
```

### 2. Create test file

```bash
dd if=/dev/urandom of=test.bin bs=1M count=10
```

### 3. Start server

```bash
uv run python -m RangeHTTPServer 8000
```

### 4. Run downloader

```bash
uv run mt-downloader http://localhost:8000/test.bin -t 4
```

---

## ⚠️ Known Limitations

* Uses `seek + write` (not fully atomic; acceptable for controlled environments)
* No resumable downloads yet
* Global cancellation on chunk failure (fail-fast strategy)
* Limited HTTP edge-case handling (e.g., misbehaving servers)

---

## 🔜 Future Improvements

* Replace seek-based writes with `pwrite` / `mmap`
* Thread pool with dynamic chunk scheduling
* Resume support for interrupted downloads
* Better fault tolerance (per-chunk recovery)
* Bandwidth throttling

---

## 📚 Learning Outcomes

This project demonstrates:

* Practical use of concurrency primitives
* Interaction between network I/O and file systems
* Real-world issues in distributed systems (unreliable servers, partial failures)
* Importance of correctness over “it works on my machine”

---

## 👥 Team

* Sanket Saha
* [Teammate Name]

---

## 🏫 Course

Operating Systems
M.Tech CS, Indian Statistical Institute Kolkata