# Business API - Recommendations & Solutions

## Current Status ✅

The business API **already exists** and is working. Here's what's available:

### Existing Endpoints

#### 1. **List Businesses** (Public)
```
GET /api/v1/businesses
```
**Query Parameters:**
- `q` - Search term (searches name and description)
- `category_id` - Filter by category
- `city` - Filter by city
- `verified` - Filter verified businesses only
- `limit` - Results per page (default: 20, max: 100)
- `offset` - Pagination offset

**Response:** Array of `BusinessOut` objects

---

#### 2. **Get Business Details** (Public)
```
GET /api/v1/businesses/{business_id}
```
**Response:** Single `BusinessOut` object

---

#### 3. **Create Business** (Requires Authentication - Business User)
```
POST /api/v1/businesses
Authorization: Bearer {token}
```
**Request Body:**
```json
{
  "category_id": "string",
  "name": "string (2-160 chars)",
  "description": "string (min 10 chars)",
  "city": "string",
  "address": "string (optional)",
  "phone": "string (optional)",
  "website": "string (optional)",
  "latitude": 31.5204,  // optional
  "longitude": 74.3587  // optional
}
```
**Response:** `BusinessOut` object

---

#### 4. **Update Business** (Requires Authentication - Business Owner)
```
PATCH /api/v1/businesses/{business_id}
Authorization: Bearer {token}
```
**Request Body:** (all fields optional)
```json
{
  "name": "string",
  "description": "string",
  "city": "string",
  "address": "string",
  "phone": "string",
  "website": "string",
  "latitude": 31.5204,
  "longitude": 74.3587
}
```
**Response:** Updated `BusinessOut` object

---

## Issues Fixed ✅

### 1. **Schema Validation Error**
- **Problem:** Businesses without `latitude`/`longitude` caused 500 errors
- **Solution:** Added default values `= None` to optional fields in schema
- **Status:** ✅ Fixed

### 2. **Missing Coordinates in Database**
- **Problem:** Some businesses had no coordinates
- **Solution:** Created migration script `scripts/fix_business_coordinates.py`
- **Status:** ✅ Fixed (1 business updated)

---

## Recommendations

### **Immediate Actions** 🚀

#### 1. **Verify Frontend API Configuration**
Check that your frontend is calling the correct endpoints:
```typescript
// Make sure base URL is correct
const API_BASE_URL = 'http://localhost:8000/api/v1';

// Example business listing call
const response = await fetch(`${API_BASE_URL}/businesses`, {
  method: 'GET',
  headers: {
    'Content-Type': 'application/json',
  },
});
```

#### 2. **Check CORS Configuration**
Current CORS settings in `.env`:
```
CORS_ORIGINS='["http://localhost:3000", "http://localhost:5173"]'
CORS_ORIGIN_REGEX='^https?://(?:localhost|127\.0\.0\.1)(?::\d+)?$'
```

✅ If your frontend runs on a different port, add it to `CORS_ORIGINS`

#### 3. **Test API Endpoints**
Use the provided test scripts or try these curl commands:

```bash
# List all businesses
curl http://localhost:8000/api/v1/businesses

# Get categories
curl http://localhost:8000/api/v1/categories

# Search businesses
curl "http://localhost:8000/api/v1/businesses?city=Lahore&limit=10"
```

---

### **Enhancements** 🔧

#### 1. **Add Public Business Creation Endpoint** (Optional)
If you want to allow non-authenticated users to submit business listings:

```python
@router.post("/businesses/submit", response_model=dict, status_code=201, tags=["businesses"])
def submit_business_for_review(payload: BusinessCreate, db: DbSession) -> dict:
    """Public endpoint for business submission (requires admin approval)"""
    if db.categories.find_one({"_id": payload.category_id}) is None:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    base_slug = slugify(payload.name)
    slug, counter = base_slug, 2
    while db.businesses.find_one({"slug": slug}):
        slug, counter = f"{base_slug}-{counter}", counter + 1
    
    item = document(
        owner_id=None,  # No owner for submitted businesses
        slug=slug,
        is_verified=False,
        is_active=False,  # Requires admin approval
        view_count=0,
        **payload.model_dump()
    )
    db.businesses.insert_one(item)
    return {"id": item["_id"], "status": "pending_review"}
```

#### 2. **Add Bulk Import Endpoint** (For Admin)
If you need to import many businesses at once:

