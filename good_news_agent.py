import requests
import yaml
from dateutil import parser
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import datetime
import os

###############################################
# Good News Agent
# Fetches positive news every morning, translates to Hebrew,
# sends to email (Gmail) and optionally to Telegram.
###############################################

# ---------------------- Configuration ----------------------
CONFIG_FILE = "config.yml"
