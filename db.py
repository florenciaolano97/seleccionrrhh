from __future__ import annotations
import sqlite3
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        industry TEXT,
        country TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        password_salt TEXT NOT NULL,
        full_name TEXT NOT NULL,
        account_type TEXT NOT NULL,
        company_id INTEGER,
        role TEXT,
        permissions_json TEXT DEFAULT '[]',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(company_id) REFERENCES companies(id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE,
        phone TEXT,
        dni TEXT,
        city TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        area TEXT,
        seniority TEXT,
        description TEXT,
        status TEXT DEFAULT 'ABIERTA',
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(company_id) REFERENCES companies(id),
        FOREIGN KEY(created_by) REFERENCES users(id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        status TEXT DEFAULT 'RECIBIDA',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(candidate_id, job_id),
        FOREIGN KEY(candidate_id) REFERENCES candidates(id),
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )''')
    conn.commit()
    conn.close()

def fetch_all(query: str, params: tuple = ()):
    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fetch_one(query: str, params: tuple = ()):
    conn = get_connection()
    row = conn.execute(query, params).fetchone()
    conn.close()
    return dict(row) if row else None

def execute(query: str, params: tuple = ()):
    conn = get_connection()
    cur = conn.execute(query, params)
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid
