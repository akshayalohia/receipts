"""Settings read from the environment (see deploy/.env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REFUND_CAP_CENTS = 2000
FILAMENT_CENTS_PER_GRAM = 2          # PLA ~$0.02/g
MESHY_COST_CENTS = 40                # per generate_mesh call (~$0.40)
WHOP_FEE_BPS = 270                   # 2.7 %
WHOP_FEE_FIXED_CENTS = 30            # + $0.30


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    mock: bool = True
    data_dir: Path = Path("./data")
    public_base_url: str = ""
    app_shared_secret: str = ""
    admin_key: str = ""
    whop_api_key: str = ""
    whop_company_id: str = ""
    whop_product_id: str = ""
    whop_webhook_secret: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    hermes_api_base: str = "http://hermes:8642"
    hermes_api_key: str = ""
    mcp_token: str = ""
    printer_poll_s: float = 5.0
    snapshot_every_s: float = 150.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mock=_env("FACTORY_MOCK", "1") not in ("0", "false", "False", ""),
            data_dir=Path(_env("FACTORY_DATA", "./data")),
            public_base_url=_env("PUBLIC_BASE_URL").rstrip("/"),
            app_shared_secret=_env("APP_SHARED_SECRET"),
            admin_key=_env("ADMIN_KEY"),
            whop_api_key=_env("WHOP_API_KEY"),
            whop_company_id=_env("WHOP_COMPANY_ID"),
            whop_product_id=_env("WHOP_PRODUCT_ID"),
            whop_webhook_secret=_env("WHOP_WEBHOOK_SECRET"),
            elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
            elevenlabs_agent_id=_env("ELEVENLABS_AGENT_ID"),
            hermes_api_base=_env("HERMES_API_BASE", "http://hermes:8642").rstrip("/"),
            hermes_api_key=_env("HERMES_API_KEY"),
            mcp_token=_env("MCP_TOKEN"),
        )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite"

    @property
    def policy_path(self) -> Path:
        return self.data_dir / "pricing_policy.json"

    def order_dir(self, order_id: str) -> Path:
        return self.data_dir / "orders" / order_id

    def upload_dir(self, order_id: str) -> Path:
        return self.data_dir / "uploads" / order_id
