import os
import pymysql

def test_connection():
    config = {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", 3306)),
        "user": os.getenv("DB_USER", "nshop"),
        "password": os.getenv("DB_PASSWORD", "Tech1324"),
        "database": os.getenv("DB_NAME", "nshop_api_v1"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor
    }

    try:
        conn = pymysql.connect(**config)
        with conn.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS cur_db, USER() AS cur_user, VERSION() AS db_version;")
            result = cursor.fetchone()
            print(" MariaDB Connection Successful!")
            print(f"- Database: {result['cur_db']}")
            print(f"- User    : {result['cur_user']}")
            print(f"- Version : {result['db_version']}")
        conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    test_connection()
