from __future__ import annotations
import json
from core.security import hash_password, normalize_email, validate_email, validate_password, verify_password
from database.db import execute, fetch_one

def register_company_admin(company_name, industry, country, full_name, email, password):
    if not company_name.strip():
        raise ValueError("Ingresá el nombre de la empresa.")
    if not full_name.strip():
        raise ValueError("Ingresá el nombre del administrador.")
    if not validate_email(email):
        raise ValueError("Ingresá un correo electrónico válido.")
    error = validate_password(password)
    if error:
        raise ValueError(error)
    email = normalize_email(email)
    if fetch_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("Ya existe un usuario con ese correo.")
    company_id = execute(
        "INSERT INTO companies(name, industry, country) VALUES (?, ?, ?)",
        (company_name.strip(), industry.strip(), country.strip()),
    )
    password_hash, salt = hash_password(password)
    execute(
        '''INSERT INTO users(
            email, password_hash, password_salt, full_name,
            account_type, company_id, role, permissions_json
        ) VALUES (?, ?, ?, ?, 'COMPANY', ?, 'ADMIN', ?)''',
        (email, password_hash, salt, full_name.strip(), company_id, json.dumps(["ALL"])),
    )
    return company_id

def register_candidate(full_name, email, password, phone="", dni="", city=""):
    if not full_name.strip():
        raise ValueError("Ingresá nombre y apellido.")
    if not validate_email(email):
        raise ValueError("Ingresá un correo electrónico válido.")
    error = validate_password(password)
    if error:
        raise ValueError(error)
    email = normalize_email(email)
    if fetch_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("Ya existe un usuario con ese correo.")
    password_hash, salt = hash_password(password)
    user_id = execute(
        '''INSERT INTO users(
            email, password_hash, password_salt, full_name, account_type
        ) VALUES (?, ?, ?, ?, 'CANDIDATE')''',
        (email, password_hash, salt, full_name.strip()),
    )
    return execute(
        "INSERT INTO candidates(user_id, phone, dni, city) VALUES (?, ?, ?, ?)",
        (user_id, phone.strip(), dni.strip(), city.strip()),
    )

def authenticate(email, password):
    user = fetch_one(
        "SELECT * FROM users WHERE email = ? AND active = 1",
        (normalize_email(email),),
    )
    if not user:
        return None
    if not verify_password(password, user["password_hash"], user["password_salt"]):
        return None
    return user
