# UK Sales Assistant Chatbot (Sales Info V2 standalone)

A high-performance, dynamic Text-to-SQL chatbot utilizing **Llama 3.3 70B** on OpenRouter to convert natural language business queries into safe, executable PostgreSQL queries and return deep analytical reasoning. 

Specifically configured and isolated for the consolidated **`Sales Info V2`** sales records (`sales_data` table).

---

## ✨ Key Custom Features

### 1. Corporate Financial Year (July 1 – June 30)
The chatbot operates on the custom financial year calendar boundaries:
* **Financial Year Definition**: runs from July 1st of any year to June 30th of the next year.
* **PostgreSQL Date Formula**: all annual filters, aggregations, and YoY growth calculations are computed at database-level using:
  ```sql
  EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month'))
  ```
  This returns the starting calendar year of the financial year (e.g. `2024` maps to **FY 2024/25** and `2025` maps to **FY 2025/26**).
* **Relative Date Bounds**: treats `'2026-05-22'` as "today" (anchored to the dataset), mapping it to the active **FY 2025/26** year.

### 2. Rounded EDP Currency System
* **Rounded Figures**: to maintain clean corporate reporting, all displayed revenue/monetary figures are rounded to the nearest whole integer (no decimals).
* **Currency Symbol**: all figures in both UI tables and AI summaries are formatted with **`EDP `** as the standard currency prefix (e.g. `EDP 150,000`).

### 3. Safety-First AST Whitelisting Validation
Equipped with an advanced SQL safety parser (`sqlglot`) to prevent malicious injections:
* **Strict Whitelisting**: only physical database tables whitelisted in the pipeline (`sales_data`) can be read.
* **CTE Recognition**: automatically filters out local virtual CTE aliases defined in `WITH` blocks (e.g., `current_period`, `sales_growth`), allowing complex growth subqueries to execute safely.

### 4. Schema & Greetings Conversational Bypasses
To prevent standard greetings and metadata schema requests from triggering safety blocks or failing syntax errors:
* **Intelligent Routing**: intercepts prompts like `"hi"`, `"who are you"`, or `"what is the schema"` before they hit the SQL translation engine.
* **Rich Summaries**: generates a beautiful, rich Markdown table description of the table columns and dynamic category classifications (`Insulation`, `Cladding`, `MMC`) directly from the LLM.

---

## 📂 Directory Layout

```text
UK_SALES_BOT_1/
  ├── app/                  # FastAPI Backend API
  ├── text_to_sql/          # Text-to-SQL Pipeline, Validation, & Formatting
  ├── data/                 # Consolidated database spreadsheet: "Sales Info V2 .xlsx"
  ├── frontend/             # Standalone React + Vite UI (Light Theme & EDP currency)
  │     └── src/
  │           ├── App.jsx   # Premium Light-Theme Analytics Chat Dashboard
  │           ├── App.css   # HSL Slate/Indigo/Violet CSS styles
  │           └── main.jsx  # Main entrypoint
  ├── docker-compose.yml    # PostgreSQL container configurations
  ├── requirements.txt      # Python dependencies
  └── .env                  # OpenRouter API keys and connection URLs
```

---

## 🚀 Local Execution Steps

Follow these PowerShell commands to spin up the local chatbot environment.

### 1. Set up the Python Environment
Open a PowerShell terminal and install backend dependencies:
```powershell
cd d:\UK_SALES_BOT_1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Start PostgreSQL Container
Spin up the database using Docker:
```powershell
docker compose up -d
```
*(Ensure Docker Desktop is open and actively running on your Windows machine).*

### 3. Launch the Backend API Server
Start the Uvicorn web server within your active virtual environment:
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
*(The backend API is served at `http://127.0.0.1:8000`).*

### 4. Populate Database (First-time Ingestion)
Open a **new** PowerShell window and trigger the Excel loading endpoint:
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/admin/ingest-excel
```
*(Loads all 2,136 Excel rows from `Sales Info V2 .xlsx` into PostgreSQL).*

### 5. Launch the Frontend React UI
Open a **new** PowerShell window, navigate to the frontend, install node packages, and start the development server:
```powershell
cd d:\UK_SALES_BOT_1\frontend
npm install
npm run dev
```

### 6. Open in Browser
Navigate your browser to the local dev URL:
👉 **`http://localhost:5173/`**
