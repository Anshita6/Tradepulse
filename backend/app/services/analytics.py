from sqlalchemy.orm import Session
from .. import models
from .api_service import get_live_price


async def calculate_portfolio(db: Session):
    assets = db.query(models.Asset).all()
    holdings = []

    total_portfolio_value = 0.0
    total_portfolio_invested = 0.0

    for asset in assets:
        txs = db.query(models.Transaction).filter_by(asset_id=asset.id).all()

        total_qty = 0.0
        total_spent = 0.0

        for tx in txs:
            if tx.transaction_type == "BUY":
                total_qty += tx.quantity
                total_spent += tx.quantity * tx.purchase_price
            elif tx.transaction_type == "SELL":
                total_qty -= tx.quantity

        if total_qty > 0:
            avg_buy_price = total_spent / total_qty if total_qty > 0 else 0.0
            current_price = await get_live_price(asset.symbol, asset.asset_type)
            current_value = total_qty * current_price
            pl = current_value - total_spent
            pl_pct = (pl / total_spent * 100) if total_spent > 0 else 0.0

            total_portfolio_value += current_value
            total_portfolio_invested += total_spent

            holdings.append(
                {
                    "symbol": asset.symbol,
                    "name": asset.name,
                    "asset_type": asset.asset_type,
                    "total_quantity": round(total_qty, 4),
                    "avg_buy_price": round(avg_buy_price, 2),
                    "current_price": round(current_price, 2),
                    "current_value": round(current_value, 2),
                    "total_spent": round(total_spent, 2),
                    "profit_loss": round(pl, 2),
                    "profit_loss_pct": round(pl_pct, 2),
                }
            )

    total_pl = total_portfolio_value - total_portfolio_invested
    total_pl_pct = (
        (total_pl / total_portfolio_invested * 100)
        if total_portfolio_invested > 0
        else 0.0
    )

    return {
        "total_value": round(total_portfolio_value, 2),
        "total_invested": round(total_portfolio_invested, 2),
        "total_profit_loss": round(total_pl, 2),
        "total_profit_loss_pct": round(total_pl_pct, 2),
        "holdings": holdings,
    }