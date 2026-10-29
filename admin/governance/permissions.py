"""
Permission helpers for Tableau content.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from tableau_api_lib import TableauServerConnection

from ..session import authenticated_session

logger = logging.getLogger(__name__)


def set_project_permissions(
    project_id: str,
    payload: Dict,
    conn: Optional[TableauServerConnection] = None,
) -> dict:
    """
    Apply a permissions payload to a project.

    Parameters
    ----------
    conn
        Pre-authenticated connection.  When *None* a new session is created.
    """
    if conn is not None:
        resp = conn.update_project_permissions(project_id=project_id, permissions_payload=payload)
        logger.info("Set permissions on project %s", project_id)
        return resp.json()

    with authenticated_session() as session:
        resp = session.update_project_permissions(project_id=project_id, permissions_payload=payload)
        logger.info("Set permissions on project %s", project_id)
        return resp.json()


def diff_permissions(current: List[dict], desired: List[dict]) -> Dict[str, List[dict]]:
    """
    Compare current vs desired permissions arrays and highlight adds/removals.
    """
    result: Dict[str, List[dict]] = {"add": [], "remove": []}
    desired_set = {(item["grantee"]["id"], tuple(sorted(item["capabilities"].items()))) for item in desired}
    current_set = {(item["grantee"]["id"], tuple(sorted(item["capabilities"].items()))) for item in current}

    for item in desired_set - current_set:
        result["add"].append(item)
    for item in current_set - desired_set:
        result["remove"].append(item)
    logger.debug("Permission diff: %d adds, %d removes", len(result["add"]), len(result["remove"]))
    return result


def apply_permission_diff(project_id: str, diff: Dict[str, List]) -> dict:
    """
    Apply adds/removals from a permission diff to a project.

    Each entry in ``diff["add"]`` is a tuple of ``(grantee_id, capabilities_tuple)``.
    Each entry in ``diff["remove"]`` follows the same shape.
    """
    added = 0
    removed = 0

    with authenticated_session() as conn:
        for grantee_id, capabilities in diff.get("add", []):
            cap_dict = dict(capabilities)
            payload = {
                "granteeCapabilities": [
                    {
                        "grantee": {"id": grantee_id},
                        "capabilities": cap_dict,
                    }
                ]
            }
            try:
                conn.update_project_permissions(
                    project_id=project_id,
                    permissions_payload=payload,
                )
                added += 1
            except Exception as exc:
                logger.error("Failed to add permissions for grantee %s: %s", grantee_id, exc)

        for grantee_id, capabilities in diff.get("remove", []):
            cap_dict = dict(capabilities)
            for cap_name, cap_mode in cap_dict.items():
                try:
                    conn.delete_project_permission(
                        project_id=project_id,
                        grantee_id=grantee_id,
                        capability_name=cap_name,
                        capability_mode=cap_mode,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to remove %s permission for grantee %s: %s",
                        cap_name,
                        grantee_id,
                        exc,
                    )
            removed += 1

    result = {"added": added, "removed": removed}
    logger.info("Applied permission diff on project %s: %s", project_id, result)
    return result
