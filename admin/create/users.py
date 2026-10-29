"""
User provisioning helpers.
"""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from pydantic import BaseModel, EmailStr, Field
from tableau_api_lib import TableauServerConnection

from ..session import authenticated_session

logger = logging.getLogger(__name__)


class UserDefinition(BaseModel):
    """Declarative definition of a Tableau user."""

    username: EmailStr
    site_role: str = Field(default="Viewer")
    auth_setting: str = Field(default="ServerDefault")
    password: str | None = None
    full_name: str | None = None


def create_user(
    user: UserDefinition,
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Create one Tableau user using the shared session manager.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    def _create(connection: TableauServerConnection) -> dict:
        response = connection.add_user_to_site(
            user_name=user.username,
            site_role=user.site_role,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create user '{user.username}': {response.status_code} — {response.text}")
        logger.info("Created user %s (role=%s)", user.username, user.site_role)
        return response.json()

    if conn is not None:
        return _create(conn)

    with authenticated_session() as session:
        return _create(session)


def update_user(
    user_id: str,
    site_role: str | None = None,
    full_name: str | None = None,
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Update an existing user.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    if conn is not None:
        response = conn.update_user(user_id=user_id, new_site_role=site_role, new_full_name=full_name)
        logger.info("Updated user %s", user_id)
        return response.json()

    with authenticated_session() as session:
        response = session.update_user(user_id=user_id, new_site_role=site_role, new_full_name=full_name)
        logger.info("Updated user %s", user_id)
        return response.json()


def bulk_provision(
    users: Iterable[UserDefinition],
    conn: Optional[TableauServerConnection] = None,
) -> List[dict]:
    """
    Provision a batch of users; simple wrapper that stops on first failure.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    def _provision(connection: TableauServerConnection) -> List[dict]:
        created = []
        for user in users:
            resp = connection.add_user_to_site(
                user_name=user.username,
                site_role=user.site_role,
            )
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Failed to provision user '{user.username}': {resp.status_code} — {resp.text}")
            logger.info("Provisioned user %s", user.username)
            created.append(resp.json())
        logger.info("Bulk provisioned %d users", len(created))
        return created

    if conn is not None:
        return _provision(conn)

    with authenticated_session() as session:
        return _provision(session)


def list_users() -> list[dict]:
    """
    Return all users on the active site.
    """
    with authenticated_session() as conn:
        resp = conn.get_users_on_site()
        users_data = resp.json().get("users", {})
        users = users_data.get("user", []) if isinstance(users_data, dict) else users_data
        logger.debug("Retrieved %d users", len(users))
        return users


def delete_user(user_id: str) -> dict:
    """
    Remove a user from the site.
    """
    with authenticated_session() as conn:
        resp = conn.remove_user_from_site(user_id=user_id)
        logger.info("Deleted user %s", user_id)
        return resp.json()
