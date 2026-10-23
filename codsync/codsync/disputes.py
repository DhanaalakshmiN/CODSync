"""Courier disputes: send the claim, track its stages, remind, and close on refund.

COD Exception carries the dispute (dispute_status = stage, stage_log = history).
Mail goes out through the site's default outgoing Email Account.
"""

import csv
import io

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, now_datetime, nowdate
from frappe.utils.data import escape_html

DISPUTE_TYPES = ("Unexpected deduction", "Amount mismatch", "Missing settlement")
# stages in which the courier still owes money
ACTIVE_STAGES = ("Raised with Courier", "Sent to courier", "Courier replied", "Accepted", "Partly accepted")
TERMINAL_STAGES = ("Rejected", "Refunded", "Resolved")
REMIND_STAGES = ("Sent to courier", "Courier replied", "Accepted", "Partly accepted")
DEFAULT_FOLLOW_UP_DAYS = 7


def follow_up_days():
	value = frappe.db.get_single_value("Store Connection", "claim_follow_up_days")
	return cint(value) or DEFAULT_FOLLOW_UP_DAYS


def stages():
	return frappe.get_meta("COD Exception").get_field("dispute_status").options.split("\n")


def set_stage(exc, stage, note=None, agreed_amount=None):
	"""Move a dispute to a stage, log it, and maintain the follow-up date. Caller saves."""
	if stage not in stages() or stage == "Not raised":
		frappe.throw(_("Unknown dispute stage {0}").format(stage))
	exc.dispute_status = stage
	if agreed_amount not in (None, ""):
		exc.agreed_amount = flt(agreed_amount)
	if stage == "Sent to courier":
		exc.next_follow_up = add_days(nowdate(), follow_up_days())
	elif stage in TERMINAL_STAGES:
		exc.next_follow_up = None
	exc.append(
		"stage_log",
		{"stage": stage, "changed_on": now_datetime(), "changed_by": frappe.session.user, "note": note},
	)


def open_dispute_for(parcel):
	"""The open exception of a parcel whose dispute is still active, if any."""
	name = frappe.db.get_value(
		"COD Exception",
		{"cod_parcel": parcel, "status": "Open", "dispute_status": ["in", ACTIVE_STAGES]},
	)
	return frappe.get_doc("COD Exception", name) if name else None


# --------------------------------------------------------------------------- sending


def _claim_amount(exc):
	return flt(exc.claim_amount) or abs(flt(exc.impact))


def _eligible(names):
	rows = [frappe.get_doc("COD Exception", n) for n in names]
	if not rows:
		frappe.throw(_("Select at least one exception"))
	for exc in rows:
		if exc.status != "Open":
			frappe.throw(_("{0} is already resolved").format(exc.name))
		if exc.exception_type not in DISPUTE_TYPES:
			frappe.throw(_("A claim cannot be sent for {0} ({1})").format(exc.name, exc.exception_type))
		if exc.dispute_status in TERMINAL_STAGES:
			frappe.throw(_("{0} already has a final dispute outcome").format(exc.name))
	return rows


def _by_courier(rows):
	groups = {}
	for exc in rows:
		if not exc.courier:
			frappe.throw(_("{0} has no courier").format(exc.name))
		groups.setdefault(exc.courier, []).append(exc)
	return groups


def _courier_mail(courier):
	to, cc = frappe.db.get_value("Courier", courier, ["claims_email", "claims_cc"]) or (None, None)
	if not to:
		frappe.throw(_("Courier {0} has no Claims Email. Add it on the Courier first.").format(courier))
	return to, [c.strip() for c in (cc or "").split(",") if c.strip()]


def _table(rows):
	head = "".join(
		f"<th style='text-align:left;padding:4px 8px'>{h}</th>"
		for h in ("AWB", "Order", "Expected", "Received", "Claim", "Reason")
	)
	body = "".join(
		"<tr>"
		+ "".join(
			f"<td style='padding:4px 8px'>{escape_html(str(v))}</td>"
			for v in (
				e.awb or "",
				e.cod_parcel or "",
				f"{flt(e.expected):.2f}",
				f"{flt(e.actual):.2f}",
				f"{_claim_amount(e):.2f}",
				e.detail or e.exception_type,
			)
		)
		+ "</tr>"
		for e in rows
	)
	return f"<table border='1' cellspacing='0' style='border-collapse:collapse'><tr>{head}</tr>{body}</table>"


