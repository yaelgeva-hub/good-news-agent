# -*- coding: utf-8 -*-
"""
Good News Agent - updated to silently skip empty or inaccessible feeds
- Fetches positive stories from multiple RSS and Atom feeds
- Handles duplicate links
- Translates titles + summaries to Hebrew
- Sends HTML digest via Gmail
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
import re


# ---------------------- Logging ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# ---------------------- CONFIG ----------------------
CONFIG = {
"languages": ["en"],
"max_articles": 25,
"min_compound": 0.05,
"summary_max_chars": 280,
"rss_feeds": [
"https://www.smithsonianmag.com/rss/travel",
"https://www.smithsonianmag.com/rss/science-nature",
"https://www.smithsonianmag.com/rss/arts-culture",
"https://www.smithsonianmag.com/rss/innovation",
"https://www.optimistdaily.com/feed",
"https://www.goodnewsnetwork.org/feed/",
"https://www.thegoodnewsmovement.com/feed/",
"https://thegoodnewsherald.wordpress.com/feed/",
"https://feeds-api.dotdashmeredith.com/v1/rss/google/90b927aa-066f-4f66-9162-a018ad8ea366",
"http://www.shampooandbooze.com/feeds/posts/default?alt=rss"
]
}
CONFIG["rss_feeds"] = list(dict.fromkeys(CONFIG["rss_feeds"]))


# ---------------------- Email ----------------------
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")


if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_TO:
logging.warning("Email credentials not fully set in environment. Email sending may fail.")


# ---------------------- Helpers ----------------------
analyzer = SentimentIntensityAnalyzer()


def clean_html_summary(html_text):
if not html_text:
return ""
text = BeautifulSoup(html_text, "html.parser").get_text(separator=" ", strip=True)
return re.sub(r"\s+", " ", text).strip()


def translate_text(text, target="he"):
if not text:
return ""
try:
return GoogleTranslator(source='auto', target=target).translate(text)
except Exception:
return text


def score_sentiment(text):
if not text:
return 0.0
