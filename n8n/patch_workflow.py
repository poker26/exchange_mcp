import json
from pathlib import Path

root = Path(__file__).parent
workflow_path = root / "exchange-emails-events-telegram-yandex.json"
format_events_js = (root / "format-events.js").read_text(encoding="utf-8")
format_emails_js = (root / "format-emails.js").read_text(encoding="utf-8")

data = json.loads(workflow_path.read_text(encoding="utf-8"))

delete_filter = {
    "parameters": {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
                "version": 1,
            },
            "conditions": [
                {
                    "id": "1",
                    "leftValue": "={{ $json.type }}",
                    "rightValue": "caldav_delete",
                    "operator": {
                        "type": "string",
                        "operation": "equals",
                    },
                }
            ],
            "combinator": "and",
        },
        "options": {},
    },
    "id": "a1b2c3d4-0021-4000-8000-000000000021",
    "name": "Has CalDAV Delete?",
    "type": "n8n-nodes-base.filter",
    "typeVersion": 2,
    "position": [0, 680],
}

delete_node = {
    "parameters": {
        "method": "DELETE",
        "url": "=https://caldav.yandex.ru/calendars/superkerogaz%40yandex.ru/events-default/{{ $json.uid }}.ics",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpBasicAuth",
        "options": {
            "response": {
                "response": {
                    "responseFormat": "text",
                }
            },
            "timeout": 15000,
        },
    },
    "id": "a1b2c3d4-0022-4000-8000-000000000022",
    "name": "CalDAV DELETE from Yandex",
    "type": "n8n-nodes-base.httpRequest",
    "typeVersion": 4.2,
    "position": [280, 680],
    "credentials": {
        "httpBasicAuth": {
            "id": "xMgPynwFvCerpDZe",
            "name": "Yandex CalDAWS",
        }
    },
}

for node in data["nodes"]:
    if node["name"] == "Format Events":
        node["parameters"]["jsCode"] = format_events_js
    if node["name"] == "Format Emails":
        node["parameters"]["jsCode"] = format_emails_js
    if node["name"] == "Sticky Note":
        node["parameters"]["content"] = (
            "## Настройка\n\n"
            "- **MCP**: `http://46.173.19.68:8903/mcp/`, **Header Auth Exchange_work**\n"
            "- **CalDAV**: добавление / изменение (PUT) + отмена (DELETE)\n"
            "- **Первый запуск**: `is_initial` — прогрев state, без TG/CalDAV"
        )

names = {node["name"] for node in data["nodes"]}
if "Has CalDAV Delete?" not in names:
    data["nodes"].extend([delete_filter, delete_node])

data["connections"]["Format Events"] = {
    "main": [
        [
            {"node": "Has Event TG?", "type": "main", "index": 0},
            {"node": "Has CalDAV?", "type": "main", "index": 0},
            {"node": "Has CalDAV Delete?", "type": "main", "index": 0},
        ]
    ]
}
data["connections"]["Has CalDAV Delete?"] = {
    "main": [[{"node": "CalDAV DELETE from Yandex", "type": "main", "index": 0}]]
}

workflow_path.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("patched workflow")
