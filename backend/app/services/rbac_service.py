"""Database seeding utilities for predefined RBAC roles and permissions."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Permission,
    PermissionCode,
    Role,
    RolePermission,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSION_MATRIX,
)


def seed_roles_and_permissions(db: Session) -> None:
    """Idempotently seed predefined permissions, roles, and role-permission mappings."""
    existing_perms = {
        p.code: p for p in db.execute(select(Permission)).scalars().all()
    }
    for code, desc in PermissionCode.ALL_DESCRIPTIONS.items():
        if code not in existing_perms:
            perm = Permission(code=code, description=desc)
            db.add(perm)
            existing_perms[code] = perm
    db.flush()

    existing_roles = {
        r.name: r for r in db.execute(select(Role)).scalars().all()
    }
    for role_name, role_desc in ROLE_DESCRIPTIONS.items():
        if role_name not in existing_roles:
            role = Role(name=role_name, description=role_desc)
            db.add(role)
            existing_roles[role_name] = role
    db.flush()

    existing_links = {
        (rp.role_id, rp.permission_id)
        for rp in db.execute(select(RolePermission)).scalars().all()
    }
    for role_name, perm_codes in ROLE_PERMISSION_MATRIX.items():
        role_obj = existing_roles[role_name]
        for code in perm_codes:
            perm_obj = existing_perms[code]
            if (role_obj.id, perm_obj.id) not in existing_links:
                db.add(RolePermission(role_id=role_obj.id, permission_id=perm_obj.id))

    db.commit()


def get_role_permissions(role: Role) -> list[str]:
    """Return sorted list of permission codes assigned to a role."""
    codes = {rp.permission.code for rp in role.role_permissions if rp.permission is not None}
    if not codes and role.name in ROLE_PERMISSION_MATRIX:
        codes = set(ROLE_PERMISSION_MATRIX[role.name])
    return sorted(codes)
