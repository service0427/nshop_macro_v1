import pymysql
from contextlib import contextmanager
from config import DB_CONFIG

def get_db_connection():
    """MariaDB 연결 객체 생성 (DictCursor 기본)"""
    return pymysql.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        charset=DB_CONFIG["charset"],
        autocommit=DB_CONFIG["autocommit"],
        cursorclass=pymysql.cursors.DictCursor
    )

@contextmanager
def get_db_cursor(commit=True):
    """
    안전한 DB 커서 컨텍스트 매니저.
    블록 내 에러 발생 시 자동 롤백, 정상 종료 시 자동 커밋(옵션) 및 연결 해제.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            yield cur, conn
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
