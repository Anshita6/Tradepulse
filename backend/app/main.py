from typing import List
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas
from .database import Base, engine, get_db
from .services.analytics import calculate_portfolio

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Crypto & Stock Portfolio Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/transactions/", response_model=schemas.TransactionResponse)
def add_transaction(tx: schemas.TransactionCreate, db: Session = Depends(get_db)):
    asset = db.query(models.Asset).filter_by(symbol=tx.asset_symbol.upper()).first()
    if not asset:
        asset = models.Asset(
            symbol=tx.asset_symbol.upper(),
            name=tx.asset_name,
            asset_type=tx.asset_type,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

    db_tx = models.Transaction(
        asset_id=asset.id,
        transaction_type=tx.transaction_type,
        quantity=tx.quantity,
        purchase_price=tx.purchase_price,
    )
    db.add(db_tx)
    db.commit()
    db.refresh(db_tx)
    return db_tx


@app.get("/api/portfolio/summary", response_model=schemas.PortfolioSummary)
async def get_portfolio_summary(db: Session = Depends(get_db)):
    return await calculate_portfolio(db)