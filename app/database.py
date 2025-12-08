import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "hotel_agent_db"

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Creates some sample reservations for testing
async def seed_data():
    """Seeds the database with test accounts if they don't exist."""
    accounts_collection = db["accounts"]
    
    # Test Data from User Request
    test_data = [
        {
            "account_id": "10001",
            "guest_name": "John Smith",
            "status": "Active",
            "reservations": [
                {
                    "reservation_id": 555,
                    "date": "2025-12-15",
                    "status": "Confirmed"
                }
            ]
        },
        {
            "account_id": "10002",
            "guest_name": "Jane Doe",
            "status": "Active",
            "reservations": [
                {
                    "reservation_id": 666,
                    "date": "2025-12-16",
                    "status": "Cancelled"
                }
            ]
        },
        {
            "account_id": "10003",
            "guest_name": "Test User",
            "status": "Active",
            "reservations": []
        }
    ]

    # Insert test data into the database
    for account in test_data:
        existing = await accounts_collection.find_one({"account_id": account["account_id"]})
        if not existing:
            await accounts_collection.insert_one(account)
            print(f"Seeded account: {account['account_id']}")
        else:
            print(f"Account already exists: {account['account_id']}")

# Returns the database object
async def get_db():
    return db
