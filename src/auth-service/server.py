import datetime
import os

import jwt
import psycopg2
from flask import Flask, jsonify, request

server = Flask(__name__)

def get_db_connection():
    conn = psycopg2.connect(host=os.getenv('DATABASE_HOST'),
                            database=os.getenv('DATABASE_NAME'),
                            user=os.getenv('DATABASE_USER'),
                            password=os.getenv('DATABASE_PASSWORD'),
                            port=5432)
    return conn


@server.route('/healthz', methods=['GET'])
def healthz():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 503

@server.route('/login', methods=['POST'])
def login():
    auth_table_name = os.getenv('AUTH_TABLE')
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return 'Could not verify', 401, {'WWW-Authenticate': 'Basic realm="Login required!"'}

    conn = get_db_connection()
    cur = conn.cursor()
    # SECURITY: passwords are stored and compared in plaintext (see
    # Helm_charts/Postgres/init.sql). Not fixed here because remediation requires
    # hashing (e.g. bcrypt/argon2) plus migrating the seeded credentials — a
    # coordinated schema + data change out of scope for this surgical pass.
    # Recommended: store password hashes and compare with a constant-time check.
    query = f"SELECT email, password FROM {auth_table_name} WHERE email = %s"
    res = cur.execute(query, (auth.username,))
    
    if res is None:
        user_row = cur.fetchone()
        email = user_row[0]
        password = user_row[1]

        if auth.username != email or auth.password != password:
            return 'Could not verify', 401, {'WWW-Authenticate': 'Basic realm="Login required!"'}
        else:
            return CreateJWT(auth.username, os.environ['JWT_SECRET'], True)
    else:
        return 'Could not verify', 401, {'WWW-Authenticate': 'Basic realm="Login required!"'}

@server.route('/register', methods=['POST'])
def register():
    auth_table_name = os.getenv('AUTH_TABLE')
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return 'email and password are required', 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT 1 FROM {auth_table_name} WHERE email = %s", (email,))
        if cur.fetchone() is not None:
            return 'an account with that email already exists', 409
        # SECURITY: password stored in plaintext to match the existing /login
        # comparison and the seeded schema (Helm_charts/Postgres/init.sql).
        # Hashing (bcrypt/argon2) is the right fix but must change /login too.
        cur.execute(
            f"INSERT INTO {auth_table_name} (email, password) VALUES (%s, %s)",
            (email, password),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    # Auto-login: return a JWT so the new user is signed in immediately.
    return CreateJWT(email, os.environ['JWT_SECRET'], True), 201

def CreateJWT(username, secret, authz):
    return jwt.encode(
        {
            "username": username,
            "exp": datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(days=1),
            "iat": datetime.datetime.now(tz=datetime.timezone.utc),
            "admin": authz,
        },
        secret,
        algorithm="HS256",
    )

@server.route('/validate', methods=['POST'])
def validate():
    encoded_jwt = request.headers['Authorization']
    
    if not encoded_jwt:
        return 'Unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Login required!"'}

    encoded_jwt = encoded_jwt.split(' ')[1]
    try:
        decoded_jwt = jwt.decode(encoded_jwt, os.environ['JWT_SECRET'], algorithms=["HS256"])
    except Exception:
        return 'Unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Login required!"'}
    
    return decoded_jwt, 200

if __name__ == '__main__':
    server.run(host='0.0.0.0', port=5000)
