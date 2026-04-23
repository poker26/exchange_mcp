"""Tool functions registered with FastMCP."""
from .folders import TOOLS as FOLDER_TOOLS
from .mail import TOOLS as MAIL_TOOLS
from .calendar import TOOLS as CALENDAR_TOOLS
from .contacts import TOOLS as CONTACT_TOOLS
from .attachments import TOOLS as ATTACHMENT_TOOLS

ALL_TOOLS = (
    FOLDER_TOOLS
    + MAIL_TOOLS
    + CALENDAR_TOOLS
    + CONTACT_TOOLS
    + ATTACHMENT_TOOLS
)

__all__ = ["ALL_TOOLS"]
