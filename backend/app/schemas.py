from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class AssetBase(BaseModel):
    symbol: str
    name: str
    asset_type: str


class AssetCreate(AssetBase):
    pass


class AssetResponse(AssetBase):
    id: int

    class Config:
        from_attributes = True


class TransactionCreate(BaseModel):
    asset_symbol: str
    asset_name: str
    asset_type: str
    transaction_type: str
    quantity: float
    purchase_price: float


class TransactionResponse(BaseModel):
    id: int
    asset_id: int
    transaction_type: str
    quantity: float
    purchase_price: float
    timestamp: datetime

    class Config:
        from_attributes = True


class HoldingSummary(BaseModel):
    symbol: str
    name: str
    asset_type: str
    total_quantity: float
    avg_buy_price: float
    current_price: float
    current_value: float
    total_spent: float
    profit_loss: float
    profit_loss_pct: float


class PortfolioSummary(BaseModel):
    total_value: float
    total_invested: float
    total_profit_loss: float
    total_profit_loss_pct: float
    holdings: List[HoldingSummary]