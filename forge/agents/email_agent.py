"""
EmailAgent — autonomous agent that reacts to ARC-Relay webhook events.

Capabilities:
  - Triage: classifies forwarded emails via lightweight LLM call
  - Auto-block: blocks senders after repeated rejections (threshold: 5)
  - DNS alerts: surfaces DMARC/SPF changes above warning severity
  - Alias management: programmatic alias creation via email tools

Runs a background thread that consumes events from a queue.
"""
import json
import logging
import threading
from collections import defaultdict
from queue import Queue, Empty

log = logging.getLogger("forge.agents.email")

AUTO_BLOCK_THRESHOLD = 5  # rejections from same sender before auto-block


class EmailAgent:
    """Background agent that processes ARC-Relay webhook events."""

    def __init__(self, api_key: str = "", api_url: str = "", model: str = ""):
        self.api_key = api_key
        self.api_url = api_url.rstrip("/") if api_url else ""
        self.model = model
        self._event_queue: Queue = Queue()
        self._running = False
        self._thread = None
        self._rejection_counts: dict[str, int] = defaultdict(int)
        self._blocked_senders: set[str] = set()
        self._processed_events: list[dict] = []

    def start(self):
        """Start the background event processing thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        log.info("EmailAgent started (model=%s)", self.model)

    def stop(self):
        """Stop the background thread."""
        self._running = False
        self._event_queue.put(None)  # wake up the thread
        if self._thread:
            self._thread.join(timeout=5)

    def handle_event(self, event: dict):
        """Called by the webhook blueprint to queue an event."""
        self._event_queue.put(event)

    def _process_loop(self):
        """Main loop: consume events from queue."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=1)
                if event is None:
                    break
                self._dispatch(event)
            except Empty:
                continue
            except Exception as e:
                log.exception("EmailAgent error processing event: %s", e)

    def _dispatch(self, event: dict):
        """Route event to the appropriate handler."""
        event_type = event.get("type", "")
        self._processed_events.append(event)

        if event_type == "forward.success":
            self._handle_forward_success(event)
        elif event_type == "forward.rejected":
            self._handle_forward_rejected(event)
        elif event_type == "forward.failed":
            self._handle_forward_failed(event)
        elif event_type.startswith("dns."):
            self._handle_dns_event(event)
        else:
            log.debug("Unhandled event type: %s", event_type)

    # ── Event Handlers ─────────────────────────────────────────────────

    def _handle_forward_success(self, event: dict):
        """Triage a successfully forwarded email."""
        data = event.get("data", {})
        sender = data.get("sender", "")
        subject = data.get("subject", "")
        domain = data.get("domain", "")
        log.info("Forward success: %s → %s [%s]", sender, domain, subject[:60])

        # Classification would use a lightweight LLM call here
        # For now, we log the triage event
        category = self._classify_email(sender, subject)
        log.info("Classified as: %s", category)

    def _handle_forward_rejected(self, event: dict):
        """Track rejections and auto-block repeat offenders."""
        data = event.get("data", {})
        sender = data.get("sender", "")
        reason = data.get("reason", "")
        log.info("Forward rejected: %s (%s)", sender, reason)

        if not sender:
            return

        self._rejection_counts[sender] += 1
        count = self._rejection_counts[sender]

        if count >= AUTO_BLOCK_THRESHOLD and sender not in self._blocked_senders:
            log.warning("Auto-blocking sender %s after %d rejections", sender, count)
            self._auto_block_sender(sender)

    def _handle_forward_failed(self, event: dict):
        """Log delivery failures."""
        data = event.get("data", {})
        sender = data.get("sender", "")
        error = data.get("error", "")
        log.warning("Forward failed: %s — %s", sender, error)

    def _handle_dns_event(self, event: dict):
        """Surface DNS alerts above warning severity."""
        event_type = event.get("type", "")
        data = event.get("data", {})
        severity = data.get("severity", "info")
        domain = data.get("domain", "")
        message = data.get("message", "")

        if severity in ("warning", "critical"):
            log.warning("DNS alert [%s] %s: %s — %s", severity, event_type, domain, message)
        else:
            log.info("DNS event [%s] %s: %s", severity, event_type, domain)

    # ── Actions ────────────────────────────────────────────────────────

    def _classify_email(self, sender: str, subject: str) -> str:
        """Classify an email into a category.

        In production this would call the executor's LLM. For now,
        uses simple heuristics.
        """
        subject_lower = subject.lower()
        sender_lower = sender.lower()
        if any(w in subject_lower for w in ["invoice", "payment", "receipt", "billing"]):
            return "financial"
        if any(w in subject_lower for w in ["alert", "warning", "urgent", "action required"]):
            return "urgent"
        if any(w in subject_lower for w in ["newsletter", "unsubscribe", "weekly", "digest"]):
            return "newsletter"
        if any(w in sender_lower for w in ["noreply", "no-reply", "donotreply", "no_reply"]):
            return "automated"
        return "general"

    def _auto_block_sender(self, sender: str):
        """Block a sender via the email_block_sender tool."""
        self._blocked_senders.add(sender)

        if not self.api_key or not self.api_url:
            log.warning("Cannot auto-block %s: no ARC-Relay API key/URL configured", sender)
            return

        try:
            from forge.tools.email import email_block_sender
            result = email_block_sender(self.api_key, sender)
            log.info("Auto-block result for %s: %s", sender, result[:200])
        except Exception as e:
            log.error("Auto-block failed for %s: %s", sender, e)

    # ── Inspection ─────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        """Return agent stats for debugging/display."""
        return {
            "running": self._running,
            "events_processed": len(self._processed_events),
            "rejection_counts": dict(self._rejection_counts),
            "blocked_senders": list(self._blocked_senders),
            "queue_size": self._event_queue.qsize(),
        }
