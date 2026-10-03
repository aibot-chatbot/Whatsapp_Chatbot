"""seo_routes.py - Crawler files: robots.txt, sitemap.xml and llms.txt.

Served from code, not as files under frontend/, because the container only admits
.html/.css/.js from frontend/ (tests/test_container_release.py). URLs come from
FRONTEND_URL so a domain change moves every crawler file with it.

The plan facts in llms.txt mirror the landing page cards; tests/test_seo_routes.py
fails if a Ringgit amount here is not one the billing system charges.
"""

from flask import Blueprint, Response, current_app

seo_blueprint = Blueprint("seo", __name__)

# The only pages a crawler may index. Everything else (the signed-in app, /api/,
# /media/, tenant widget pages) stays closed: this is an allow-list, so a new
# app page is hidden until someone lists it here on purpose.
SITEMAP_PATHS = ("/", "/privacy.html", "/terms.html")
_CACHE = "public, max-age=3600"

_ROBOTS = """\
# Public marketing and legal pages are open to search engines and AI crawlers.
# Everything else is closed. robots.txt is a crawl request, not access control:
# private data is protected by authentication, never by this file.
# Allow lines come before the final "Disallow: /" so first-match parsers agree
# with RFC 9309 longest-match parsers.

# Search engines
User-agent: Googlebot
User-agent: Bingbot
User-agent: Applebot
# AI search and user-requested fetches (these produce citations)
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: Claude-SearchBot
User-agent: Claude-User
User-agent: PerplexityBot
# AI training. To opt out, move these four into their own group with "Disallow: /".
User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
# Every other crawler
User-agent: *
Allow: /$
Allow: /landing.html
Allow: /privacy.html
Allow: /terms.html
Allow: /register.html
Allow: /login.html
Allow: /llms.txt
Allow: /sitemap.xml
Allow: /assets/
Allow: /widget.js
Disallow: /api/
Disallow: /media/
Disallow: /

Sitemap: {site}/sitemap.xml
"""

_LLMS = """\
# Omnexa

> Omnexa is a WhatsApp AI chatbot for Malaysian businesses. It answers customer messages on WhatsApp, Telegram and a website chat widget using the business's own documents and web pages, and includes a built-in CRM, broadcasts and booking requests in chat. Plans are billed monthly in Malaysian Ringgit (MYR).

Omnexa is operated by a private limited company (Sdn Bhd) registered in Malaysia.

## Channels

- WhatsApp through the official WhatsApp Cloud API. The business connects its own number through Meta embedded signup; a Meta Business account is required.
- WhatsApp through a Wasender session.
- Telegram. Only a Telegram bot token is required.
- A chat widget for the business's own website, plus a shareable chat link. Neither uses a channel slot.
- Instagram, Facebook, X and LinkedIn are in development and are not included in any plan.

## Key features

- AI replies grounded in documents the business uploads and web pages it adds, not general knowledge.
- Built-in CRM: every conversation writes back to a customer record with tags, status and staff assignment.
- Broadcasts to WhatsApp and Telegram audiences, sent immediately or scheduled, segmented by CRM tag.
- Booking requests collected inside the chat; staff confirm them and download the list as CSV.
- One inbox where staff can read and reply to any conversation.

## Plans (price per month, MYR)

- Free, RM 0: a 7-day free trial only, for new accounts, no card required. 1 bot, 1 channel, 1 seat, 3 knowledge files (50 MB), RM 1 AI credit for the trial, 1 entry AI model. AI replies stop when the trial ends unless the account moves to a paid plan.
- Essential, RM 39: 1 bot, 1 channel, 1 seat, 5 knowledge files (50 MB), RM 5 AI credit, AI models GPT-6 Luna and Gemini 3.8 Flash.
- Advanced, RM 89: 2 bots, 2 channels, 3 seats, 25 knowledge files (250 MB), RM 20 AI credit, AI models GPT-6 Luna, Gemini 3.8 Flash and Claude Haiku 4.5.
- Pro, RM 169: 3 bots, 2 channels, 5 seats, 75 knowledge files (1 GB), RM 60 AI credit, AI models GPT-6.1 Sol, Claude Sonnet 5.5 and Gemini 3.1 Pro.

Every paid plan includes a monthly AI credit allowance; usage beyond it is billed separately. Higher plans add features such as an AI-derived bot persona, conversation memory, CRM lead assignment, website scraping, AI-assisted menu generation, AI-generated reports and automation workflows. The pricing section lists them per plan.

## Pages

- [Overview]({site}/): channels, features, pricing and FAQ
- [Pricing]({site}/#pricing): the four plans and what each includes
- [Privacy policy]({site}/privacy.html): how personal data is collected, used and protected, in English and Bahasa Malaysia
- [Terms]({site}/terms.html): terms for registering for and using Omnexa

## Optional

- [Create an account]({site}/register.html)
- [Sign in]({site}/login.html)
"""


def _site():
    return current_app.config["FRONTEND_URL"].rstrip("/")


def _text(body, mimetype):
    response = Response(body, mimetype=mimetype)
    response.headers["Cache-Control"] = _CACHE
    return response


@seo_blueprint.get("/robots.txt")
def robots_txt():
    return _text(_ROBOTS.format(site=_site()), "text/plain")


@seo_blueprint.get("/llms.txt")
def llms_txt():
    return _text(_LLMS.format(site=_site()), "text/markdown")


@seo_blueprint.get("/sitemap.xml")
def sitemap_xml():
    site = _site()
    urls = "".join(f"  <url><loc>{site}{path}</loc></url>\n" for path in SITEMAP_PATHS)
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n")
    return _text(body, "application/xml")
