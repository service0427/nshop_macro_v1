#!/usr/bin/env python3
import json
import secrets
import uuid
import hashlib
import random

def generate_identity():
    ssaid = secrets.token_hex(8)
    ni = hashlib.md5(ssaid.encode()).hexdigest()
    token = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))
    
    profiles = [
        {"model": "SM-S928N", "brand": "samsung", "manufacturer": "samsung", "device": "e3q", "product": "e3qks", "hardware": "qcom"},
        {"model": "SM-N986N", "brand": "samsung", "manufacturer": "samsung", "device": "canvas2", "product": "canvas2ks", "hardware": "qcom"},
        {"model": "SM-G998N", "brand": "samsung", "manufacturer": "samsung", "device": "o1q", "product": "o1qks", "hardware": "qcom"},
        {"model": "SM-S908N", "brand": "samsung", "manufacturer": "samsung", "device": "rainbow", "product": "rainbowks", "hardware": "qcom"}
    ]
    prof = random.choice(profiles)
    
    identity = {
        "ssaid": ssaid,
        "adid": str(uuid.uuid4()),
        "idfv": str(uuid.uuid4()),
        "ni": ni,
        "token": token,
        "model": prof["model"],
        "brand": prof["brand"],
        "manufacturer": prof["manufacturer"],
        "device": prof["device"],
        "product": prof["product"],
        "hardware": prof["hardware"]
    }
    return identity

if __name__ == "__main__":
    print(json.dumps(generate_identity(), indent=2))
