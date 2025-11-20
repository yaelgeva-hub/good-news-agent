#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Good News Agent - Final corrected version
- Searches Google News RSS for uplifting stories in several categories & languages
- Translates titles + short summaries to Hebrew
- Sends an HTML digest (links + Hebrew summaries) via Gmail
- Designed to run in GitHub Actions (uses EMAIL_USER / EMAIL_PASSWORD / EMAIL_TO secrets)
"""

import os
import logging
import traceback
import hashlib
import datetime as dt
import time
import re

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib

# ---------------------- Logging ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------------- CONFIG ----------------------
CONFIG = {
    "queries": {
        # בעלי חיים — סיפורים מיוחדים/חיוביים
        "animals": [
            "rare animal birth",
            "rare animal discovery",
            "baby animals zoo",
            "unique animal behavior",
            "animal friendship unusual",
            "rare species sighting",
            "new species discovered",
        ],
        # תיירות — מקומות מיוחדים, מלונות ובתי אירוח
        "tourism": [
            "unique tourist destination",
            "new hotel opened",
            "special boutique hotel",
            "unique guesthouse",
            "new hiking trail opened",
            "rare village tourism",
            "new museum opens",
            "unique travel experience",
            "world heritage restored",
        ],
        # טבע — נופים, צמחים נדירים, תופעות טבע
        "nature": [
            "rare natural phenomenon",
            "unique landscape discovered",
            "rare plant discovered",
            "new national park area",
            "beautiful natural site",
            "unique geological formation",
            "stunning natural view",
        ],
        # מדע
        "science": [
            "positive scientific discovery",
            "new medical breakthrough hope",
            "technology improves life",
            "new space discovery exciting",
            "archaeological discovery rare",
        ],
        # תרבות
        "culture": [
            "ancient artifact discovered",
            "new museum opens",
            "unique art exhibition",
            "historic site restored",
            "rare cultural discovery",
        ],
        # השראה
        "inspiration": [
            "heartwarming story",
            "community success story",
            "inspiring achievement",
            "uplifting news",
            "good news story",
        ],
    },
    "languages": ["en", "es", "fr", "de", "pt", "ar"],
    "max_articles": 25,
    "min_compound": 0.05,
    "rss_timeout": 10,
    "summary_max_chars": 300,
}

# ---------------------- Email configuration (from environment / GitHub Secrets) ----------------------
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_TO:
    logging.warning("Email credentials not fully set in environment. Email sending will be skipped or fail if run.")

# ---------------------- Helpers & NLP ----------------------
analyzer = SentimentIntensityAnalyzer()


def clean_html_summary(html_text):
    """Strip HTML tags and normalize text."""
    if not html_text:
        return ""
    text = BeautifulSoup(html_text, "html.parser").get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def translate_text(text, target="he"):
    if not text:
        return ""
    try:
        return GoogleTranslator(source='auto', target=target).translate(text)
    except Exception as e:
        logging.debug(f"Translation to {target} failed: {e}")
        return text


def translate_to_en_safe(text):
    if not text:
        return ""
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception:
        return text


def score_sentiment(text):
    if not text:
        return 0.0
    try:
        scores = analyzer.polarity_scores(text)
        return scores.get("compound", 0.0)
    except Exception as e:
        logging.debug(f"VADER scoring failed: {e}")
        return 0.0


def hashlib_sha1(s):
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


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


# ---------------------- Fetch Google News RSS ----------------------
def fetch_google_news_rss(query, lang):
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
            items.append({"title": title, "description": desc, "link": link, "pubDate": pub, "lang": lang})
        return items
    except Exception as e:
        logging.warning(f"RSS fetch failed for '{query}' lang '{lang}': {e}")
        return []


# ---------------------- Build HTML digest (modern magazine style) ----------------------
def build_html_digest(articles):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<style>",
        "body{font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background:#f7f7f7; color:#111; direction:rtl; margin:0; padding:20px}",
        ".container{max-width:900px;margin:0 auto;background:#ffffff;padding:28px;border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,0.08)}",
        "header{border-bottom:1px solid #eee;padding-bottom:14px;margin-bottom:18px}",
        "h1{font-size:28px;margin:0;text-align:center;color:#222;font-weight:700}",
        ".lead{font-size:14px;color:#666;text-align:center;margin-top:6px}",
        ".sections{display:grid;grid-template-columns:1fr 320px;grid-gap:20px}",
        ".main{padding-right:6px}",
        ".aside{background:#fafafa;padding:12px;border-radius:6px;border:1px solid #f0f0f0}",
        ".article{margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid #eee}",
        ".title{font-size:18px;color:#0b3d91;margin:0 0 6px 0;font-weight:700}",
        ".meta{font-size:12px;color:#777;margin-bottom:6px}",
        ".summary{font-size:14px;color:#222;line-height:1.6;text-align:justify}",
        "a{color:#0b3d91;text-decoration:none;border-bottom:1px dotted rgba(11,61,145,0.15)}",
        "a:hover{text-decoration:underline}",
        "footer{margin-top:20px;padding-top:12px;border-top:1px solid #eee;font-size:12px;color:#666;text-align:center}",
        "@media (max-width:720px){.sections{grid-template-columns:1fr} .aside{order:2}}",
        "</style>",
        "</head><body>",
        "<div class='container'>",
        "<header>",
        f"<h1>Good News Digest</h1>",
        f"<div class='lead'>עדכון — {now} | חדשות טובות מהעולם בתרגום לעברית</div>",
        "</header>",
        "<div class='sections'>",
        "<div class='main'>",
    ]

    if not articles:
        parts.append("<p>לא נמצאו ידיעות מתאימות בזמן החיפוש. נסי להריץ שוב מאוחר יותר או הרחיבי את מילות החיפוש.</p>")
    else:
        for a in articles:
            title = a.get("title_he") or a.get("title") or "(ללא כותרת)"
            summary = a.get("summary_he") or a.get("summary") or ""
            link = a.get("link") or "#"
            pub = a.get("pubDate") or ""
            parts.extend([
                "<article class='article'>",
                f"<div class='title'><a href='{link}' target='_blank' rel='noopener noreferrer'>{title}</a></div>",
                f"<div class='meta'>{pub}</div>" if pub else "",
                f"<div class='summary'>{summary}</div>" if summary else "",
                "</article>",
            ])

    # aside with quick stats
    parts.extend([
        "</div>",
        "<aside class='aside'>",
        f"<h3 style='margin-top:0'>סקירה מהירה</h3>",
        f"<p>מספר ידיעות שנאספו: {len(articles)}</p>",
        "<p>קטלוג: " + ", ".join(CONFIG['queries'].keys()) + "</p>",
        "</aside>",
        "</div>",
        "<footer>",
        "<div>נוצר על-ידי Good News Agent — מייל יומי עם חדשות טובות</div>",
        "</footer>",
        "</div>",
        "</body></html>",
    ])

    return "\n".join(parts)


# ---------------------- Email send ----------------------
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
                            "summary_he": summary_he,
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
        err_html = f"<html><body><h3>Good News Agent - Error</h3><pre>{str(e)}\\n\\n{traceback.format_exc()}</pre></body></html>"
        with open("good_news_digest_error.html", "w", encoding="utf-8") as f:
            f.write(err_html)
        if EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO:
            try:
                send_email(err_html)
            except Exception:
                logging.debug("Failed to send error email")

    logging.info("Good News Agent finished")


# ---------------------- Entry point ----------------------
if __name__ == "__main__":
    run()
