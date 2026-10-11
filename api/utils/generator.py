import os
import re
import secrets
import string

NNB_PATTERN = re.compile(r'^[A-Z0-9]{13}$')
CHARSET = string.ascii_uppercase + string.digits

def generate_nnb() -> str:
    """13자리 대문자 + 숫자 조합의 NNB 문자열 생성"""
    return ''.join(secrets.choice(CHARSET) for _ in range(13))

def validate_nnb(nnb: str) -> bool:
    """NNB 형식(13자리 대문자/숫자) 유효성 검사"""
    if not isinstance(nnb, str):
        return False
    return bool(NNB_PATTERN.match(nnb.strip()))