def _csv(rows):
	buf = io.StringIO()
	w = csv.writer(buf)
	w.writerow(["AWB", "Order", "Settlement batch", "Expected", "Received", "Claim", "Reason"])
	for e in rows:
		w.writerow(
			[e.awb, e.cod_parcel, e.settlement_batch, e.expected, e.actual, _claim_amount(e), e.detail or e.exception_type]
		)
	return buf.getvalue().encode("utf-8")


def build_claim(courier, rows, message=None, reminder=False):
	total = sum(_claim_amount(e) for e in rows)
	company = frappe.db.get_single_value("Store Connection", "store_name") or ""
	if reminder:
		subject = f"Reminder: pending claim for {len(rows)} shipment(s), {total:.2f}"
		intro = "This is a reminder about the claim below, which is still unresolved."
	else:
		subject = f"Short-payment claim: {len(rows)} shipment(s), {total:.2f}"
		intro = "We found differences between the COD amount due and the amount settled for the shipments below."
	body = (
		f"<p>Hello {escape_html(courier)} team,</p><p>{intro}</p>{_table(rows)}"
		f"<p>Total claimed: <b>{total:.2f}</b>. Please review, credit the amount or send us the "
		f"deduction breakup, and quote your ticket reference in the reply.</p>"
		+ (f"<p>{escape_html(message)}</p>" if message else "")
		+ f"<p>Regards,<br>{escape_html(company)}</p>"
	)
	return {"subject": subject, "message": body, "total": total}


def preview_claim(names, message=None):
	"""What send_claim would email, per courier. Sends nothing."""
	groups = _by_courier(_eligible(names))
	out = []
	for courier, rows in groups.items():
		to, cc = _courier_mail(courier)
		mail = build_claim(courier, rows, message)
		out.append({"courier": courier, "to": to, "cc": cc, "count": len(rows), **mail})
	return out


def _require_outgoing_email():
	if not frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
		frappe.throw(_("No default outgoing Email Account is set up on this site"))


def send_claim(names, message=None):
	"""Email one consolidated claim per courier and move each exception to Sent to courier."""
	from codsync.codsync.synclog import log_sync

	groups = _by_courier(_eligible(names))
	mails = {c: _courier_mail(c) for c in groups}
	_require_outgoing_email()
	sent = []
	for courier, rows in groups.items():
		to, cc = mails[courier]
		mail = build_claim(courier, rows, message)
		frappe.sendmail(
			recipients=[to],
			cc=cc,
			subject=mail["subject"],
			message=mail["message"],
			attachments=[{"fname": f"claim-{courier}-{nowdate()}.csv", "fcontent": _csv(rows)}],
			reference_doctype="COD Exception",
			reference_name=rows[0].name,
		)
		for exc in rows:
			if (exc.dispute_status or "Not raised") == "Not raised":
				exc.resolution = "Raise dispute"
				exc.claim_amount = _claim_amount(exc)
				exc.dispute_raised_on = nowdate()
			exc.claim_sent_on = now_datetime()
			exc.claim_sent_to = to
			set_stage(exc, "Sent to courier", f"Claim emailed to {to}")
			exc.save(ignore_permissions=True)
			exc.add_comment("Comment", f"Claim of {_claim_amount(exc):.2f} emailed to {to}")
		log_sync(
			"Courier",
			"Dispute",
			"Success",
			error_message=f"Claim for {len(rows)} shipment(s) sent to {courier}",
			response_payload={"exceptions": [e.name for e in rows], "total": mail["total"]},
		)
		sent.append({"courier": courier, "to": to, "count": len(rows), "total": mail["total"]})
	return {"sent": sent}


