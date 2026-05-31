#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V228 TELEGRAM SEND CONNECTOR

목적:
- telegram_message.txt 내용을 실제 텔레그램으로 발송
- GitHub Secrets 사용:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID

입력:
- telegram_message.txt

출력:
- v228_telegram_send_result.json
- v228_telegram_send_result.txt
"""

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()

MESSAGE_FILE = ROOT / "telegram_message.txt"
OUT_JSON = ROOT / "v228_telegram_send_result.json"
OUT_TXT = ROOT / "v228_telegram_send_result.txt"

def now_text():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def write_result(status, message, response=None):
    result = {
        "version": "V228_TELEGRAM_SEND_CONNECTOR",
        "sentAt": now_text(),
        "status": status,
        "message": message,
        "telegramResponse": response,
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_TXT.write_text(
        f"V228 TELEGRAM SEND RESULT\n"
        f"==========================\n"
        f"status: {status}\n"
        f"sentAt: {result['sentAt']}\n"
        f"message: {message}\n"
        f"telegramResponse: {response}\n",
        encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        write_result("FAIL", "TELEGRAM_BOT_TOKEN GitHub Secret이 없습니다.")
        raise SystemExit(1)

    if not chat_id:
        write_result("FAIL", "TELEGRAM_CHAT_ID GitHub Secret이 없습니다.")
        raise SystemExit(1)

    if not MESSAGE_FILE.exists():
        write_result("FAIL", "telegram_message.txt 파일이 없습니다. V227 workflow를 먼저 실행하세요.")
        raise SystemExit(1)

    text = MESSAGE_FILE.read_text(encoding="utf-8").strip()

    if not text:
        write_result("FAIL", "telegram_message.txt 내용이 비어 있습니다.")
        raise SystemExit(1)

    # Telegram message limit is 4096 chars. Split safely.
    chunks = []
    while text:
        chunks.append(text[:3800])
        text = text[3800:]

    responses = []
    for idx, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            chunk = f"[{idx}/{len(chunks)}]\n" + chunk

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": "true",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                responses.append(json.loads(body))
        except Exception as e:
            write_result("FAIL", f"텔레그램 발송 실패: {e}", responses)
            raise SystemExit(1)

    ok = all(r.get("ok") for r in responses if isinstance(r, dict))
    if ok:
        write_result("SUCCESS", f"텔레그램 메시지 {len(chunks)}건 발송 완료", responses)
    else:
        write_result("FAIL", "텔레그램 응답이 ok가 아닙니다.", responses)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
