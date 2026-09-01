import json
from typing import List, Dict, Any, Optional

def format_discord_payload(alerts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Format alerts into Discord Webhook embed structure."""
    embeds = []
    for a in alerts:
        color = 0xFF0055 if a.get('severity') == 'CRITICAL' else (0xFFB800 if a.get('severity') == 'WARNING' else 0x4D9EFF)
        embeds.append({
            'title': a.get('title', 'Market Alert'),
            'description': a.get('detail', ''),
            'color': color,
            'fields': [
                {'name': 'Asset', 'value': a.get('asset', '—'), 'inline': True},
                {'name': 'Severity', 'value': a.get('severity', 'INFO'), 'inline': True},
                {'name': 'Timestamp', 'value': a.get('timestamp', '—'), 'inline': True}
            ]
        })
    return {'content': '🚨 **Institutional Quant Market Alert**', 'embeds': embeds}

def format_telegram_payload(alerts: List[Dict[str, Any]]) -> str:
    """Format alerts into Telegram Markdown format."""
    lines = ['🚨 *INSTITUTIONAL QUANT ALERTS*\n']
    for a in alerts:
        lines.append(f"*{a.get('severity')}:* {a.get('title')}")
        lines.append(f"{a.get('detail')}")
        lines.append(f"_Asset: {a.get('asset')} | {a.get('timestamp')}_\n")
    return '\n'.join(lines)

def format_line_notify_payload(alerts: List[Dict[str, Any]]) -> str:
    """Format alerts for LINE Notify message."""
    lines = ['\n[FUTURES OPTIONS ALERT]']
    for a in alerts:
        lines.append(f"[{a.get('severity')}] {a.get('title')}")
        lines.append(f"{a.get('detail')}")
    return '\n'.join(lines)
