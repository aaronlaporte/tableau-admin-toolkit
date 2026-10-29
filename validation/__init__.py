"""
Validation utilities for comparing Tableau dashboards against alternate data sources.
"""

from .config import ValidationConfig, load_validation_config

__all__ = ["ValidationConfig", "load_validation_config"]
