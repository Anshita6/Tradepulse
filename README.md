# TradePulse

A crypto and stock portfolio tracker. Log your trades, view your holdings, and follow your portfolio's performance over time.

**Live demo:** https://tradepulse-r2hj.onrender.com
**API:** https://tradepulse-api.onrender.com/docs

## Features

- Dashboard with a portfolio overview
- Holdings page showing current positions
- Transactions page with a full trade history
- Add buy/sell trades through a form
- Portfolio history tracking
- REST API with auto-generated docs (Swagger)

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Frontend | HTML, CSS, JavaScript, jQuery |
| Data | SQLite |
| Deployment | Render (backend), Netlify (frontend) |

## Project Structure

```
crypto-stock-tracker/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   └── services/
│   │       └── api_service.py
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── dashboard.html
    ├── holdings.html
    ├── transactions.html
    └── js/main.js
```

## Getting Started

### Prerequisites
- Python 3.10+
- Git

### Run the backend

```bash
git clone https://github.com/YOUR_USERNAME/tradepulse.git
cd tradepulse/backend

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs at http://127.0.0.1:8000 and the docs are at http://127.0.0.1:8000/docs.

### Run the frontend

Open `frontend/index.html` in your browser, or use the VS Code **Live Server** extension.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/holdings` | List current holdings |
| GET | `/api/history` | Portfolio history |

## Deployment

- **Backend:** Render Web Service (root directory `backend`)
- **Frontend:** Netlify (base directory `frontend`)

## Future Improvements

- User authentication
- Live price updates
- Charts for profit/loss over time

## Author

Your Name · [GitHub](https://github.com/YOUR_USERNAME)
