# mt-downloader

Multi-threaded chunked file downloader implemented in Python as part of our Operating Systems course project.

This project implements parallel file downloading using multiple threads. Each thread downloads a disjoint byte range of a file using HTTP Range requests and writes directly to the correct offset in the output file.


## 🛠 Requirements

- Python 3.12+
- uv (Python package manager)



## ⚙️ Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/Sanket-Saha-768/mt-downloader.git
cd mt-downloader
```



### 2. Install uv (if not installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify:

```bash
uv --version
```



### 3. Install project dependencies

```bash
uv sync
```



## 🧪 Local Testing Setup

Public servers are unreliable for Range requests, so we test using a local HTTP server.

### 1. Create a test file

```bash
dd if=/dev/urandom of=test.bin bs=1M count=10
```



### 2. Start Range-supporting HTTP server (Terminal 1)

```bash
uv run python -m RangeHTTPServer 8000
```

Server will run at:

```
http://localhost:8000
```



### 3. Run downloader (Terminal 2)

```bash
uv run mt-downloader http://localhost:8000/test.bin -t 4
```



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
│   └── utils.py       # Helper functions
│
├── tests/
├── pyproject.toml
└── README.md
```



## ▶️ Usage

```bash
uv run mt-downloader <URL> -t <num_threads>
```

Example:

```bash
uv run mt-downloader http://localhost:8000/test.bin -t 4
```



## 🧠 Implementation Details

* Multi-threaded downloading using Python `threading`
* HTTP Range requests (`bytes=start-end`)
* Shared state protected via locks
* Cooperative cancellation using events
* Chunk-based partitioning of file
* Retry mechanism with exponential backoff
* HEAD → Range fallback for server probing
* File pre-allocation and direct offset writes

## 👨‍🏫 Instructor

* Prof. Ansuman Banerjee

## 👥 Team

* Sanket Saha - CS2425
* Aniket Das - CS24



## 🏫 Course

Operating Systems
M.Tech CS, Indian Statistical Institute Kolkata
