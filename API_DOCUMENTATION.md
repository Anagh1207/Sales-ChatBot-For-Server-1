# 🔌 API Documentation: Sales Chatbot V2

This document provides all the information needed for frontend engineers and UI designers to integrate the chatbot into custom applications, dashboards, or external websites.

The API endpoint accepts natural language queries, validates them, executes PostgreSQL queries, formats financial values under the corporate rules (**Financial Year starting July 1st, rounded whole numbers, and the `EDP` currency symbol**), and returns structured data alongside Markdown answers.

---

## 🌐 Endpoint Details

* **Method**: `POST`
* **Content-Type**: `application/json`
* **Base URL**: `https://sales-chat-bot-for-server-1.vercel.app` (Production) or `http://127.0.0.1:8000` (Local)
* **Endpoint Path**: `/api/chat`

---

## 📥 Request Body

The request payload is a JSON object with two fields:

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `message` | `string` | **Yes** | The user's query or message (e.g., `"Show me the highest sales growth in the last 12 months"`). |
| `history` | `array` | No | List of prior messages in the conversation session, used to carry over conversation context. |

### Message Object Structure in `history`
Each turn in the `history` array must be an object containing:
* `role` (`string`): `"user"` or `"assistant"`
* `content` (`string`): The text content of the message.

### Request Example
```json
{
  "message": "Sales difference between FY 2024/25 and FY 2025/26, and reason for it",
  "history": [
    {
      "role": "user",
      "content": "Hi, who are you?"
    },
    {
      "role": "assistant",
      "content": "Hello! I am your Sales V2 AI Agent..."
    }
  ]
}
```

---

## 📤 Response Body

The response is a JSON object designed for simple frontend integration:

| Field | Type | Description |
| :--- | :--- | :--- |
| `answer` | `string` | The markdown explanation and analytical reasoning containing formatted EDP whole-number values. |
| `sql_query` | `string` | The executed SQL query (empty if chitchat or metadata question). |
| `data_table` | `object` \| `null` | Contains `columns` (array of strings) and `rows` (array of arrays) if tabular data is fetched. |
| `has_data` | `boolean` | Flag indicating if a tabular dataset is included. |
| `error` | `string` \| `null` | Error details if a validation safety block or database execution error occurred. |

### Response Example
```json
{
  "answer": "### Sales Analysis\n\nThe total sales for **FY 2024/25** (July 1st, 2024 to June 30th, 2025) were **EDP 3,690,415**.\nFor **FY 2025/26** (July 1st, 2025 to June 30th, 2026), they grew to **EDP 5,385,822**.\nThis represents a solid year-over-year sales growth of **45.9%**.\n\n### Key Drivers\n1. **Operations Timeline**: The data for FY 2024/25 covers only a 6-month period (starting July 2024), whereas the active FY 2025/26 spans a full year.",
  "sql_query": "SELECT EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month')) AS financial_year, SUM(contract_price) AS total_sales FROM sales_data WHERE EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month')) IN (2024, 2025) GROUP BY EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month')) ORDER BY financial_year;",
  "data_table": {
    "columns": ["financial_year", "total_sales"],
    "rows": [
      [2024, 3690414.75],
      [2025, 5385821.57]
    ]
  },
  "has_data": true,
  "error": null
}
```

---

## 💻 Integration Examples

### JavaScript / Fetch
```javascript
const API_URL = "https://sales-chat-bot-for-server-1.vercel.app/api/chat";

async function sendChatQuery(messageText, chatHistory = []) {
  try {
    const response = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        message: messageText,
        history: chatHistory
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP Error: ${response.status}`);
    }

    const data = await response.json();
    
    // Render Markdown Answer
    console.log("Markdown Answer:", data.answer);
    
    // Render SQL Query Code Block
    if (data.sql_query) {
      console.log("SQL:", data.sql_query);
    }
    
    // Render Table
    if (data.has_data) {
      console.log("Columns:", data.data_table.columns);
      console.log("Rows:", data.data_table.rows);
    }
  } catch (error) {
    console.error("API Call Failed:", error);
  }
}
```

### Python / Requests
```python
import requests

API_URL = "https://sales-chat-bot-for-server-1.vercel.app/api/chat"

payload = {
    "message": "Which product types perform best in retrofit projects?",
    "history": []
}

response = requests.post(API_URL, json=payload)
if response.status_code == 200:
    data = response.json()
    print("Answer:", data["answer"])
    if data["has_data"]:
        print("Data columns:", data["data_table"]["columns"])
else:
    print("Error:", response.status_code, response.text)
```
