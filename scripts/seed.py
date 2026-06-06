"""Idempotent seed: default tenant + saas_admin user."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import uuid
from passlib.context import CryptContext
from sqlalchemy import select
from app.config import get_settings
from app.database import OwnerSessionLocal
from app.models import Tenant, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


async def seed() -> None:
    async with OwnerSessionLocal() as session:
        # Tenant
        row = await session.execute(select(Tenant).where(Tenant.slug == "default"))
        tenant = row.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(id=uuid.uuid4(), name="OJSDef Default", slug="default")
            session.add(tenant)
            await session.flush()
            print(f"[seed] tenant created: {tenant.id}")
        else:
            print(f"[seed] tenant exists: {tenant.id}")

        # saas_admin
        row = await session.execute(select(User).where(User.email == settings.seed_admin_email))
        user = row.scalar_one_or_none()
        if not user:
            user = User(
                id=uuid.uuid4(),
                tenant_id=tenant.id,
                email=settings.seed_admin_email,
                hashed_password=pwd_context.hash(settings.seed_admin_password),
                full_name="SaaS Administrator",
                role="saas_admin",
            )
            session.add(user)
            print(f"[seed] saas_admin created: {settings.seed_admin_email}")
        else:
            print(f"[seed] saas_admin exists: {settings.seed_admin_email}")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
