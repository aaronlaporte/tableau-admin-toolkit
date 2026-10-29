"""
Group creation & membership.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

from tableau_api_lib import TableauServerConnection

from ..session import authenticated_session

logger = logging.getLogger(__name__)


def create_group(
    name: str,
    minimum_site_role: str = "Viewer",
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Create a Tableau group.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    def _create(connection: TableauServerConnection) -> dict:
        response = connection.create_group(new_group_name=name)
        if response.status_code not in (200, 201):
            raise RuntimeError(f"Failed to create group '{name}': {response.status_code} — {response.text}")
        logger.info("Created group '%s' (min_role=%s)", name, minimum_site_role)
        return response.json()

    if conn is not None:
        return _create(conn)

    with authenticated_session() as session:
        return _create(session)


def add_users_to_group(
    group_id: str,
    user_ids: Iterable[str],
    conn: Optional[TableauServerConnection] = None,
) -> list[dict]:
    """
    Add a list of users to a group.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    def _add(connection: TableauServerConnection) -> list[dict]:
        results = []
        for user_id in user_ids:
            resp = connection.add_user_to_group(group_id=group_id, user_id=user_id)
            logger.info("Added user %s to group %s", user_id, group_id)
            results.append(resp.json())
        return results

    if conn is not None:
        return _add(conn)

    with authenticated_session() as session:
        return _add(session)


def list_groups() -> list[dict]:
    """
    Return all groups on the active site.
    """
    with authenticated_session() as conn:
        resp = conn.query_groups()
        groups_data = resp.json().get("groups", {})
        groups = groups_data.get("group", []) if isinstance(groups_data, dict) else groups_data
        logger.debug("Retrieved %d groups", len(groups))
        return groups


def list_group_members(group_id: str) -> list[dict]:
    """
    Return all users in a group.
    """
    with authenticated_session() as conn:
        resp = conn.get_users_in_group(group_id=group_id)
        users = resp.json().get("users", {}).get("user", [])
        logger.debug("Group %s has %d members", group_id, len(users))
        return users


def remove_user_from_group(group_id: str, user_id: str) -> dict:
    """
    Remove a user from a group.
    """
    with authenticated_session() as conn:
        resp = conn.remove_user_from_group(group_id=group_id, user_id=user_id)
        logger.info("Removed user %s from group %s", user_id, group_id)
        return resp.json()


def delete_group(group_id: str) -> dict:
    """
    Delete a group.
    """
    with authenticated_session() as conn:
        resp = conn.delete_group(group_id=group_id)
        logger.info("Deleted group %s", group_id)
        return resp.json()
