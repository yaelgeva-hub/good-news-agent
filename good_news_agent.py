#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Good News Agent - full version
- Searches Google News RSS for positive / uplifting stories in multiple categories & languages
- Translates titles + short summaries to Hebrew
- Sends an HTML digest (links + Hebrew summaries) via Gmail
- Designed to be run in GitHub Actions (uses EMAIL_USER / EMAIL_PASSWORD / EMAIL_TO secrets)
"""

import os
import logging
import traceback
import hashlib
import datetime
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib
import time
import re

# ---------------------- Logging ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------------- CONFIG ----------------------
CONFIG = {
    "queries": {
        # בעלי חיים — רק סיפורים מיוחדים/חיוביים, ללא חילוצים/שיקום
        "animals": [
            "rare animal birth",
            "rare animal discovery",
            "baby animals zoo",
            "unique animal behavior",
            "animal friendship unusual",
            "rare species sighting",
            "new species discovered"
        ],

        # תיירות — מקומות מיוחדים, מלונות ובתי אירוח ייחודיים, אטרקציות
        "tourism": [
            "unique tourist destination",
            "new hotel opened",
            "special boutique hotel",
            "unique guesthouse",
            "new hiking trail opened",
            "rare village tourism",
            "new museum opens",
            "unique travel experience",
            "world heritage restored"
        ],

        # טבע (לא חילוצים / לא ניקויים) — תופעות טבע, נופים, צמחים נדירים
        "nature": [
            "rare natural phenomenon",
            "unique landscape discovered",
            "rare plant discovered",
            "new national park area",
            "beautiful natural site",
            "unique geological formation",
            "stunning natural view"
        ],

        # מדע — חדשות חיוביות ומרגשות
        "science": [
            "positive scientific discovery",
            "new medical breakthrough hope",
            "technology improves life",
            "new space discovery exciting",
            "archaeological discovery rare"
        ],

        # תרבות — תערוכות, מוזיאונים, פריטים נדירים ושימור
        "culture": [
            "ancient artifact discovered",
            "new museum opens",
            "unique art exhibition",
            "historic site restored",
            "rare cultural discovery"
        ],

        # השראה — סיפורים מעוררי השראה (ללא חילוצים)
        "inspiration": [
            "heartwarming story",
            "community success story",
            "inspiring achievement",
            "uplifting news",
            "good news story"
        ],
    },
    "languages": ["en", "es", "fr", "de", "pt", "ar"],  # שפות לחיפוש
    "max_articles": 25,
    "min_compound": 0.05,  # יותר נדיב, יכלול יותר ידיעות חיוביות
    "rss_timeout": 10,
    "summary_max_chars": 280  # תקציר בעברית מקסימום תווים
}

# ---------------------- Email configuration (from environment / GitHub Secrets) ----------------------
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_TO:
    logging.warning("Email credentials not fully set in environment. Email sending will be skipped or fail if run.")

# ---------------------- Helpers ----------------------
analyzer = SentimentIntensityAnalyzer()

def clean_html_summary(html_text):
    """Strip HTML tags and decode entities, produce a short plaintext summary."""
    if not html_text:
        return ""
    # Remove tags
    text = BeautifulSoup(html_text, "html.parser").get_text(separator=" ", strip=True)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text

def translate_text(text, target="he"):
    """Translate text to target language (default Hebrew). Falls back to original on error."""
    if not text:
        return ""
    try:
        # Note: GoogleTranslator.auto-detects source
        return GoogleTranslator(source='auto', target=target).translate(text)
    except Exception as e:
        logging.debug("Translation failed (%s). Returning original.", e)
        return text

def translate_to_en(text):
    """Translate to English (for sentiment scoring)."""
    if not text:
        return ""
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception:
        return text

def score_sentiment(text):
    """Return compound sentiment score using VADER (expects English or close)."""
    if not text:
        return 0.0
    try:
        scores = analyzer.polarity_scores(text)
        return scores.get("compound", 0.0)
    except Exception as e:
        logging.debug("VADER scoring failed: %s", e)
        return 0.0

def dedupe_articles(articles):
    seen = set()
    out = []
    for a in articles:
        key_src = (a.get("link") or "") + (a.get("title") or "")
        key = hashlib_sha1(key_src)
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out

def hashlib_sha1(s):
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

# ---------------------- Fetching Google News RSS ----------------------
def fetch_google_news_rss(query, lang):
    """Fetch Google News RSS search results for a given query and language (hl param)."""
    try:
        q = requests.utils.quote(query)
        url = f"https://news.google.com/rss/search?q={q}&hl={lang}&gl=US&ceid=US:{lang}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; GoodNewsAgent/1.0)"}
        r = requests.get(url, timeout=CONFIG["rss_timeout"], headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "xml")
        items = []
        for item in soup.find_all("item"):
            title = item.title.text if item.title else ""
            desc = item.description.text if item.description else ""
            link = item.link.text if item.link else ""
            pub = item.pubDate.text if item.pubDate else ""
            items.append({
                "title": title,
                "description": desc,
                "link": link,
                "pubDate": pub,
                "lang": lang
            })
        return items
    except Exception as e:
        logging.warning("RSS fetch failed for '%s' lang '%s': %s", query, lang, e)
        return []

# ---------------------- Build digest HTML ----------------------
def build_html_digest(articles):
    now = datetime.datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><style>",
        "body{font-family:Arial;direction:rtl;color:#111}",
        ".article{margin-bottom:18px;padding-bottom:10px;border-bottom:1px solid #eee}",
        ".title{font-weight:700;font-size:16px;margin-bottom:6px}",
        ".meta{font-size:12px;color:#666;margin-bottom:6px}",
        ".summary{font-size:14px;margin-bottom:6px}",
        "a{color:#0b62d1;text-decoration:none}",
        "</style></head><body>",
        f"<h2>דוח חדשות טובות — {now}</h2>"
    ]
    if not articles:
        parts.append("<p>לא נמצאו ידיעות שמתאימות לקריטריונים בזמן החיפוש. נסי להריץ שוב או הרחיבי את מילות החיפוש.</p>")
    else:
        for a in articles:
            title = a.get("title_he") or a.get("title") or ""
            summary = a.get("summary_he") or a.get("summary") or ""
            link = a.get("link") or "#"
            pub = a.get("pubDate") or ""
            parts.append("<div class='article'>")
            parts.append(f"<div class='title'><a href='{link}' target='_blank'>{title}</a></div>")
            if pub:
                parts.append(f"<div class='meta'>{pub}</div>")
            if summary:
                parts.append(f"<div class='summary'>{summary}</div>")
            parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)

# ---------------------- Email sending (Gmail) ----------------------
def send_email(html):
    if not (EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO):
        logging.info("Email credentials not set; skipping email send.")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_TO
        msg["Subject"] = "Good News Digest"
        body = MIMEText("מצורף דוח החדשות הטובות להיום (לינקים ותקצירים).", "plain", "utf-8")
        msg.attach(body)
        attachment = MIMEApplication(html.encode("utf-8"), _subtype="html")
        attachment.add_header("Content-Disposition", "attachment", filename="good_news_digest.html")
        msg.attach(attachment)

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        logging.info("Email sent to %s", EMAIL_TO)
        return True
    except Exception as e:
        logging.error("Failed to send email: %s", e)
        logging.debug(traceback.format_exc())
        return False

# ---------------------- Main routine ----------------------
def run():
    logging.info("Good News Agent starting")
    collected = []
    try:
        for topic, queries in CONFIG["queries"].items():
            logging.info("Topic: %s", topic)
            for q in queries:
                # For each language:
                for lang in CONFIG["languages"]:
                    items = fetch_google_news_rss(q, lang)
                    # If no items, small sleep to avoid aggressive requests
                    if not items:
                        time.sleep(0.3)
                    for it in items:
                        title = it.get("title", "")
                        desc_html = it.get("description", "")
                        desc = clean_html_summary(desc_html)
                        link = it.get("link", "")
                        pub = it.get("pubDate", "")
                        if not title and not desc:
                            continue
                        # Score sentiment: translate to English first for reliability
                        text_for_sentiment = (title + " " + (desc or ""))[:2000]
                        en_text = translate_to_en_safe(text_for_sentiment)
                        score = score_sentiment(en_text)
                        if score < CONFIG["min_compound"]:
                            continue
                        # Prepare hebrew title + summary
                        title_he = translate_text(title, target="he")
                        # Shorten description and translate
                        short_desc = desc[:CONFIG["summary_max_chars"]]
                        summary_he = translate_text(short_desc, target="he") if short_desc else ""
                        collected.append({
                            "title": title,
                            "description": desc,
                            "summary": short_desc,
                            "link": link,
                            "pubDate": pub,
                            "score": score,
                            "title_he": title_he,
                            "summary_he": summary_he
                        })
                        logging.info("Collected (%s) score=%.3f title=%s", topic, score, title[:80])
                        if len(collected) >= CONFIG["max_articles"]:
                            break
                    if len(collected) >= CONFIG["max_articles"]:
                        break
                if len(collected) >= CONFIG["max_articles"]:
                    break
            if len(collected) >= CONFIG["max_articles"]:
                break

        # dedupe by title/link
        collected = dedupe_articles(collected)
        logging.info("Collected total: %d", len(collected))

        # build HTML
        html = build_html_digest(collected)
        # save local copy (artifact)
        with open("good_news_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        logging.info("Saved good_news_digest.html locally")

        # send email
        send_email(html)

    except Exception as e:
        logging.error("Unhandled exception: %s", e)
        logging.debug(traceback.format_exc())
        # create error artifact
        err_html = f"<html><body><h3>Good News Agent - Error</h3><pre>{str(e)}\n\n{traceback.format_exc()}</pre></body></html>"
        with open("good_news_digest_error.html", "w", encoding="utf-8") as f:
            f.write(err_html)
        if EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO:
            try:
                send_email(err_html)
            except Exception:
                logging.debug("Failed to send error email")

    logging.info("Good News Agent finished")

# ---------------------- Small helpers used above ----------------------
def translate_to_en_safe(text):
    if not text:
        return ""
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception:
        return text

# ---------------------- Entry point ----------------------
if __name__ == "__main__":
    run()
