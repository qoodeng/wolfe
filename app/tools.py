"""
Synchronous tool implementations for Pipecat.
Uses PyMongo (sync) instead of Motor (async) to avoid event loop conflicts.
"""

import os
from datetime import datetime
from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = "hotel_agent_db"

# Synchronous MongoDB client
_client = None

def get_db():
    """Get database connection (lazy initialization)."""
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URL)
    return _client[DB_NAME]


async def check_account_status(account_id: str) -> bool:
    """Checks if the account_id exists and is active in the database."""
    db = get_db()
    account = db["accounts"].find_one({"account_id": account_id, "status": "Active"})
    return account is not None


async def get_guest_reservation(account_id: str, search_name: str):
    """Retrieves booking details for a verified account."""
    db = get_db()
    account = db["accounts"].find_one({"account_id": account_id})
    if not account:
        return "Account not found."
    
    reservations = account.get("reservations", [])
    if not reservations:
        return f"No reservations found for {search_name}."
    
    return str(reservations)


async def cancel_guest_reservation(account_id: str, reservation_id: int):
    """Marks a booking as canceled."""
    db = get_db()
    result = db["accounts"].update_one(
        {"account_id": account_id, "reservations.reservation_id": reservation_id},
        {"$set": {"reservations.$.status": "Cancelled"}}
    )
    
    if result.modified_count > 0:
        return f"Reservation {reservation_id} has been cancelled."
    return f"Reservation {reservation_id} not found or already cancelled."


async def make_new_reservation(account_id: str, guest_name: str, check_in_date: str, room_type: str):
    """Creates a new reservation."""
    db = get_db()
    account = db["accounts"].find_one({"account_id": account_id})
    if not account:
        return "Account not found."
    
    # Generate a simple mock reservation ID
    reservation_id = int(datetime.utcnow().timestamp())
    
    new_reservation = {
        "reservation_id": reservation_id,
        "date": check_in_date,
        "status": "Confirmed",
        "room_type": room_type
    }
    
    db["accounts"].update_one(
        {"account_id": account_id},
        {"$push": {"reservations": new_reservation}}
    )
    
    return f"New reservation confirmed for {guest_name} on {check_in_date}. Reservation ID: {reservation_id}"


async def edit_guest_reservation(
    account_id: str, 
    reservation_id: int, 
    new_check_in_date: str = None, # Both are safe because we immediately check for None after
    new_room_type: str = None
):
    """Edits an existing reservation's date and/or room type."""
    db = get_db()
    
    # Build the update document dynamically
    update_fields = {}
    if new_check_in_date:
        update_fields["reservations.$.date"] = new_check_in_date
    if new_room_type:
        update_fields["reservations.$.room_type"] = new_room_type
    
    if not update_fields:
        return "No changes provided. Specify new_check_in_date and/or new_room_type."
    
    result = db["accounts"].update_one(
        {"account_id": account_id, "reservations.reservation_id": reservation_id},
        {"$set": update_fields}
    )
    
    if result.modified_count > 0:
        changes = []
        if new_check_in_date:
            changes.append(f"date to {new_check_in_date}")
        if new_room_type:
            changes.append(f"room type to {new_room_type}")
        return f"Reservation {reservation_id} updated: {', '.join(changes)}."
    
    return f"Reservation {reservation_id} not found."
