from telegram import TelegramMessage
import notification_service


class _AuditFailDatabase:
    def __init__(self):
        self.calls = 0

    def record_delivery(self, *args, **kwargs):
        self.calls += 1
        raise RuntimeError("audit unavailable")


def test_telegram_send_survives_delivery_audit_failure(monkeypatch):
    db = _AuditFailDatabase()
    service = notification_service.NotificationService(db)
    sent = []

    monkeypatch.setattr(
        notification_service,
        "send_message",
        lambda message, config: sent.append(message.text),
    )
    monkeypatch.setattr(
        service,
        "_config",
        lambda: object(),
    )

    result = service.deliver(
        signal_id="sig-1",
        message=TelegramMessage("MSG-TEST-V1", "hello"),
    )

    assert result is True
    assert sent == ["hello"]
    assert db.calls >= 1


def test_reminders_and_trade_closed_deliver_for_delivered_signal(monkeypatch):
    class _DeliveredDb:
        def __init__(self):
            self.rows = []

        def signal_event(self, signal_id):
            return {"signal_id": signal_id, "reason": "BULLISH", "pipeline_status": "DELIVERED"}

        def record_delivery(self, signal_id, **kwargs):
            self.rows.append({"signal_id": signal_id, **kwargs})

    db = _DeliveredDb()
    service = notification_service.NotificationService(db)
    service._config_value = object()
    sent = []
    service.set_telegram_send(lambda message, config: sent.append(message.text) or True)

    assert service.deliver(signal_id="sig-1", message=TelegramMessage("MSG-SIGNAL-BUY-V1", "dup"), kind="SIGNAL") is False
    assert sent == []
    assert service.deliver(signal_id="sig-1", message=TelegramMessage("MSG-REMINDER-V1", "remind"), kind="REMINDER") is True
    assert service.deliver(signal_id="sig-1", message=TelegramMessage("MSG-TRADE-CLOSED-V1", "closed"), kind="TRADE_CLOSED") is True
    assert sent == ["remind", "closed"]
