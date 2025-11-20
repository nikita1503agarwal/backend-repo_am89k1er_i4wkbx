import os
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User as UserSchema, Category as CategorySchema, Product as ProductSchema, Review as ReviewSchema, Order as OrderSchema

SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

app = FastAPI(title="E‑Commerce API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helpers
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    avatar_url: Optional[str] = None


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db["user"].find_one({"_id": ObjectId(user_id)})
    if not user:
        raise credentials_exception
    return UserOut(id=str(user["_id"]), name=user.get("name"), email=user.get("email"), avatar_url=user.get("avatar_url"))


@app.get("/")
def read_root():
    return {"message": "E‑commerce backend is running"}


# Auth
@app.post("/api/register", response_model=UserOut)
def register(user: UserSchema):
    if db is None:
        raise HTTPException(500, "Database not configured")
    existing = db["user"].find_one({"email": user.email})
    if existing:
        raise HTTPException(400, "Email already registered")
    data = user.model_dump()
    data["password_hash"] = get_password_hash(data["password_hash"])  # field contains plain on input
    user_id = db["user"].insert_one({**data, "created_at": datetime.now(timezone.utc)}).inserted_id
    return UserOut(id=str(user_id), name=user.name, email=user.email, avatar_url=user.avatar_url)


@app.post("/api/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if db is None:
        raise HTTPException(500, "Database not configured")
    user = db["user"].find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password_hash", "")):
        raise HTTPException(400, "Incorrect email or password")
    access_token = create_access_token({"sub": str(user["_id"])})
    return Token(access_token=access_token)


@app.get("/api/me", response_model=UserOut)
def me(current: UserOut = Depends(get_current_user)):
    return current


# Catalog
@app.get("/api/categories")
def list_categories():
    cats = get_documents("category")
    for c in cats:
        c["id"] = str(c.pop("_id"))
    return cats


@app.get("/api/products")
def list_products(
    q: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    page: int = 1,
    limit: int = 12,
    sort: Optional[str] = Query(None, description="price_asc|price_desc|rating_desc"),
):
    if db is None:
        raise HTTPException(500, "Database not configured")
    filter_q = {}
    if q:
        filter_q["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"tags": {"$regex": q, "$options": "i"}},
        ]
    if category:
        filter_q["category"] = category
    if min_price is not None or max_price is not None:
        price_filter = {}
        if min_price is not None:
            price_filter["$gte"] = min_price
        if max_price is not None:
            price_filter["$lte"] = max_price
        filter_q["price"] = price_filter

    sort_spec = None
    if sort == "price_asc":
        sort_spec = [("price", 1)]
    elif sort == "price_desc":
        sort_spec = [("price", -1)]
    elif sort == "rating_desc":
        sort_spec = [("rating", -1)]

    cursor = db["product"].find(filter_q)
    if sort_spec:
        cursor = cursor.sort(sort_spec)
    total = cursor.count() if hasattr(cursor, 'count') else db["product"].count_documents(filter_q)
    cursor = cursor.skip((page - 1) * limit).limit(limit)

    items = []
    for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)

    return {"items": items, "page": page, "limit": limit, "total": total}


@app.get("/api/products/{slug}")
def get_product(slug: str):
    prod = db["product"].find_one({"slug": slug})
    if not prod:
        raise HTTPException(404, "Product not found")
    prod["id"] = str(prod.pop("_id"))
    # related by category
    related = list(db["product"].find({"category": prod["category"], "slug": {"$ne": slug}}).limit(8))
    for r in related:
        r["id"] = str(r.pop("_id"))
    return {"product": prod, "related": related}


@app.get("/api/products/{product_id}/reviews")
def get_reviews(product_id: str):
    revs = list(db["review"].find({"product_id": product_id}).sort([("created_at", -1)]))
    for r in revs:
        r["id"] = str(r.pop("_id"))
    return revs


@app.post("/api/products/{product_id}/reviews")
def add_review(product_id: str, review: ReviewSchema, current: Optional[UserOut] = Depends(get_current_user)):
    if review.product_id != product_id:
        raise HTTPException(400, "Mismatched product id")
    data = review.model_dump()
    if current:
        data["user_id"] = current.id
        data["user_name"] = current.name
    data["created_at"] = datetime.now(timezone.utc)
    rid = db["review"].insert_one(data).inserted_id
    # update product rating
    revs = list(db["review"].find({"product_id": product_id}))
    if revs:
        avg = sum([r.get("rating", 0) for r in revs]) / len(revs)
        db["product"].update_one({"_id": ObjectId(product_id)}, {"$set": {"rating": round(avg, 2), "rating_count": len(revs)}})
    return {"id": str(rid)}


# Orders (simple checkout)
@app.post("/api/orders")
def create_order(order: OrderSchema):
    data = order.model_dump()
    data["created_at"] = datetime.now(timezone.utc)
    oid = db["order"].insert_one(data).inserted_id
    return {"order_id": str(oid), "status": "received"}


# Search suggestions
@app.get("/api/search")
def search_suggestions(q: str):
    cursor = db["product"].find({"title": {"$regex": q, "$options": "i"}}, {"title": 1, "slug": 1}).limit(8)
    return [{"title": d.get("title"), "slug": d.get("slug")} for d in cursor]


# Seed sample data if empty
@app.post("/api/seed")
def seed():
    if db["category"].count_documents({}) == 0:
        categories = [
            {"name": "Cards", "slug": "cards", "image": "/cat-cards.jpg"},
            {"name": "Accessories", "slug": "accessories", "image": "/cat-accessories.jpg"},
            {"name": "Digital", "slug": "digital", "image": "/cat-digital.jpg"},
        ]
        db["category"].insert_many(categories)
    if db["product"].count_documents({}) == 0:
        products = [
            {
                "title": "Glass Credit Card",
                "slug": "glass-credit-card",
                "description": "Minimal, premium glass-morphic card.",
                "price": 129.0,
                "images": ["/prod-card-1.jpg", "/prod-card-2.jpg", "/prod-card-3.jpg"],
                "category": "cards",
                "tags": ["card", "glass", "fintech"],
                "variants": [
                    {"name": "Color", "value": "Frost", "sku": "GC-FR", "price_delta": 0, "stock": 25},
                    {"name": "Color", "value": "Graphite", "sku": "GC-GR", "price_delta": 10, "stock": 12},
                ],
                "rating": 4.6,
                "rating_count": 42,
            },
            {
                "title": "Metal Card Holder",
                "slug": "metal-card-holder",
                "description": "Slim aluminum RFID-blocking holder.",
                "price": 49.0,
                "images": ["/prod-holder-1.jpg", "/prod-holder-2.jpg"],
                "category": "accessories",
                "tags": ["holder", "rfid"],
                "variants": [
                    {"name": "Color", "value": "Silver", "sku": "MH-SV", "price_delta": 0, "stock": 40},
                    {"name": "Color", "value": "Black", "sku": "MH-BK", "price_delta": 0, "stock": 35},
                ],
                "rating": 4.4,
                "rating_count": 26,
            },
            {
                "title": "Virtual Card Subscription",
                "slug": "virtual-card-subscription",
                "description": "Secure virtual cards for online purchases.",
                "price": 9.99,
                "images": ["/prod-virtual-1.jpg"],
                "category": "digital",
                "tags": ["subscription", "virtual"],
                "variants": [],
                "rating": 4.8,
                "rating_count": 61,
            },
        ]
        db["product"].insert_many(products)
    return {"ok": True}


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
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
