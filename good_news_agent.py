#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import datetime
import hashlib
import time
import traceback
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------------- Configuration ----------------------
CONFIG = {
    # Categories / queries to search (expand as needed)
    "queries": {
        "animals": ["animal rescue", "pets saved", "wildlife rescued"],
        "weather": ["sunny weekend", "mild temperatures", "rain ends", "storm cleared"],
        "housing": ["affordable housing", "new housing plan", "rent relief", "housing grants"],
        "tourism": ["new tourist attraction", "new route opened", "tourism recovery"]
    },
    # languages to try when searching Google News RSS (hl / gl params)
    "languages": ["en", "es", "fr", "de", "pt", "ar"],
    "max_articles": 12,
    "min_compound": 0.15,  # VADER threshold for "positive"
    "rss_timeout": 10
}

# Read email config from environment (set as GitHub Secrets)
EMAIL_USER = os.getenv("EMAIL_USER") or os.getenv("EMAIL_USER".upper())
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD".upper())
EMAIL_TO = os.getenv("EMAIL_TO") or os.getenv("EMAIL_TO".upper())

if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_TO:
    logging.warning("EMAIL_USER / EMAIL_PASSWORD / EMAIL_TO are not all defined in environment. Email will be skipped.")


# ---------------------- Helpers ----------------------
analyzer = SentimentIntensityAnalyzer()

def translate_text(text, target="en"):
    if not text:
        return ""
    try:
        # GoogleTranslator can auto-detect source
        return GoogleTranslator(source='auto', target=target).translate(text)
    except Exception as e:
        logging.debug(f"Translation to {target} failed: {e}")
        return text

def fetch_google_news_rss(query, lang):
    """
    Fetch Google News RSS search results for a query and language (hl param).
    Returns list of dicts: {title, description, link, pubDate}
    """
    try:
        q = requests.utils.quote(query)
        # Use gl=US to be broad; hl controls language of results
        url = f"https://news.google.com/rss/search?q={q}&hl={lang}&gl=US&ceid=US:{lang}"
        logging.debug(f"Fetching RSS: {url}")
        r = requests.get(url, timeout=CONFIG["rss_timeout"], headers={"User-Agent": "Mozilla/5.0"})
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
        logging.warning(f"RSS fetch failed for query '{query}' lang '{lang}': {e}")
        return []


def dedupe_articles(articles):
    seen = set()
    out = []
    for a in articles:
        key_src = (a.get("link") or "") + (a.get("title") or "")
        key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out

def is_positive_article(title, description, src_lang='auto'):
    """
    Return (bool, compound_score). We try to translate to English for VADER if needed.
    """
    text = " ".join(filter(None, [title, description]))
    if not text.strip():
        return False, 0.0
    try:
        # translate to English for sentiment scoring
        en = translate_text(text, target="en")
        scores = analyzer.polarity_scores(en)
        compound = scores.get("compound", 0.0)
        return compound >= CONFIG["min_compound"], compound
    except Exception as e:
        logging.debug(f"Sentiment check failed: {e}")
        return False, 0.0

def build_html_digest(articles):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><style>body{font-family:Arial;direction:rtl} .article{margin-bottom:18px;padding-bottom:8px;border-bottom:1px solid #ddd}</style></head><body>",
        f"<h2>דוח חדשות טובות — {now}</h2>"
    ]
    if not articles:
        html_parts.append("<p>לא נמצאו חדשות טובות בזמן החיפוש. שיניתי את מאגרי החיפוש, נסה להריץ שוב מאוחר יותר.</p>")
    else:
        for a in articles:
            title = a.get("title_he") or a.get("title") or ""
            desc = a.get("description_he") or a.get("description") or ""
            link = a.get("link") or "#"
            pub = a.get("pubDate") or ""
            html_parts.append("<div class='article'>")
            html_parts.append(f"<div><a href='{link}' target='_blank' style='font-size:16px;font-weight:700'>{title}</a></div>")
            if pub:
                html_parts.append(f"<div style='font-size:12px;color:#666'>{pub}</div>")
            if desc:
                html_parts.append(f"<div style='margin-top:6px'>{desc}</div>")
            html_parts.append("</div>")
    html_parts.append("</body></html>")
    return "\n".join(html_parts)

def send_email(html):
    if not (EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO):
        logging.info("Email credentials not set — skipping email send.")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_TO
        msg["Subject"] = "Good News Digest"
        text_part = MIMEText("מצורף דוח החדשות הטובות להיום.", "plain", "utf-8")
        msg.attach(text_part)
        attachment = MIMEApplication(html.encode("utf-8"), _subtype="html")
        attachment.add_header("Content-Disposition", "attachment", filename="good_news_digest.html")
        msg.attach(attachment)

        # connect to Gmail SMTP
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        logging.info("Email sent successfully to %s", EMAIL_TO)
        return True
    except Exception as e:
        logging.error("Failed to send email: %s", e)
        logging.debug(traceback.format_exc())
        return False


# ---------------------- Main ----------------------

def run():
    logging.info("Starting Good News Agent")
    collected = []
    try:
        for topic, queries in CONFIG["queries"].items():
            logging.info("Searching topic: %s", topic)
            for q in queries:
                for lang in CONFIG["languages"]:
                    items = fetch_google_news_rss(q, lang)
                    for it in items:
                        title = it.get("title", "")
                        desc = it.get("description", "")
                        link = it.get("link", "")
                        pub = it.get("pubDate", "")
                        lang_tag = it.get("lang", lang)
                        positive, score = is_positive_article(title, desc, src_lang=lang_tag)
                        if positive:
                            # translate title/desc to Hebrew for presentation
                            try:
                                title_he = translate_text(title, target="he")
                            except Exception:
                                title_he = title
                            try:
                                desc_he = translate_text(desc, target="he")
                            except Exception:
                                desc_he = desc
                            collected.append({
                                "title": title,
                                "description": desc,
                                "link": link,
                                "pubDate": pub,
                                "score": score,
                                "title_he": title_he,
                                "description_he": desc_he
                            })
                            logging.info("Collected positive: %s (%s)", title[:80], score)
                            if len(collected) >= CONFIG["max_articles"]:
                                break
                    if len(collected) >= CONFIG["max_articles"]:
                        break
                if len(collected) >= CONFIG["max_articles"]:
                    break
            if len(collected) >= CONFIG["max_articles"]:
                break
        collected = dedupe_articles(collected)
        logging.info("Total positive articles collected: %d", len(collected))
        html = build_html_digest(collected)
        # save locally (for debug / artifact)
        with open("good_news_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        logging.info("Saved good_news_digest.html")

        # send email
        send_email(html)

    except Exception as e:
        logging.error("Unhandled exception: %s", e)
        logging.debug(traceback.format_exc())
        # still try to save an error HTML for debugging
        err_html = "<html><body><h3>Good News Agent - Error</h3><pre>{}</pre></body></html>".format(
            str(e) + "\n\n" + traceback.format_exc()
        )
        with open("good_news_digest_error.html", "w", encoding="utf-8") as f:
            f.write(err_html)
        if EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO:
            try:
                send_email(err_html)
            except Exception:
                logging.debug("Failed sending error email.")
    logging.info("Finished run.")

if __name__ == "__main__":
    run()
