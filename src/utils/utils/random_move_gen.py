import sys
import math
import random
import json

def generate_random_walk(start_lat, start_lng, count, radius_m):
    pts = [[start_lat, start_lng]]
    
    # Generate completely random points "왔다갔다" around the start point
    # Constrain within a given radius in meters.
    for _ in range(count):
        radius_deg = radius_m / 111000.0
        
        u = random.random()
        v = random.random()
        
        # uniform circle distribution
        w = radius_deg * math.sqrt(u)
        t = 2 * math.pi * v
        
        r_lat = start_lat + w * math.sin(t)
        r_lng = start_lng + (w * math.cos(t)) / math.cos(math.radians(start_lat))
        
        pts.append([r_lat, r_lng])
        
    return pts

if __name__ == "__main__":
    lat = float(sys.argv[1])
    lng = float(sys.argv[2])
    count = int(sys.argv[3])
    out_file = sys.argv[4]
    
    # 30 meters radius as requested
    pts = generate_random_walk(lat, lng, count, 30)
    
    with open(out_file, "w") as f:
        json.dump(pts, f)
