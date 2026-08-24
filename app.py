"""Telegram webhook bot for returning senior-company contacts from an authorized source.

This service deliberately does not scrape, log into, or automate LinkedIn.  Its CSV
provider is an adapter boundary: replace it with an approved provider's API client
when you have credentials and permission to use that data.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("senior-profile-bot")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
CSV_PATH = Path(os.getenv("CANDIDATES_CSV", "candidates.csv"))
ALLOWED_USERS = {
    value.strip() for value in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",") if value.strip()
}

if not BOT_TOKEN or "replace_with" in BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN is not configured; Telegram requests will fail until it is set.")

app = FastAPI(title="Senior Profile Finder")

STARTUP_TERMS = ("founder", "co-founder", "cofounder", "ceo", "cto", "vp engineering", "head of engineering")
MNC_TERMS = ("cto", "cio", "vp engineering", "vice president engineering", "director of engineering", "engineering manager", "principal engineer", "distinguished engineer")


@dataclass(frozen=True)
class Candidate:
    company: str
    name: str
    title: str
    profile_url: str
    source: str
    confidence: float
    current: bool


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def classify_company(company: str, requested: str | None) -> Literal["startup", "mnc"]:
    if requested in {"startup", "mnc"}:
        return requested
    # Default to startup-oriented roles when no reliable company metadata is supplied.
    # Users can override: /find Acme | mnc
    return "startup"


def load_candidates() -> list[Candidate]:
    if not CSV_PATH.exists():
        return []
    candidates: list[Candidate] = []
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            try:
                candidates.append(Candidate(
                    company=row["company"].strip(), name=row["name"].strip(),
                    title=row["title"].strip(), profile_url=row["profile_url"].strip(),
                    source=row.get("source", "Authorized provider").strip(),
                    confidence=float(row.get("confidence", 0)),
                    current=normalise(row.get("current", "true")) in {"true", "yes", "1"},
                ))
            except (KeyError, ValueError, AttributeError):
                logger.warning("Skipping invalid candidate row")
    return candidates


def score(candidate: Candidate, company: str, company_type: str) -> int:
    if not candidate.current or normalise(candidate.company) != normalise(company):
        return -1
    title = normalise(candidate.title)
    terms = STARTUP_TERMS if company_type == "startup" else MNC_TERMS
    role_score = max((len(term) for term in terms if term in title), default=0)
    if not role_score:
        return -1
    seniority = sum(term in title for term in ("chief", "founder", "vice president", "vp", "director", "head", "manager", "principal", "distinguished"))
    return role_score * 100 + seniority * 10 + round(candidate.confidence * 10)


def find_profiles(company: str, requested_type: str | None) -> tuple[str, list[Candidate]]:
    company_type = classify_company(company, requested_type)
    ranked = sorted(
        ((score(candidate, company, company_type), candidate) for candidate in load_candidates()),
        key=lambda item: item[0], reverse=True,
    )
    selected: list[Candidate] = []
    seen: set[str] = set()
    for candidate_score, candidate in ranked:
        identity = normalise(candidate.name)
        if candidate_score < 0 or identity in seen:
            continue
        selected.append(candidate)
        seen.add(identity)
        if len(selected) == 5:
            break
    return company_type, selected


def parse_request(text: str) -> list[tuple[str, str | None]]:
    text = re.sub(r"^/(find|start)(?:@\w+)?\s*", "", text, flags=re.I).strip()
    if not text:
        return []
    # A trailing type applies to every comma-separated company:
    # /find Company A, Company B | mnc
    names_part, separator, maybe_type = text.rpartition("|")
    global_type = normalise(maybe_type) if separator else None
    if global_type in {"startup", "mnc"}:
        return [(company.strip(), global_type) for company in names_part.split(",") if company.strip()]
    results = []
    for part in text.split(","):
        company = part.strip()
        if company:
            results.append((company, None))
    return results


def render(company: str, company_type: str, candidates: list[Candidate]) -> str:
    heading = f"{company} — {company_type.upper()}"
    if not candidates:
        return heading + "\nNo verified matches in the authorized data source."
    lines = [heading]
    for index, candidate in enumerate(candidates, 1):
        lines.extend((f"{index}. {candidate.name} — {candidate.title}", candidate.profile_url))
    if len(candidates) < 5:
        lines.append(f"Only {len(candidates)} verified match(es) were available.")
    return "\n".join(lines)


async def telegram_send(chat_id: int, text: str) -> None:
    if not BOT_TOKEN:
        return
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        response.raise_for_status()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    if not WEBHOOK_SECRET or not x_telegram_bot_api_secret_token or not hmac.compare_digest(WEBHOOK_SECRET, x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=403, detail="invalid webhook secret")
    update = await request.json()
    message = update.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    sender_id = str(message.get("from", {}).get("id", ""))
    text = message.get("text", "")
    if not chat_id or not isinstance(text, str):
        return {"ok": True}
    if ALLOWED_USERS and sender_id not in ALLOWED_USERS:
        await telegram_send(chat_id, "This bot is private.")
        return {"ok": True}
    requests = parse_request(text)
    if not requests:
        await telegram_send(chat_id, "Use: /find Company A, Company B | mnc\nTypes: startup or mnc.")
        return {"ok": True}
    replies = [render(company, *(find_profiles(company, kind))) for company, kind in requests]
    await telegram_send(chat_id, "\n\n".join(replies)[:4000])
    return {"ok": True}


@app.post("/admin/set-webhook")
async def set_webhook(request: Request) -> dict:
    """One-time setup endpoint; protect it with the same secret in an Authorization header."""
    if request.headers.get("authorization") != f"Bearer {WEBHOOK_SECRET}":
        raise HTTPException(status_code=401, detail="unauthorized")
    if not BOT_TOKEN or not WEBHOOK_SECRET or not PUBLIC_BASE_URL:
        raise HTTPException(status_code=500, detail="bot token, secret, and PUBLIC_BASE_URL are required")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": f"{PUBLIC_BASE_URL}/telegram/webhook", "secret_token": WEBHOOK_SECRET, "drop_pending_updates": True},
        )
        response.raise_for_status()
        return response.json()