def send_follow_ups():
	"""Daily: remind couriers about claims whose follow-up date has passed."""
	from codsync.codsync.synclog import log_sync

	due = frappe.get_all(
		"COD Exception",
		filters={
			"status": "Open",
			"dispute_status": ["in", REMIND_STAGES],
			"next_follow_up": ["<=", nowdate()],
		},
		pluck="name",
	)
	if not due:
		return {"reminded": 0}
	rows = [frappe.get_doc("COD Exception", n) for n in due]
	count = 0
	for courier, group in _by_courier(rows).items():
		try:
			to, cc = _courier_mail(courier)
			_require_outgoing_email()
			mail = build_claim(courier, group, reminder=True)
			frappe.sendmail(
				recipients=[to],
				cc=cc,
				subject=mail["subject"],
				message=mail["message"],
				attachments=[{"fname": f"claim-{courier}-{nowdate()}.csv", "fcontent": _csv(group)}],
				reference_doctype="COD Exception",
				reference_name=group[0].name,
			)
		except Exception as e:
			log_sync("Courier", "Dispute", "Failed", error_message=f"Reminder to {courier}: {e}")
			continue
		for exc in group:
			exc.next_follow_up = add_days(nowdate(), follow_up_days())
			exc.last_reminder_on = nowdate()
			exc.append(
				"stage_log",
				{
					"stage": exc.dispute_status,
					"changed_on": now_datetime(),
					"changed_by": "Administrator",
					"note": f"Reminder emailed to {to}",
				},
			)
			exc.save(ignore_permissions=True)
		count += len(group)
		log_sync("Courier", "Dispute", "Success", error_message=f"Reminder for {len(group)} claim(s) sent to {courier}")
	return {"reminded": count}


def is_overdue(exc):
	return bool(
		exc.status == "Open"
		and exc.dispute_status in REMIND_STAGES + ("Raised with Courier",)
		and exc.next_follow_up
		and getdate(exc.next_follow_up) < getdate(nowdate())
	)


# --------------------------------------------------------------------------- refunds


def apply_refund(exc, line, parcel):
	"""A later settlement line paid (part of) a disputed amount for an already-settled parcel.

	Adds it to the parcel's received amount. Fully recovered -> Refunded and the
	exception resolves; partly recovered -> Partly accepted and it stays open.
	"""
	from codsync.codsync.engine import payout_decision

	amount = flt(line.net_paid)
	recovered = flt(exc.recovered_amount) + amount
	actual = flt(parcel.actual_settlement) + amount
	difference, _within, status = payout_decision(parcel, parcel.expected_settlement, actual)
	target = flt(exc.agreed_amount) or _claim_amount(exc)
	full = status == "Paid" or recovered >= target

	frappe.db.set_value(
		"Remittance Line",
		line.name,
		{"cod_parcel": parcel.name, "match_status": "Paid", "difference": 0, "expected_net": 0},
	)
	frappe.db.set_value(
		"COD Parcel",
		parcel.name,
		{"actual_settlement": actual, "difference": difference, "payout_status": status},
	)
	exc.recovered_amount = recovered
	batch = line.parent
	if full:
		set_stage(exc, "Refunded", f"{amount:.2f} received in {batch}")
		exc.status = "Resolved"
		exc.resolution_note = f"Refund of {recovered:.2f} received in {batch}"
	else:
		set_stage(exc, "Partly accepted", f"{amount:.2f} of {target:.2f} received in {batch}")
	exc.save(ignore_permissions=True)
	exc.add_comment(
		"Comment",
		f"Refund of {amount:.2f} received in {batch}" + ("" if full else f" ({recovered:.2f} of {target:.2f} so far)"),
	)
	return {"refunded": full, "amount": amount}


def close_on_settlement(parcel, amount, batch):
	"""A missing settlement finally arrived: close active disputes on that parcel as Refunded."""
	for name in frappe.get_all(
		"COD Exception",
		pluck="name",
		filters={
			"cod_parcel": parcel,
			"exception_type": "Missing settlement",
			"status": "Open",
			"dispute_status": ["in", ACTIVE_STAGES],
		},
	):
		exc = frappe.get_doc("COD Exception", name)
		exc.recovered_amount = flt(amount)
		set_stage(exc, "Refunded", f"Settlement of {flt(amount):.2f} received in {batch}")
		exc.save(ignore_permissions=True)
