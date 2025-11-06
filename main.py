import os
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models for requests
class MemberCreate(BaseModel):
    name: str

class AttendanceScan(BaseModel):
    token: str
    action: str  # "IN" or "OUT"

# Utility: validate Mongo ObjectId

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid member id")


@app.get("/")
def read_root():
    return {"message": "Attendance Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# Members Endpoints
@app.post("/api/members")
def create_member(payload: MemberCreate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = {
        "name": payload.name,
        "present": False,
        "last_in": None,
        "last_out": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    res = db["member"].insert_one(doc)
    doc["_id"] = str(res.inserted_id)
    return doc


@app.get("/api/members")
def list_members():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    members = list(db["member"].find())
    for m in members:
        m["_id"] = str(m["_id"])
        # compute current status from presence flag and times
        m["status"] = "Present" if m.get("present") else "Absent"
    return members


# QR token generation (time-bound)
# We will generate a short-lived token by hashing member_id + action + current time slice
import hmac
import hashlib
import base64

SECRET = os.getenv("QR_SECRET", "dev-secret")
TOKEN_WINDOW_SECONDS = 10


def generate_token(member_id: str, action: str, now: Optional[datetime] = None) -> str:
    if action not in ("IN", "OUT"):
        raise HTTPException(status_code=400, detail="Invalid action")
    now = now or datetime.now(timezone.utc)
    # time slice index
    ts = int(now.timestamp()) // TOKEN_WINDOW_SECONDS
    msg = f"{member_id}:{action}:{ts}".encode()
    sig = hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return token


def verify_token(member_id: str, action: str, token: str) -> bool:
    now = datetime.now(timezone.utc)
    current_slice = int(now.timestamp()) // TOKEN_WINDOW_SECONDS
    for ts in (current_slice, current_slice - 1):  # allow small clock skew
        msg = f"{member_id}:{action}:{ts}".encode()
        sig = hmac.new(SECRET.encode(), msg, hashlib.sha256).digest()
        expected = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        if hmac.compare_digest(expected, token):
            return True
    return False


@app.get("/api/members/{member_id}/qrs")
def get_member_qrs(member_id: str):
    # return urls with token for IN and OUT
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    m = db["member"].find_one({"_id": oid(member_id)})
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    return {
        "in": {
            "action": "IN",
            "token": generate_token(member_id, "IN"),
        },
        "out": {
            "action": "OUT",
            "token": generate_token(member_id, "OUT"),
        },
        "window_seconds": TOKEN_WINDOW_SECONDS,
    }


# Scanning endpoint
@app.post("/api/scan")
def scan(payload: AttendanceScan):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # payload.token encodes the time slice; client must provide member_id separately in URL or token must be per-member
    # We'll expect query params member_id and action inside payload as we defined
    action = payload.action
    # Search members to verify token by trying each? Not efficient. Instead, client should send member_id.
    # To keep API simple, include member_id in token verification path via x-member-id header? We'll extend payload.
    raise HTTPException(status_code=400, detail="Include member_id in request body as 'member_id'.")


class AttendanceScan2(BaseModel):
    member_id: str
    action: str  # IN|OUT
    token: str


@app.post("/api/scan2")
def scan2(payload: AttendanceScan2):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    member_id = payload.member_id
    action = payload.action
    token = payload.token
    if action not in ("IN", "OUT"):
        raise HTTPException(status_code=400, detail="Invalid action")
    # verify
    if not verify_token(member_id, action, token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # record attendance
    now = datetime.now(timezone.utc)
    att = {
        "member_id": member_id,
        "action": action,
        "timestamp": now,
        "created_at": now,
        "updated_at": now,
    }
    db["attendance"].insert_one(att)

    # update member presence
    upd = {"updated_at": now}
    if action == "IN":
        upd.update({"present": True, "last_in": now})
    else:
        upd.update({"present": False, "last_out": now})
    db["member"].update_one({"_id": oid(member_id)}, {"$set": upd})

    return {"status": "ok"}


@app.get("/api/members/{member_id}/attendance")
def member_attendance(member_id: str, limit: int = 50):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    records = list(db["attendance"].find({"member_id": member_id}).sort("timestamp", -1).limit(limit))
    for r in records:
        r["_id"] = str(r["_id"])
    return records
