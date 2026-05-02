"""Synthetic stress-test CSVs for Shadow (chargeback, ATO, bot, ring, cross-case). Writes into this folder."""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

OUT = Path(__file__).resolve().parent

fake = Faker()
Faker.seed(2026)
random.seed(2026)


def generate_stress_datasets() -> None:
    print("Generating stress test datasets into", OUT)

    # 1. Chargeback stress: "The Seasoned Professional"
    cb_data: list[dict] = []
    uid = "TRUSTED_USER_001"
    for i in range(20):
        dt = datetime(2025, 6, 1) + timedelta(days=i * 5)
        cb_data.append(
            {
                "tx_id": f"LEGIT_{i}",
                "user_id": uid,
                "amount": random.randint(10, 50),
                "status": "completed",
                "ip": "1.1.1.1",
                "device": "iPhone_14_Pro",
                "date": dt,
            }
        )
    cb_data.append(
        {
            "tx_id": "DISPUTE_TRAP",
            "user_id": uid,
            "amount": 3500.00,
            "status": "disputed",
            "ip": "1.1.1.1",
            "device": "iPhone_14_Pro",
            "date": datetime(2026, 1, 15),
            "reason": "Unrecognized Transaction",
        }
    )
    pd.DataFrame(cb_data).to_csv(OUT / "stress_chargeback_seasoning.csv", index=False)

    # 2. ATO stress: "The Legitimate Jetsetter"
    ato_data = [
        {"session": "S1", "user": "exec_88", "ip": "100.1.1.1", "city": "New York", "time": "2026-05-01 10:00:00"},
        {"session": "S2", "user": "exec_88", "ip": "200.2.2.2", "city": "London", "time": "2026-05-01 12:00:00"},
    ]
    context_data = [{"user": "exec_88", "subject": "Your Flight to London is Confirmed", "date": "2026-04-28"}]
    pd.DataFrame(ato_data).to_csv(OUT / "stress_ato_travel.csv", index=False)
    pd.DataFrame(context_data).to_csv(OUT / "ato_mock_email_context.csv", index=False)

    # 3. Bot stress: "The Humanoid Low-and-Slow"
    bot_data: list[dict] = []
    shared_canvas = "canvas_hash_999_xyz"
    for i in range(100):
        bot_data.append(
            {
                "acc_id": f"HUMANOID_{i}",
                "name": fake.name(),
                "ip": fake.ipv4(),
                "created_at": fake.date_time_between(start_date="-3d", end_date="now"),
                "canvas_fingerprint": shared_canvas,
                "browser": "Chrome 120.0.0",
            }
        )
    pd.DataFrame(bot_data).to_csv(OUT / "stress_bot_humanoid.csv", index=False)

    # 4. Fraud ring stress: "The Snowflake Multi-Hop"
    ring_data: list[dict] = []
    bridge_acc = "NEUTRAL_EXCHANGE_HUB"
    for i in range(10):
        mule = f"MULE_{i}"
        ring_data.append({"from": mule, "to": bridge_acc, "amt": 499.00, "type": "p2p"})
    ring_data.append({"from": bridge_acc, "to": "KINGPIN_CASH_OUT", "amt": 4990.00, "type": "wire"})
    pd.DataFrame(ring_data).to_csv(OUT / "stress_ring_multihop.csv", index=False)

    # 5. Cross-investigation: "The Recidivist Return"
    file_old = [{"user_id": "U_RECID", "event": "ACCOUNT_BREACHED", "date": "2025-10-01"}]
    file_new = [{"user_id": "U_RECID", "event": "LARGE_TRANSFER_OUT", "date": "2026-05-02"}]
    pd.DataFrame(file_old).to_csv(OUT / "history_oct_2025.csv", index=False)
    pd.DataFrame(file_new).to_csv(OUT / "current_may_2026.csv", index=False)

    print("Done. CSV files written to", OUT)


if __name__ == "__main__":
    generate_stress_datasets()
