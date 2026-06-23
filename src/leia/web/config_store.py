"""DB-backed ICP override so the web Settings editor survives redeploys.

On a hosted, ephemeral filesystem we can't reliably write config/icp.yaml, so the
edited ICP is stored in the ``app_config`` table (key="icp_yaml"). Reads prefer the
DB value and fall back to the bundled YAML file for the first-run default.
"""

from __future__ import annotations

import yaml
from sqlalchemy.orm import Session

from leia.config import ICPConfig, load_icp
from leia.models import AppConfig

ICP_KEY = "icp_yaml"


def get_effective_icp(session: Session, file_path: str = "config/icp.yaml") -> ICPConfig:
    row = session.get(AppConfig, ICP_KEY)
    if row and row.value:
        return ICPConfig.model_validate(yaml.safe_load(row.value))
    return load_icp(file_path)


def save_icp(session: Session, cfg: ICPConfig) -> None:
    text = yaml.safe_dump(cfg.model_dump(), sort_keys=False, allow_unicode=True)
    row = session.get(AppConfig, ICP_KEY)
    if row:
        row.value = text
    else:
        session.add(AppConfig(key=ICP_KEY, value=text))
    session.commit()
