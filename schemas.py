"""
Database Schemas for E‑commerce

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    password_hash: str = Field(..., description="Hashed password")
    avatar_url: Optional[str] = Field(None)
    is_active: bool = Field(True)

class Category(BaseModel):
    name: str = Field(...)
    slug: str = Field(..., description="URL-safe identifier")
    image: Optional[str] = None
    description: Optional[str] = None

class Variant(BaseModel):
    name: str = Field(..., description="e.g., Color or Size")
    value: str = Field(..., description="e.g., Red or M")
    sku: Optional[str] = None
    price_delta: float = 0.0
    stock: int = 0

class Product(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    images: List[str] = []
    category: str = Field(..., description="Category slug")
    tags: List[str] = []
    variants: List[Variant] = []
    rating: float = 0.0
    rating_count: int = 0

class Review(BaseModel):
    product_id: str
    user_id: str
    user_name: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

class OrderItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int
    variant: Optional[str] = None
    image: Optional[str] = None

class ShippingAddress(BaseModel):
    full_name: str
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str

class Order(BaseModel):
    user_id: Optional[str] = None
    items: List[OrderItem]
    subtotal: float
    shipping: float
    total: float
    email: EmailStr
    shipping_address: ShippingAddress
    status: str = "pending"
