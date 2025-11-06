"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

# Example schemas (kept for reference):
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")

# Attendance app schemas
class Member(BaseModel):
    name: str = Field(..., description="Member full name")
    present: bool = Field(False, description="Current presence status")
    last_in: Optional[datetime] = Field(None, description="Last IN timestamp")
    last_out: Optional[datetime] = Field(None, description="Last OUT timestamp")

class Attendance(BaseModel):
    member_id: str = Field(..., description="Member ObjectId as string")
    action: Literal["IN", "OUT"] = Field(..., description="Attendance action")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp (UTC)")
