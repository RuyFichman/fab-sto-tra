"""Alertas do paper trading: notificação do Windows e, se configurado, Telegram.

O Telegram só é usado quando token e chat_id estão no config.toml ou nas
variáveis QUANTLAB_TELEGRAM_TOKEN / QUANTLAB_TELEGRAM_CHAT_ID. Falha de alerta
nunca interrompe o paper.
"""
from __future__ import annotations

import os
import subprocess

_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $xml.GetElementsByTagName('text')
$t.Item(0).AppendChild($xml.CreateTextNode($env:QL_TITLE)) | Out-Null
$t.Item(1).AppendChild($xml.CreateTextNode($env:QL_BODY)) | Out-Null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notify(cfg: dict, title: str, body: str) -> list[str]:
    """Envia pelos canais configurados. Retorna os erros, sem levantar exceção."""
    a, errors = cfg.get("alerts", {}), []
    if a.get("windows_toast") and os.name == "nt":
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", _TOAST], timeout=30, check=True,
                           capture_output=True, env={**os.environ, "QL_TITLE": title, "QL_BODY": body})
        except Exception as e:
            errors.append(f"notificação do Windows: {type(e).__name__}")
    token = a.get("telegram_token") or os.environ.get("QUANTLAB_TELEGRAM_TOKEN")
    chat = a.get("telegram_chat_id") or os.environ.get("QUANTLAB_TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            import requests

            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                          json={"chat_id": chat, "text": f"{title}\n{body}"}).raise_for_status()
        except Exception as e:
            errors.append(f"Telegram: {type(e).__name__}")
    return errors
