"""
Reference datasource connectors (SQL-based).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text


@dataclass
class ReferenceSource:
    """
    Generic SQL reference datasource using SQLAlchemy.
    """

    connection_string: str

    def query(self, sql: str, **params) -> pd.DataFrame:
        engine = create_engine(self.connection_string)
        with engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)
        return df


def load_reference_source(connection_string: Optional[str] = None) -> ReferenceSource:
    """
    Build reference data connector from env/config.
    """
    if not connection_string:
        from os import getenv

        connection_string = getenv("REFERENCE_DB_URL")
    if not connection_string:
        raise RuntimeError("Set REFERENCE_DB_URL in .env to query validation datasource.")
    return ReferenceSource(connection_string=connection_string)
