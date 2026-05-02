import pandas as pd
import random
from faker import Faker
from datetime import datetime, timedelta
import os

fake = Faker()
Faker.seed(42)
random.seed(42)

# Ensure data directory exists
os.makedirs('../workspace/data', exist_ok=True)

print("Starting Synthetic Fraud Data Generation...")

# ==========================================
# 1. CHARGEBACK & FRIENDLY FRAUD DATASET
# ==========================================
def generate_chargeback_data(num_records=5000):
    print("Generating Chargeback dataset...")
    data = []
    for _ in range(num_records):
        user_id = fake.uuid4()[:8]
        tx_date = fake.date_time_between(start_date='-60d', end_date='-10d')
        
        # 5% chance of being a dispute
        is_disputed = random.random() < 0.05
        dispute_date = tx_date + timedelta(days=random.randint(2, 8)) if is_disputed else None
        
        # INJECT FRIENDLY FRAUD: User disputes, but logs in AFTER the dispute from the exact same IP
        is_friendly_fraud = is_disputed and random.random() < 0.4
        ip_address = fake.ipv4()
        device_id = fake.sha256()[:12]
        
        if is_friendly_fraud:
            last_login = dispute_date + timedelta(days=1) # Logged in after dispute
            login_ip = ip_address # Matched IP (Caught red-handed)
        else:
            last_login = tx_date + timedelta(hours=random.randint(1, 24))
            login_ip = fake.ipv4() if is_disputed else ip_address

        data.append({
            "transaction_id": fake.uuid4(),
            "user_id": user_id,
            "amount_usd": round(random.uniform(10, 1500), 2),
            "ip_address": ip_address,
            "device_id": device_id,
            "billing_zip": fake.zipcode(),
            "shipping_zip": fake.zipcode() if not is_friendly_fraud else "MATCH", # Mismatched zips are common in true fraud
            "transaction_date": tx_date,
            "dispute_date": dispute_date,
            "last_login_date": last_login,
            "last_login_ip": login_ip
        })
    pd.DataFrame(data).to_csv('../workspace/data/chargebacks_demo.csv', index=False)


# ==========================================
# 2. ATO (ACCOUNT TAKEOVER) DATASET
# ==========================================
def generate_ato_data(num_sessions=10000):
    print("Generating ATO (Account Takeover) dataset...")
    data = []
    # Create 100 baseline users
    users = [{"user_id": f"USR_{i}", "home_ip": fake.ipv4(), "home_lat": fake.latitude(), "home_lon": fake.longitude(), "device": fake.user_agent()} for i in range(100)]
    
    for _ in range(num_sessions):
        user = random.choice(users)
        timestamp = fake.date_time_between(start_date='-30d', end_date='now')
        
        # INJECT ATO: 2% chance of session hijacking (Impossible travel + password change)
        is_ato = random.random() < 0.02
        
        if is_ato:
            # Hacker Session (Different IP, wildly different location, changed password)
            lat, lon = fake.latitude(), fake.longitude() # New random location
            action = "PASSWORD_CHANGE"
            device = fake.user_agent() # Different device
            ip = fake.ipv4()
        else:
            # Normal Session
            lat, lon = user['home_lat'], user['home_lon']
            action = random.choice(["LOGIN", "VIEW_ITEM", "CHECKOUT"])
            device = user['device']
            ip = user['home_ip']

        data.append({
            "session_id": fake.uuid4()[:8],
            "user_id": user["user_id"],
            "timestamp": timestamp,
            "action": action,
            "ip_address": ip,
            "latitude": lat,
            "longitude": lon,
            "user_agent": device
        })
    pd.DataFrame(data).to_csv('../workspace/data/ato_sessions_demo.csv', index=False)


# ==========================================
# 3. BOT CLUSTER DATASET
# ==========================================
def generate_bot_data():
    print("Generating Bot Cluster dataset...")
    data = []
    base_time = datetime.now() - timedelta(days=5)
    
    # 1. Normal Users (Scattered over 5 days)
    for _ in range(2000):
        data.append({
            "account_id": fake.uuid4()[:8],
            "username": fake.user_name(),
            "email": fake.email(),
            "created_at": fake.date_time_between(start_date='-5d', end_date='now'),
            "ip_address": fake.ipv4(),
            "user_agent": fake.user_agent()
        })
        
    # 2. INJECT BOT CLUSTER (500 accounts created within 2 minutes sharing 1 IP Subnet)
    print(" -> Injecting Bot Burst attack...")
    bot_ip_base = "192.168.44."
    bot_agent = "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:40.0) Gecko/20100101 Firefox/40.1" # Old user agent
    
    for i in range(500):
        burst_time = base_time + timedelta(seconds=(i * 0.5)) # Created half a second apart
        data.append({
            "account_id": f"BOT_{i}",
            "username": f"promo_abuser_{i}{random.randint(100,999)}",
            "email": f"j.o.h.n.s.m.i.t.h+{i}@gmail.com", # Gmail dot trick
            "created_at": burst_time,
            "ip_address": f"{bot_ip_base}{random.randint(1, 255)}",
            "user_agent": bot_agent
        })
        
    pd.DataFrame(data).to_csv('../workspace/data/bot_registrations_demo.csv', index=False)


# ==========================================
# 4. FRAUD RING / COLLUSION DATASET (Graph Data)
# ==========================================
def generate_fraud_ring_data():
    print("Generating Fraud Ring / Money Laundering dataset...")
    data = []
    
    # Create normal random P2P transactions
    users = [fake.uuid4()[:6] for _ in range(500)]
    for _ in range(3000):
        sender, receiver = random.sample(users, 2)
        data.append({
            "tx_id": fake.uuid4(),
            "timestamp": fake.date_time_between(start_date='-10d', end_date='now'),
            "sender_id": sender,
            "receiver_id": receiver,
            "amount": round(random.uniform(5, 50), 2),
            "sender_device": fake.sha256()[:8],
            "receiver_device": fake.sha256()[:8]
        })
        
    # INJECT FRAUD RING: 5 Accounts laundering money in a circle sharing 1 Device ID
    print(" -> Injecting Circular Fraud Ring...")
    ring_members = ["RING_A", "RING_B", "RING_C", "RING_D", "RING_E"]
    shared_device = "BAD_DEVICE_999"
    
    # A -> B -> C -> D -> E -> A
    for i in range(50):
        sender = ring_members[i % 5]
        receiver = ring_members[(i + 1) % 5]
        data.append({
            "tx_id": f"LAUNDER_{i}",
            "timestamp": fake.date_time_between(start_date='-2d', end_date='now'),
            "sender_id": sender,
            "receiver_id": receiver,
            "amount": round(random.uniform(4900, 4999), 2), # Just under $5k reporting threshold
            "sender_device": shared_device, # THE SMOKING GUN
            "receiver_device": shared_device  # THE SMOKING GUN
        })
        
    pd.DataFrame(data).to_csv('../workspace/data/p2p_transfers_demo.csv', index=False)

# Run Generators
if __name__ == "__main__":
    generate_chargeback_data()
    generate_ato_data()
    generate_bot_data()
    generate_fraud_ring_data()
    print("Done! Demo files are ready in /workspace/data/")
