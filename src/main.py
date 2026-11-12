"""AI Outreach Mailer CLI.

Examples:
  python -m src.main --file data/recipients.xlsx                 # dry run (nothing sent)
  python -m src.main --file data/recipients.xlsx --preview 3     # print 3 emails
  python -m src.main --test-to you@gmail.com --file data/recipients.xlsx
  python -m src.main --file data/recipients.xlsx --send --limit 20
  python -m src.main --check                                     # test keys + SMTP login
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from .config import LOGS_DIR, ConfigError, load_settings
from .loader import LoaderError, load_recipients
from .personalizer import Personalizer
from .providers import build_providers
from .renderer import build_message
from .sender import PermanentSendError, TemporarySendError, Throttle, build_sender, send_with_retry
from .tracker import Tracker

# Windows terminals/log files may not be UTF-8; never crash on ₹, €, emoji, etc.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

console = Console()


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="ai-outreach-mailer", description="AI-personalized outreach emails from your company mailbox")
    p.add_argument("--file", "-f", help="Recipients file (.xlsx, .xls, .csv)")
    p.add_argument("--config", help="Path to config.yaml (default: project root)")
    p.add_argument("--send", action="store_true", help="Actually send emails (default is dry run)")
    p.add_argument("--yes", action="store_true", help="Skip the YES confirmation (for scheduled runs)")
    p.add_argument("--limit", type=int, help="Only process the first N eligible recipients")
    p.add_argument("--preview", type=int, metavar="N", help="Print N personalized emails and exit")
    p.add_argument("--test-to", metavar="EMAIL", help="Send ONE sample (first row) to this address")
    p.add_argument("--no-ai", action="store_true", help="Skip AI, use the plain template for everyone")
    p.add_argument("--check-dns", action="store_true", help="Also check each email domain exists")
    p.add_argument("--check", action="store_true", help="Check AI keys and SMTP login, then exit")
    p.add_argument("--list-models", action="store_true", help="List models your AI keys can use")
    p.add_argument("--unsubscribe", metavar="EMAIL", nargs="+", help="Add address(es) to the unsubscribe list")
    return p.parse_args(argv)


def make_personalizer(settings, no_ai: bool) -> Personalizer:
    providers = []
    if not no_ai:
        providers, warnings = build_providers(settings)
        for w in warnings:
            console.print(f"[yellow]! {w}[/yellow]")
        if not providers:
            console.print("[yellow]! No AI provider available; every email will use the plain template.[/yellow]")
    return Personalizer(providers, settings)


def print_email(to: str, draft, idx: int | None = None):
    title = f"[bold]{'#' + str(idx) + '  ' if idx else ''}To:[/bold] {to}   [dim]written by: {draft.provider}[/dim]"
    console.print(Panel(f"[bold]Subject:[/bold] {draft.subject}\n\n{draft.body}", title=title,
                        title_align="left", expand=False))
    for n in draft.notes:
        console.print(f"  [dim]· {n}[/dim]")


def cmd_check(settings) -> int:
    ok = True
    providers, warnings = build_providers(settings)
    for w in warnings:
        console.print(f"[yellow]✗ {w}[/yellow]")
    if not providers:
        ok = False
        console.print("[red]✗ No AI provider available. Set GEMINI_API_KEY or XAI_API_KEY in .env[/red]")
    for p in providers:
        try:
            p.generate("Reply with JSON only.", 'Return {"ok": true}')
            console.print(f"[green]✓ {p.name} ({p.model}) works[/green]")
        except Exception as e:
            ok = False
            console.print(f"[red]✗ {p.name}: {str(e)[:200]}[/red]")
    try:
        s = build_sender(settings)
        s.verify()
        s.close()
        console.print(f"[green]✓ SMTP login OK ({settings.env_get('SMTP_USER')})[/green]")
    except Exception as e:
        ok = False
        console.print(f"[red]✗ SMTP: {e}[/red]")
    return 0 if ok else 1


def cmd_list_models(settings) -> int:
    providers, warnings = build_providers(settings)
    for w in warnings:
        console.print(f"[yellow]! {w}[/yellow]")
    for p in providers:
        try:
            names = p.list_models()
            console.print(f"[bold]{p.name}[/bold]: " + ", ".join(sorted(names)))
        except Exception as e:
            console.print(f"[red]{p.name}: {e}[/red]")
    return 0


def run(argv=None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.config)
    except (ConfigError, OSError) as e:
        console.print(f"[red]Config problem: {e}[/red]")
        return 2
    tracker = Tracker(LOGS_DIR)
    campaign = settings.campaign.get("name", "default")

    if args.unsubscribe:
        for e in args.unsubscribe:
            tracker.add_unsubscribe(e)
        console.print(f"[green]Added {len(args.unsubscribe)} address(es) to logs/unsubscribed.txt[/green]")
        return 0
    if args.check:
        return cmd_check(settings)
    if args.list_models:
        return cmd_list_models(settings)
    if not args.file:
        console.print("[red]--file is required. Example: python -m src.main --file data/recipients.xlsx[/red]")
        return 2

    # 1. LOAD
    try:
        recipients, rejected = load_recipients(args.file, settings.columns, check_dns=args.check_dns)
    except LoaderError as e:
        console.print(f"[red]{e}[/red]")
        return 2
    console.print(f"Loaded [bold]{len(recipients)}[/bold] valid recipients from {Path(args.file).name}"
                  + (f", [yellow]{len(rejected)} rejected[/yellow]" if rejected else ""))
    for r in rejected[:10]:
        console.print(f"  [dim]row {r['row']}: {r.get('email') or '(blank)'} → {r['reason']}[/dim]")
    if len(rejected) > 10:
        console.print(f"  [dim]...and {len(rejected) - 10} more[/dim]")

    personalizer = make_personalizer(settings, args.no_ai)

    # Test send to yourself
    if args.test_to:
        if not recipients:
            console.print("[red]No valid recipients to build a sample from.[/red]")
            return 2
        rec = next((r for r in recipients if not tracker.is_unsubscribed(r["email"])), recipients[0])
        draft = personalizer.write(rec)
        print_email(args.test_to, draft)
        msg = build_message(to_email=args.test_to, subject="[TEST] " + draft.subject,
                            body=draft.body, settings=settings)
        try:
            sender = build_sender(settings)
            send_with_retry(sender, msg, settings.sending.get("max_send_retries", 3))
            sender.close()
        except Exception as e:
            console.print(f"[red]Test send failed: {e}[/red]")
            return 1
        console.print(f"[green]Test email sent to {args.test_to} (based on {rec['email']}).[/green]")
        return 0

    # 2. FILTER
    queue, skipped = [], Counter()
    for rec in recipients:
        if tracker.is_unsubscribed(rec["email"]):
            skipped["unsubscribed"] += 1
        elif tracker.already_sent(rec["email"], campaign):
            skipped["already sent"] += 1
        else:
            queue.append(rec)
    if skipped:
        console.print("Skipping: " + ", ".join(f"{v} {k}" for k, v in skipped.items()))

    if args.preview:
        for i, rec in enumerate(queue[: args.preview], 1):
            print_email(rec["email"], personalizer.write(rec), i)
        return 0

    if args.limit:
        queue = queue[: args.limit]

    if args.send:
        cap = int(settings.sending.get("daily_cap", 400))
        room = max(0, cap - tracker.sent_today)
        if room == 0:
            console.print(f"[yellow]Daily cap of {cap} already reached today. Try again tomorrow.[/yellow]")
            return 0
        if len(queue) > room:
            console.print(f"[yellow]Daily cap: only {room} more today (cap {cap}). The rest will wait.[/yellow]")
            queue = queue[:room]

    if not queue:
        console.print("[green]Nothing to do.[/green]")
        return 0

    mode = "SEND" if args.send else "DRY RUN"
    if args.send and not args.yes:
        console.print(Panel(f"About to email [bold]{len(queue)}[/bold] people from "
                            f"[bold]{settings.env_get('FROM_EMAIL') or settings.env_get('SMTP_USER')}[/bold]\n"
                            f"Campaign: {campaign}", title="Confirm", border_style="red"))
        if input("Type YES to send: ").strip() != "YES":
            console.print("Cancelled.")
            return 1

    sender = None
    if args.send:
        try:
            sender = build_sender(settings)
            sender.verify()
        except Exception as e:  # bad login, wrong host/port, no internet
            console.print(f"[red]Could not connect to the mail server: {e}[/red]")
            return 1

    preview_dir = LOGS_DIR / "previews"
    if not args.send:
        preview_dir.mkdir(parents=True, exist_ok=True)

    throttle = Throttle(int(settings.sending.get("emails_per_minute", 10)),
                        tuple(settings.sending.get("jitter_seconds", [2, 6])))
    stats, by_provider = Counter(), Counter()

    # 3-6. PERSONALIZE → RENDER → SEND → LOG
    with Progress(TextColumn("[bold]{task.description}"), BarColumn(), MofNCompleteColumn(),
                  TimeElapsedColumn(), console=console) as progress:
        task = progress.add_task(mode, total=len(queue))
        for rec in queue:
            email = rec["email"]
            progress.update(task, description=f"{mode} {email}")
            try:
                draft = personalizer.write(rec)
                by_provider[draft.provider] += 1
                msg = build_message(to_email=email, subject=draft.subject, body=draft.body, settings=settings)
                if args.send:
                    throttle.wait()
                    send_with_retry(sender, msg, settings.sending.get("max_send_retries", 3))
                    tracker.log(campaign=campaign, email=email, status="sent",
                                provider=draft.provider, subject=draft.subject)
                    stats["sent"] += 1
                else:
                    safe = email.replace("@", "_at_")
                    (preview_dir / f"{safe}.eml").write_bytes(bytes(msg))
                    tracker.log(campaign=campaign, email=email, status="dry_run",
                                provider=draft.provider, subject=draft.subject)
                    stats["dry_run"] += 1
            except (PermanentSendError, TemporarySendError) as e:
                tracker.log(campaign=campaign, email=email, status="failed", error=str(e))
                stats["failed"] += 1
                progress.console.print(f"[red]✗ {email}: {e}[/red]")
            except KeyboardInterrupt:
                progress.console.print("[yellow]Stopped by user. Re-run to continue where you left off.[/yellow]")
                break
            except Exception as e:  # never let one bad row kill the whole batch
                tracker.log(campaign=campaign, email=email, status="failed", error=f"{type(e).__name__}: {e}")
                stats["failed"] += 1
                progress.console.print(f"[red]✗ {email}: {type(e).__name__}: {e}[/red]")
            progress.advance(task)

    if sender:
        sender.close()

    t = Table(title=f"Summary ({mode})", show_header=False)
    for k, v in stats.items():
        t.add_row(k, str(v))
    for k, v in skipped.items():
        t.add_row(f"skipped ({k})", str(v))
    for k, v in by_provider.items():
        t.add_row(f"written by {k}", str(v))
    console.print(t)
    if not args.send:
        console.print(f"Dry run: nothing was sent. Email previews saved to [bold]{preview_dir}[/bold] "
                      "(open the .eml files in any mail app). Add --send to send for real.")
    console.print(f"Log: {LOGS_DIR / 'sent_log.csv'}")
    return 0 if not stats["failed"] else 1


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
