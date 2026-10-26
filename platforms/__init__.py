"""
Platforms package for MCPCONECCT.
"""
from typing import Dict
from platforms.base import AcademicPlatform
from platforms.scopus import ScopusPlatform
from platforms.ieee import IeeePlatform
from platforms.wos import WosPlatform
from platforms.springer import SpringerPlatform


PLATFORMS: Dict[str, AcademicPlatform] = {
    "scopus": ScopusPlatform(),
    "ieee": IeeePlatform(),
    "wos": WosPlatform(),
    "springer": SpringerPlatform(),
}


def get_platform(name: str) -> AcademicPlatform:
    clean_name = name.lower().strip()
    if clean_name not in PLATFORMS:
        raise ValueError(f"Unsupported database '{name}'. Supported databases: {list(PLATFORMS.keys())}")
    return PLATFORMS[clean_name]