```python
@router.post("/admin/businesses/bulk-import", tags=["admin"])
def bulk_import_businesses(
    businesses: list[BusinessCreate],
    db: DbSession,
    user: AdminUser
) -> dict[str, int]:
    """Import multiple businesses at once"""
    created_count = 0
    failed_count = 0
    
    for business_data in businesses:
        try:
            # Validate category
            if db.categories.find_one({"_id": business_data.category_id}) is None:
                failed_count += 1
                continue
            
            # Generate slug
            base_slug = slugify(business_data.name)
            slug, counter = base_slug, 2
            while db.businesses.find_one({"slug": slug}):
                slug, counter = f"{base_slug}-{counter}", counter + 1
            
            # Create business
            item = document(
                owner_id=user["_id"],
                slug=slug,
                is_verified=True,  # Admin imports are auto-verified
                is_active=True,
                view_count=0,
                **business_data.model_dump()
            )
            db.businesses.insert_one(item)
            created_count += 1
        except Exception:
            failed_count += 1
    
    return {
        "created": created_count,
        "failed": failed_count,
        "total": len(businesses)
    }
```

#### 3. **Add Data Validation Improvements**
Enhance the `create_business` endpoint to auto-geocode if coordinates are missing:

```python
@router.post("/businesses", response_model=BusinessOut, status_code=201, tags=["businesses"])
def create_business(payload: BusinessCreate, db: DbSession, user: BusinessUser) -> dict:
    if db.categories.find_one({"_id": payload.category_id}) is None:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    # Auto-geocode if coordinates not provided
    if payload.latitude is None or payload.longitude is None:
        city_coords = {
            "karachi": (24.8607, 67.0011),
            "lahore": (31.5204, 74.3587),
            "islamabad": (33.6844, 73.0479),
            # ... more cities
        }
        city_lower = payload.city.lower().strip()
        if city_lower in city_coords:
            payload.latitude, payload.longitude = city_coords[city_lower]
        else:
            # Default to Lahore
            payload.latitude, payload.longitude = (31.5204, 74.3587)
    
    base_slug = slugify(payload.name)
    slug, counter = base_slug, 2
    while db.businesses.find_one({"slug": slug}):
        slug, counter = f"{base_slug}-{counter}", counter + 1
    
    item = document(
        owner_id=user["_id"],
        slug=slug,
        is_verified=False,
        is_active=True,
        view_count=0,
        **payload.model_dump()
    )
    db.businesses.insert_one(item)
    return public(item)
```

---

## Frontend Integration Guide

### 1. **Fetch Businesses**
```typescript
async function fetchBusinesses(filters?: {
  category?: string;
  city?: string;
  search?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.category) params.append('category_id', filters.category);
  if (filters?.city) params.append('city', filters.city);
  if (filters?.search) params.append('q', filters.search);
  
  const response = await fetch(
    `http://localhost:8000/api/v1/businesses?${params}`,
    {
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
}
```

### 2. **Create Business** (Authenticated)
```typescript
async function createBusiness(
  businessData: BusinessCreate,
  token: string
) {
  const response = await fetch(
    'http://localhost:8000/api/v1/businesses',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(businessData),
    }
  );
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
}
```

### 3. **Error Handling**
```typescript
try {
  const businesses = await fetchBusinesses({ city: 'Lahore' });
  console.log('Businesses:', businesses);
} catch (error) {
  if (error instanceof TypeError) {
    console.error('Network error - cannot reach API');
  } else {
    console.error('Error fetching businesses:', error);
  }
}
```

---

## Debugging Checklist ✅

If "Unable to load businesses" persists:

1. ✅ **Backend running?** Check: `http://localhost:8000/api/v1/health`
2. ✅ **Coordinates fixed?** Run: `python scripts/fix_business_coordinates.py`
3. ✅ **CORS configured?** Check `.env` has correct frontend URL
4. ✅ **API reachable?** Test: `curl http://localhost:8000/api/v1/businesses`
5. ✅ **Frontend URL correct?** Verify API base URL in frontend config
6. ✅ **Browser console?** Check for CORS or network errors

---

## Summary

### What's Working ✅
- Business listing API (GET /businesses)
- Business detail API (GET /businesses/:id)
- Business creation API (POST /businesses - requires auth)
- Business update API (PATCH /businesses/:id - requires auth)
- Categories API (GET /categories)
- Schema validation fixed
- Database coordinates fixed

### What Might Need Checking ⚠️
- Frontend API base URL configuration
- CORS settings if frontend is on different port
- Network connectivity between frontend and backend
- Authentication flow if creating/updating businesses

### Next Steps 🎯
1. Run the coordinate fix script: `python scripts/fix_business_coordinates.py`
2. Verify backend is running: `http://localhost:8000/api/v1/health`
3. Test API directly: `curl http://localhost:8000/api/v1/businesses`
4. Check frontend console for errors
5. Verify frontend API URL matches backend port (8000)
