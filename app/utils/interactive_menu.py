import json
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class InteractiveButton:
    id: str
    title: str

@dataclass
class InteractiveMenu:
    body: str
    title: Optional[str] = None
    footer: Optional[str] = None
    buttons: List[InteractiveButton] = field(default_factory=list)

    def to_dict(self):
        return {
            "type": "interactive_menu",
            "title": self.title,
            "body": self.body,
            "footer": self.footer,
            "buttons": [{"id": b.id, "title": b.title} for b in self.buttons]
        }
