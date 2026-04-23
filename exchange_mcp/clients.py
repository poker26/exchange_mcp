"""Single shared MailRouter instance. Import from here everywhere else."""
from __future__ import annotations

import logging

from .router import MailRouter

logger = logging.getLogger(__name__)

router = MailRouter()
