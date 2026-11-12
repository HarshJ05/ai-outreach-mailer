# AI Outreach Mailer

Send personalized outreach emails from your company's official mail id to a list
of people in an Excel/CSV file. Each email is written for that person by AI
(Gemini first, Grok if Gemini is busy or failing, a plain template if both fail),
checked for mistakes, and sent slowly enough to stay out of spam.

Works for any company: your name, offer, prices, links and tone all live in `config.yaml`.

```
recipients.xlsx → load & clean → skip sent/unsubscribed → AI writes email
   (Gemini → Grok → template) → safety check → HTML + text email → SMTP send → log
```

![tests](https://github.com/HarshJ05/ai-outreach-mailer/actions/workflows/tests.yml/badge.svg)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

### Highlights

- **Multi-provider LLM failover**: Gemini → Grok → template, with per-provider rate-limit cooldown and exponential-backoff retries, so a run never stalls on one API.
- **Output guardrails**: every AI email is validated before sending: required link and code present, no leftover placeholders, no invented money figures (multi-currency parser), no misleading claims to new leads.
- **Idempotent, resumable sends**: a per-campaign sent log means a crash or re-run never emails anyone twice; daily cap and throttling with jitter protect sender reputation.
- **Flexible ingestion**: `.xlsx` / `.xls` / `.csv` in any encoding, header aliases (e.g. "Email ID", "e-mail", "Mail"), email validation and de-duplication.
- **Deliverability and compliance built in**: multipart HTML + text, `List-Unsubscribe` header, unsubscribe list, footer with postal address.
- **Production-ready**: config-driven (no code changes per company), Docker image, GitHub Actions CI, 40 offline tests with mocked AI and SMTP.

**Tech:** Python · pandas · Google Gemini API · xAI Grok API (OpenAI-compatible) · smtplib · Jinja2 · tenacity · rich · pytest · Docker · GitHub Actions

---

## 1. Setup (one time, ~10 minutes)

```bash
git clone https://github.com/HarshJ05/ai-outreach-mailer.git
cd ai-outreach-mailer
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

Open `.env` and fill in:

| Setting | Where to get it |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| `XAI_API_KEY` | https://console.x.ai |
| `SMTP_USER` / `FROM_EMAIL` | Your company's official mail id, e.g. `hello@yourcompany.com` |
| `SMTP_PASSWORD` | **Gmail / Google Workspace App Password**: Google Account → Security → 2-Step Verification (turn on) → App passwords → create one. Paste the 16-letter code. Never the normal password. |
| `COMPANY_ADDRESS` | Your postal address (shown in the footer, required by anti-spam laws) |
| `UNSUBSCRIBE_EMAIL` | Inbox where people reply "unsubscribe" |

Not on Google? Zoho: `smtp.zoho.in` port `587`. Outlook/365: `smtp.office365.com` port `587`.
Port `465`? Set `SMTP_SECURITY=ssl`.

Check everything works:

```bash
python -m src.main --check
```

You should see a green tick for Gemini, Grok, and SMTP. If a model name is rejected,
run `python -m src.main --list-models` and put a valid name in `config.yaml`.

---

## 2. Set up your company and offer: `config.yaml`

```yaml
company:
  name: "Acme Growth"
  website: "https://example.com"
  what_we_do: "a marketing platform that helps small businesses get more customers"
  sender_name: "Your Name"
  sender_title: "Team Acme Growth"

campaign:
  name: "launch_offer"            # change for every new campaign
  hook: "₹10K in ads. ₹1.4L in revenue. 3 days."
  proof: "That's one client's reported result."
  steps: "research competitor ads, launch your campaign, optimise 24/7"
  offer: "Get the Starter Plan for ₹2,000 instead of ₹4,999 for your first month."
  bonus: "We'll set up your first campaign FREE!"
  discount_code: "WELCOME50"
  cta_link: "https://example.com/#pricing"
  closing: "Let's get you more customers!"
```

Required: `company.name`, `campaign.hook`, `campaign.offer`, `campaign.cta_link`.
Everything else is optional (use `""` to leave it out).

**Ready-made example:** `examples/northwind-ads.yaml` is a full config for a fictional AI ads company.
Run any command with `--config examples/northwind-ads.yaml` to use it, or copy it as a starting point.
Keep one config file per company or campaign and pick it with `--config`.

---

## 3. Prepare the spreadsheet

Put your file in `data/` (git-ignored, so customer data never reaches GitHub).
Open `data/recipients.example.xlsx` to see the format.

| Column | Required | Notes |
|---|---|---|
| Email / Email ID / Mail | ✅ | Invalid and duplicate emails are skipped automatically |
| Name / First Name | recommended | Used in "Hi Aarav," |
| Company, Industry, City | optional | AI uses these to personalize |
| Segment | optional | `cold` (default) or `existing` |
| Personal Link | only for `existing` | That customer's own link (e.g. reconnect / login URL) |
| Any other column | optional | Passed to the AI as extra context |

Header names are flexible (`Email ID`, `e-mail`, `Mail` all work). Add aliases in `config.yaml → columns`.
Excel `.xlsx`, old `.xls` and `.csv` (any encoding) are supported.

### Segments: new leads vs existing customers

| Segment | Who | Gets `segments.existing_line`? |
|---|---|---|
| `cold` | New leads who have never used your product | **No.** The safety checker blocks words like "disconnected" or "your account" (`segments.cold_forbidden_words`), because telling a stranger their account has a problem is false and gets your domain flagged as phishing. |
| `existing` (or `lapsed`) | Real customers | **Yes**, with their personal link, e.g. *"Your account got disconnected. Reconnect in 1 minute: {link}"* |

A row marked `existing` without a personal link is treated as `cold`.

---

## 4. Run a campaign

```bash
# 1. Look at a few emails (nothing sent)
python -m src.main --file data/recipients.xlsx --preview 3

# 2. Send ONE sample to yourself and check it lands in Primary, not Spam
python -m src.main --file data/recipients.xlsx --test-to you@gmail.com

# 3. Dry run the whole list. Saves .eml previews to logs/previews/
python -m src.main --file data/recipients.xlsx

# 4. Send for real (asks you to type YES)
python -m src.main --file data/recipients.xlsx --send --limit 20
```

**Safe to re-run.** Everyone already sent in this campaign is skipped, so after a crash,
Ctrl+C, or hitting the daily cap, just run the same command again.

### All options

| Flag | What it does |
|---|---|
| `--file PATH` | Recipients file (.xlsx, .xls, .csv) |
| `--config PATH` | Use a different config (default `config.yaml`) |
| `--preview N` | Print N emails and stop |
| `--test-to EMAIL` | Send one sample to yourself |
| `--send` | Actually send (default is dry run) |
| `--yes` | Skip the YES prompt (for scheduled runs) |
| `--limit N` | Only the first N eligible people |
| `--no-ai` | Use the plain template for everyone (no API cost) |
| `--check-dns` | Also check each email's domain exists |
| `--check` | Test API keys and SMTP login |
| `--list-models` | Show model names your keys can use |
| `--unsubscribe a@x.com b@y.com` | Add people to the never-email list |

---

## 5. Changing the email

| What | Where |
|---|---|
| Company, offer, prices, code, link, hook, sender | `config.yaml` |
| Extra AI rules (tone, language, words to avoid) | `config.yaml → campaign.extra_instructions` |
| Full AI instructions | `templates/base_prompt.txt` |
| Email used when AI is unavailable | `templates/fallback.txt` |
| Look of the HTML email | `templates/email.html.j2` |
| Speed and daily limit | `config.yaml → sending` |

### Safety checks (every email, AI or template)
An AI email is thrown away (and the next provider tried) if it:
- is missing the call-to-action link or discount code,
- doesn't use the person's first name, or leaves a placeholder like `[first name]`,
- contains any money amount (₹, Rs, INR, $, €, £) that isn't already in your config, so no invented results,
- says "guaranteed", "100%", or "risk-free",
- uses a `cold_forbidden_words` word in an email to a new lead,
- is too short, too long, or has an empty/overlong subject.

The footer (signature, unsubscribe line, address) and the `List-Unsubscribe`
header are always added by code, never by the AI.

---

## 6. How the AI load balancing works

`config.yaml → ai.provider_order: [gemini, grok]`

1. Each email goes to **Gemini** first.
2. If Gemini says *rate limited* (429), it **cools down** for `cooldown_seconds`
   and every email goes to **Grok** until the cooldown ends.
3. Other errors are retried (`max_retries_per_provider`) with backoff, then Grok is tried.
4. If the AI writes something that fails the safety checks, the next provider is tried.
5. If everything fails, the plain **template** is used, so nobody is skipped.

The summary at the end shows how many emails each provider wrote. To add another
provider (OpenAI, Claude, ...), add a class in `src/providers/` and its name to `provider_order`.

---

## 7. Staying out of spam (do this before the first big send)

1. **SPF, DKIM, DMARC** on your domain. Google Workspace: Admin console → Apps →
   Google Workspace → Gmail → Authenticate email → generate DKIM and add the DNS record.
   Add a DMARC TXT record: `_dmarc.yourcompany.com` → `v=DMARC1; p=none; rua=mailto:hello@yourcompany.com`.
2. **Warm up.** Day 1: 20 emails, day 2: 40, day 3: 80, then grow slowly. Use `--limit`.
3. **Limits.** Gmail ≈ 500/day, Google Workspace ≈ 2,000/day. `daily_cap` (default 400) protects you.
4. **Honour unsubscribes** within a day: `python -m src.main --unsubscribe person@x.com`.
5. Only email people with a genuine reason to hear from you.
6. Going above ~500/day? Use a bulk email service (Brevo, Amazon SES, Resend). Most
   give SMTP details, so you only change `.env`; or add an API sender in `src/sender.py`.

---

## 8. Docker

```bash
docker build -t ai-outreach-mailer .
docker run --rm --env-file .env \
  -v "$(pwd)/data:/app/data" -v "$(pwd)/logs:/app/logs" \
  ai-outreach-mailer --file data/recipients.xlsx --preview 3
```

Send daily on a server (cron, 10:00 every weekday):
```
0 10 * * 1-5 cd /opt/ai-outreach-mailer && docker run --rm --env-file .env -v $PWD/data:/app/data -v $PWD/logs:/app/logs ai-outreach-mailer --file data/recipients.xlsx --send --yes >> logs/cron.log 2>&1
```
With the daily cap and the "already sent" log, this sends the next batch each day until the list is done.

---

## 9. Files

```
config.yaml             your company, offer, AI and sending settings
examples/northwind-ads.yaml   a complete example config (fictional company)
src/main.py             CLI and the full pipeline
src/config.py           loads config.yaml + .env, checks required fields
src/loader.py           reads Excel/CSV, cleans emails, finds columns
src/personalizer.py     Gemini → Grok → template, with cooldown + retries
src/providers/          one file per AI provider
src/validator.py        safety checks
src/renderer.py         builds the HTML + text email, footer, headers
src/sender.py           SMTP sending, throttling, retries
src/tracker.py          logs/sent_log.csv and logs/unsubscribed.txt
tests/                  run `pytest`; no API keys needed
```

`logs/sent_log.csv` has one row per email (time, email, status, which AI wrote it,
subject, error) and opens correctly in Excel.

---

## License

MIT, see [LICENSE](LICENSE).
