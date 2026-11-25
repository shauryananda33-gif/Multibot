-- Defense in depth for the private application schema.
-- No Data API policies are added: browser roles must remain unable to access it.
ALTER TABLE multibot.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.signal_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.scan_error_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.market_data_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.forex_calendar_week_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.forex_calendar_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.multibot_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.app_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE multibot.runtime_leases ENABLE ROW LEVEL SECURITY;

-- Event triggers execute their function as the function owner. Do not allow
-- untrusted API roles to invoke this SECURITY DEFINER function directly.
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC, anon, authenticated;
