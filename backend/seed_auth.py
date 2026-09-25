import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from auth.database import auth_engine, AuthBase, AuthSessionLocal
from auth.models import User
from auth.security import generate_id, hash_password
from auth.audit import next_user_id

DEMO_USERS = [
    {
        "full_name": "Admin User",
        "email": "admin@sankalp.gov.in",
        "password": "admin123",
        "role": "admin",
        "department": "Digital India Corporation",
        "designation": "System Administrator",
    },
    {
        "full_name": "Rajesh Kumar",
        "email": "officer@sankalp.gov.in",
        "password": "officer123",
        "role": "officer",
        "department": "Ministry of Road Transport",
        "designation": "Project Monitoring Officer",
    },
    {
        "full_name": "Priya Sharma",
        "email": "analyst@sankalp.gov.in",
        "password": "analyst123",
        "role": "analyst",
        "department": "NITI Aayog",
        "designation": "Risk Analyst",
    },
    {
        "full_name": "Amit Verma",
        "email": "viewer@sankalp.gov.in",
        "password": "viewer123",
        "role": "viewer",
        "department": "Ministry of Finance",
        "designation": "Budget Review Officer",
    },
]

EXPECTED_USER_IDS = {
    "admin@sankalp.gov.in": "USR-0001",
    "officer@sankalp.gov.in": "USR-0002",
    "analyst@sankalp.gov.in": "USR-0003",
    "viewer@sankalp.gov.in": "USR-0004",
}


def seed_auth():
    AuthBase.metadata.create_all(bind=auth_engine)
    db = AuthSessionLocal()
    try:
        created = 0
        for u in DEMO_USERS:
            existing = db.query(User).filter(User.email == u["email"]).first()
            if existing:
                if not existing.user_id:
                    existing.user_id = EXPECTED_USER_IDS.get(u["email"]) or next_user_id(db)
                    print(f"  [backfill] {u['email']} -> {existing.user_id}")
                else:
                    print(f"  [skip] {u['email']} already exists ({existing.user_id})")
                continue
            user = User(
                id=generate_id(),
                user_id=EXPECTED_USER_IDS.get(u["email"]) or next_user_id(db),
                full_name=u["full_name"],
                email=u["email"],
                password_hash=hash_password(u["password"]),
                role=u["role"],
                department=u["department"],
                designation=u["designation"],
                is_active=True,
            )
            db.add(user)
            created += 1
            print(f"  [created] {u['email']} ({u['role']}) {user.user_id}")
        db.commit()
        print(f"\nAuth seed complete. {created} users created, {4 - created} skipped.")
        print("\nDemo accounts:")
        for u in DEMO_USERS:
            uid = EXPECTED_USER_IDS.get(u["email"], "")
            print(f"  {uid}  {u['email']} / {u['password']} ({u['role']})")
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding auth database...\n")
    seed_auth()