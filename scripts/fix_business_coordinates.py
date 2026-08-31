"""Fix businesses missing latitude/longitude coordinates."""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import get_database
from app.models import utc_now


def fix_business_coordinates():
    """Add default coordinates to businesses missing lat/long."""
    db = get_database()
    
    # Default coordinates for major Pakistani cities
    city_coordinates = {
        "karachi": {"latitude": 24.8607, "longitude": 67.0011},
        "lahore": {"latitude": 31.5204, "longitude": 74.3587},
        "islamabad": {"latitude": 33.6844, "longitude": 73.0479},
        "rawalpindi": {"latitude": 33.5651, "longitude": 73.0169},
        "faisalabad": {"latitude": 31.4504, "longitude": 73.1350},
        "multan": {"latitude": 30.1575, "longitude": 71.5249},
        "peshawar": {"latitude": 34.0151, "longitude": 71.5249},
        "quetta": {"latitude": 30.1798, "longitude": 66.9750},
        "sialkot": {"latitude": 32.4972, "longitude": 74.5319},
        "gujranwala": {"latitude": 32.1877, "longitude": 74.1945},
    }
    
    # Find businesses without coordinates
    businesses_without_coords = db.businesses.find({
        "$or": [
            {"latitude": {"$exists": False}},
            {"longitude": {"$exists": False}},
            {"latitude": None},
            {"longitude": None}
        ]
    })
    
    updated_count = 0
    for business in businesses_without_coords:
        city = business.get("city", "").lower().strip()
        
        # Try to match city name
        coords = city_coordinates.get(city)
        if not coords:
            # Default to Lahore if city not found
            coords = city_coordinates["lahore"]
            print(f"⚠ Business '{business['name']}' in unknown city '{business.get('city')}', using Lahore coordinates")
        
        # Update business
        result = db.businesses.update_one(
            {"_id": business["_id"]},
            {
                "$set": {
                    "latitude": coords["latitude"],
                    "longitude": coords["longitude"],
                    "updated_at": utc_now()
                }
            }
        )
        
        if result.modified_count > 0:
            updated_count += 1
            print(f"✓ Updated '{business['name']}' in {business.get('city', 'Unknown')} with coordinates")
    
    print(f"\n{'='*60}")
    print(f"Fixed {updated_count} businesses with missing coordinates")
    print(f"{'='*60}")


if __name__ == "__main__":
    print("="*60)
    print("Fixing Business Coordinates")
    print("="*60)
    fix_business_coordinates()
