"""
Session helpers for Tableau REST interactions.

Supports two authentication methods:

* **PAT** (Personal Access Token) — one token per site, managed in the UI.
* **JWT** (Connected App / Direct Trust) — short-lived tokens minted on
  the fly from a client-id + secret.  No rotation required.

Credentials come from the unified config YAML.  Per-site overrides take
precedence over top-level defaults.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from typing import Generator, Optional

import jwt
import requests as http_requests
from tableau_api_lib import TableauServerConnection

try:
    from tableau_api_lib.exceptions import TableauServerResponseError
except ImportError:
    TableauServerResponseError = Exception  # type: ignore[assignment,misc]

from .config import SiteDefinition, TableauConfig, load_config

logger = logging.getLogger(__name__)


# ── JWT helpers ────────────────────────────────────────────────────────


def _mint_jwt(
    client_id: str,
    secret_id: str,
    secret_value: str,
    username: str,
) -> str:
    """
    Create a short-lived JWT for Tableau Connected App (Direct Trust).

    The token is valid for 5 minutes — Tableau requires ``exp`` within
    10 minutes of ``iss`` time.
    """
    now = int(time.time())
    payload = {
        "iss": client_id,
        "sub": username,
        "aud": "tableau",
        "exp": now + 300,  # 5 minutes
        "jti": str(uuid.uuid4()),
        "scp": ["tableau:content:read",
                 "tableau:tasks:run",
                 "tableau:workbooks:create",
                 "tableau:datasources:create",
                 "tableau:projects:create",
                 "tableau:groups:create",
                 "tableau:users:create"],
    }
    token = jwt.encode(payload, secret_value, algorithm="HS256", headers={
        "kid": secret_id,
        "iss": client_id,
    })
    return token


def _sign_in_with_jwt(
    server: str,
    api_version: str,
    site_content_url: str,
    jwt_token: str,
) -> dict:
    """
    POST to the Tableau REST sign-in endpoint with a JWT credential.

    Returns the full credentials dict (auth token, site id, user id).
    """
    url = f"{server}/api/{api_version}/auth/signin"
    body = {
        "credentials": {
            "jwt": jwt_token,
            "site": {
                "contentUrl": site_content_url,
            },
        }
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    resp = http_requests.post(url, json=body, headers=headers)
    logger.debug("JWT sign-in response: status=%d, body=%s", resp.status_code, resp.text[:500])
    if resp.status_code != 200:
        raise RuntimeError(
            f"JWT sign-in failed for site '{site_content_url}': "
            f"{resp.status_code} — {resp.text}"
        )
    try:
        return resp.json()["credentials"]
    except (ValueError, KeyError) as exc:
        raise RuntimeError(
            f"JWT sign-in for site '{site_content_url}' returned unexpected response: "
            f"{resp.status_code} — {resp.text[:500]}"
        ) from exc


def _build_jwt_connection(
    cfg: TableauConfig,
    site_def: SiteDefinition,
) -> TableauServerConnection:
    """
    Build a TableauServerConnection authenticated via JWT.

    We create the connection with dummy PAT values (to satisfy the
    constructor), then replace the auth token with one obtained from
    the JWT sign-in flow.
    """
    jwt_token = _mint_jwt(
        client_id=site_def.jwt_client_id,
        secret_id=site_def.jwt_secret_id,
        secret_value=site_def.jwt_secret_value,
        username=site_def.jwt_username,
    )

    creds = _sign_in_with_jwt(
        server=cfg.server,
        api_version=cfg.api_version,
        site_content_url=site_def.content_url,
        jwt_token=jwt_token,
    )

    # Build a connection object with placeholder creds — we'll inject
    # the real auth token immediately.
    connection = TableauServerConnection(
        config_json={
            "tableau_prod": {
                "server": cfg.server,
                "api_version": cfg.api_version,
                "site_name": site_def.content_url,
                "site_url": site_def.content_url,
                "personal_access_token_name": "jwt_placeholder",
                "personal_access_token_secret": "jwt_placeholder",
            }
        },
        env="tableau_prod",
    )

    # Inject the JWT-obtained auth state so all subsequent API calls
    # use the correct session.
    connection.auth_token = creds["token"]
    connection.site_id = creds["site"]["id"]
    connection.user_id = creds["user"]["id"]

    logger.debug(
        "JWT auth complete for site '%s' (user=%s)",
        site_def.content_url,
        site_def.jwt_username,
    )
    return connection


# ── PAT helpers ────────────────────────────────────────────────────────


def _get_site_pat(cfg: TableauConfig, site_def: Optional[SiteDefinition] = None):
    """
    Resolve PAT credentials: per-site overrides take precedence over
    top-level config.
    """
    pat_name = (site_def.pat_name if site_def and site_def.pat_name else cfg.pat_name)
    pat_secret = (site_def.pat_secret if site_def and site_def.pat_secret else cfg.pat_secret)
    return pat_name, pat_secret


def _build_pat_connection(
    cfg: TableauConfig,
    site_content_url: str,
    site_def: Optional[SiteDefinition] = None,
) -> TableauServerConnection:
    """Build a PAT-authenticated connection for a specific site."""
    pat_name, pat_secret = _get_site_pat(cfg, site_def)
    if not pat_name or not pat_secret:
        raise RuntimeError(
            f"Missing PAT credentials for site '{site_content_url}'. "
            "Set pat_name/pat_secret at the top level or per-site in your config, "
            "or via TABLEAU_PAT_NAME / TABLEAU_PAT_SECRET env vars."
        )
    return TableauServerConnection(
        config_json={
            "tableau_prod": {
                "server": cfg.server,
                "api_version": cfg.api_version,
                "site_name": site_content_url,
                "site_url": site_content_url,
                "personal_access_token_name": pat_name,
                "personal_access_token_secret": pat_secret,
            }
        },
        env="tableau_prod",
    )


# ── Public API ─────────────────────────────────────────────────────────


def build_connection(config: Optional[TableauConfig] = None) -> TableauServerConnection:
    """
    Instantiate a tableau-api-lib connection from config (default site).
    """
    cfg = config or load_config()
    return _build_pat_connection(cfg, site_content_url=cfg.site)


@contextmanager
def authenticated_session(
    config: Optional[TableauConfig] = None,
) -> Generator[TableauServerConnection, None, None]:
    """
    Context manager that signs in to the default site and automatically
    signs out.
    """
    connection = build_connection(config)
    try:
        response = connection.sign_in()
        if response.status_code != 200:
            raise RuntimeError(
                f"Tableau sign-in failed for default site: "
                f"{response.status_code} — {response.text}"
            )
        logger.debug("Signed in to %s (site=%s)", connection.server, connection.site_name)
        yield connection
    except TableauServerResponseError as exc:
        raise RuntimeError(f"Tableau API error: {exc}") from exc
    finally:
        try:
            connection.sign_out()
            logger.debug("Signed out")
        except Exception:
            pass


@contextmanager
def authenticated_session_for_site(
    site_content_url: str,
    config: Optional[TableauConfig] = None,
) -> Generator[TableauServerConnection, None, None]:
    """
    Context manager that signs into a *specific* site.

    Reads the site's ``auth_method`` from the config:

    * ``pat`` — signs in with a Personal Access Token (per-site or global).
    * ``jwt`` — mints a short-lived JWT from the site's Connected App
      credentials, signs in via the REST API, and injects the auth token
      into the connection object.

    Used by multi-site batch operations (publishing, bootstrapping,
    migration) where each iteration targets a different site.
    """
    cfg = config or load_config()

    # Look up the SiteDefinition for per-site auth settings
    site_def: Optional[SiteDefinition] = None
    for s in cfg.sites:
        if s.content_url == site_content_url:
            site_def = s
            break

    auth_method = site_def.auth_method if site_def else "pat"

    if auth_method == "jwt":
        if not site_def:
            raise RuntimeError(
                f"JWT auth requested for site '{site_content_url}' but no site "
                "definition found in config."
            )
        if not all([site_def.jwt_client_id, site_def.jwt_secret_id,
                     site_def.jwt_secret_value, site_def.jwt_username]):
            raise RuntimeError(
                f"JWT auth for site '{site_content_url}' requires jwt_client_id, "
                "jwt_secret_id, jwt_secret_value, and jwt_username."
            )
        # JWT sign-in is handled during connection build — already authenticated.
        connection = _build_jwt_connection(cfg, site_def)
        try:
            logger.debug("Signed in to site '%s' via JWT", site_content_url)
            yield connection
        finally:
            try:
                connection.sign_out()
                logger.debug("Signed out of site '%s'", site_content_url)
            except Exception:
                pass
    else:
        # PAT flow
        connection = _build_pat_connection(cfg, site_content_url, site_def)
        try:
            response = connection.sign_in()
            if response.status_code != 200:
                raise RuntimeError(
                    f"Tableau sign-in failed for site '{site_content_url}': "
                    f"{response.status_code} — {response.text}"
                )
            logger.debug("Signed in to site '%s' via PAT", site_content_url)
            yield connection
        except TableauServerResponseError as exc:
            raise RuntimeError(
                f"Tableau API error on site '{site_content_url}': {exc}"
            ) from exc
        finally:
            try:
                connection.sign_out()
                logger.debug("Signed out of site '%s'", site_content_url)
            except Exception:
                pass
