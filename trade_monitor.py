"""Universal paper-trade monitor for every strategy."""
from __future__ import annotations
import logging
import pandas as pd
from config import ACCOUNT_SIZES,LIVE_ASSET_MAP,account_names
from db import DatabaseManager
from trading import AccountState,PaperTrade,TradePlan,close_trade,realized_pnl
from notification_service import NotificationService
from telegram import trade_closed_message

logger=logging.getLogger("multibot2.trade_monitor")

class TradeMonitor:
    def __init__(self,*,database:DatabaseManager,price_lookup,accounts:dict,account_lock=None,notifier=None):
        from threading import RLock
        self.database=database; self.price_lookup=price_lookup; self.accounts=accounts; self.account_lock=account_lock or RLock(); self.notifier=notifier or NotificationService(database)

    def _hit(self,row,price):
        side=row.get("type","BUY")
        if side=="BUY":
            if price<=float(row["sl"]): return "STOP_LOSS"
            if price>=float(row["tp"]): return "TAKE_PROFIT"
        else:
            if price>=float(row["sl"]): return "STOP_LOSS"
            if price<=float(row["tp"]): return "TAKE_PROFIT"
        return None

    def _trade(self,row):
        ts=pd.Timestamp(row["signal_ts"])
        plan=TradePlan(row.get("strategy",""),row["type"],ts,float(row["entry"]),float(row["sl"]),float(row["tp"]),timeframe=row.get("timeframe",""),strategy_version=row.get("strategy_version",""),metadata=row.get("metadata"),trailing_policy=row.get("trailing_policy"),fx_rate=float(row.get("fx_rate",1.0)))
        return PaperTrade(plan=plan,account=row["account"],quantity=float(row["qty"]))

    def monitor_once(self,*,now=None):
        current=pd.Timestamp.now(tz="Asia/Kolkata") if now is None else pd.Timestamp(now)
        if current.tzinfo is None: raise ValueError("now must be timezone-aware")
        closed=[]; errors=[]
        open_rows = self.database.load_trades("OPEN")
        for row in open_rows:
            symbol=row.get("symbol")
            try:
                price=self.price_lookup(symbol)
                if price is None: errors.append({"id":row.get("id"),"symbol":symbol,"reason":"PRICE_UNAVAILABLE"}); continue
                reason=self._hit(row,float(price))
                if not reason: continue
                trade=self._trade(row)
                # Execution contract: once SL/TP is crossed, settle at the defined
                # plan level. This prevents monitor polling overshoots from creating
                # P&L outside the strategy risk/reward contract.
                exit_price = float(trade.plan.stop_loss if reason == "STOP_LOSS" else trade.plan.take_profit)
                closed_trade=close_trade(trade,exit_price=exit_price,exit_timestamp=current,exit_reason=reason)
                with self.account_lock:
                    pnl=realized_pnl(trade,exit_price=exit_price)
                    payload=dict(row); payload.update({"status":"CLOSED","exit_price":exit_price,"exit_reason":reason,"closed_at":current.isoformat(),"pnl":pnl,"result":"WIN" if pnl>=0 else "LOSS"})
                    opened_ts = pd.Timestamp(row.get("opened_at") or row.get("signal_ts"))
                    if opened_ts.tzinfo is None:
                        opened_ts = opened_ts.tz_localize("Asia/Kolkata")
                    closed_once, account_row = self.database.close_trade_and_settle_account(
                        row["id"], payload, current.isoformat(), account_name=row["account"],
                        pnl=pnl, planned_risk=trade.planned_risk,
                        reset_date=current.tz_convert("Asia/Kolkata").date().isoformat(),
                        reservation_date=opened_ts.tz_convert("Asia/Kolkata").date().isoformat(),
                    )
                    if not closed_once:
                        # Another monitor pass already closed this trade. The
                        # conditional status transition guarantees no second P&L.
                        continue
                    if account_row is None:
                        raise RuntimeError(f"Account {row['account']!r} missing after trade settlement")
                    updated=AccountState(
                        row["account"], float(account_row["starting_balance"]),
                        float(account_row["balance"]), float(account_row["planned_risk_used"]),
                        int(account_row["trades_today"]),
                    )
                    self.accounts[row["account"]]=updated
                signal_id=str(row.get("signal_id") or row["id"])
                message=trade_closed_message(closed_trade,exit_price,pnl,updated.balance,trade.plan.side=="BUY",reason=="TAKE_PROFIT")
                self.notifier.deliver(signal_id=signal_id,message=message,kind="TRADE_CLOSED",metadata={"trade_id":row["id"],"reason":reason,"pnl":pnl})
                closed.append(payload)
            except Exception as exc:
                logger.exception("Trade monitor failed for %s",row.get("id")); errors.append({"id":row.get("id"),"symbol":symbol,"reason":str(exc)})
        remaining = len(open_rows) - len(closed) if not errors else len(self.database.load_trades("OPEN"))
        return {"status":"OK" if not errors else "PARTIAL","closed":closed,"errors":errors,"active_trades":max(0, remaining),"timestamp":current.isoformat()}
