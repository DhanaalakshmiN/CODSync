"""Excel / CSV import: reading, column mapping, row checks, preview and the two importers."""

import csv
import datetime
import io
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from codsync.codsync import importer
from codsync.tests.helpers import NET_1KG, Fixture

PARCEL_HEAD = ["Order ID", "AWB", "Courier", "COD Amount", "Status", "Delivered Date", "Declared Weight"]
REMIT_HEAD = ["Remittance ID", "Remittance Date", "UTR", "AWB", "COD Amount", "Net Paid"]


class ImporterCase(IntegrationTestCase):
	prefix = "IMP"

	def setUp(self):
		self.fx = Fixture(self.prefix)
		self.fx.default_settings()
		self.fx.make_courier()
		self.files = []

	def tearDown(self):
		frappe.set_user("Administrator")
		with patch("frappe.utils.global_search.sync_value_in_queue"):
			for name in self.files:
				frappe.delete_doc("File", name, force=True, ignore_permissions=True)
		self.fx.cleanup()

	def make_file(self, rows, head=None, name="sample.csv", raw=None):
		"""Write a CSV (or raw bytes under any name) as a private File; returns its file_url."""
		if raw is None:
			buf = io.StringIO()
			w = csv.writer(buf)
			if head:
				w.writerow(head)
			w.writerows(rows)
			raw = buf.getvalue().encode()
		# File inserts queue a global-search update in Redis; the test bench may not have it running
		with patch("frappe.utils.global_search.sync_value_in_queue"):
			doc = frappe.get_doc(
				{"doctype": "File", "file_name": f"{self.prefix}-{len(self.files)}-{name}", "content": raw, "is_private": 1}
			).insert(ignore_permissions=True)
		self.files.append(doc.name)
		return doc.file_url

	def parcel_row(self, key, **kw):
		v = {
			"order": f"{self.prefix}-{key}", "awb": f"{self.prefix}AWB{key}", "courier": self.fx.courier,
			"cod": 1000, "status": "Delivered", "delivered": str(datetime.date.today()), "weight": 1,
		}
		v.update(kw)
		return [v["order"], v["awb"], v["courier"], v["cod"], v["status"], v["delivered"], v["weight"]]

	def remit_row(self, rid, awb, net=NET_1KG, cod=1000, utr="UTR1", date=None):
		# the batch id is the Remittance ID, or the UTR when the ID is blank: no ID means no UTR here
		return [f"{self.prefix}-{rid}" if rid else "", date or str(datetime.date.today()), utr if rid else "", awb, cod, net]


class TestCellsAndMapping(IntegrationTestCase):
	def test_cell_to_str(self):
		f = importer._cell_to_str
		self.assertEqual(f(None), "")
		self.assertEqual(f("  hi  "), "hi")
		self.assertEqual(f(5.0), "5")
		self.assertEqual(f(5.25), "5.25")
		self.assertEqual(f(datetime.datetime(2026, 1, 2)), "2026-01-02")
		self.assertEqual(f(datetime.datetime(2026, 1, 2, 3, 4, 5)), "2026-01-02 03:04:05")
		self.assertEqual(f(datetime.date(2026, 1, 2)), "2026-01-02")
		self.assertEqual(f("123.0", "awb"), "123")
		self.assertEqual(f("98400.0", "phone"), "98400")
		self.assertEqual(f("1.0", "city"), "1.0")  # only awb / phone / pincode lose a trailing .0

	def test_auto_detect_headers(self):
		m = {x["header"]: x for x in importer.build_mapping(["order id", "awb", "cod amount", "mystery"], "Parcels")}
		self.assertEqual(m["order id"]["field"], "order_id")
		self.assertEqual(m["awb"]["field"], "awb")
		self.assertEqual(m["cod amount"]["field"], "cod_amount")
		self.assertEqual(m["order id"]["source"], "auto")
		self.assertEqual((m["mystery"]["field"], m["mystery"]["source"]), (None, "none"))

	def test_explicit_mapping_wins_over_auto(self):
		m = importer.build_mapping(["ref", "awb"], "Parcels", explicit={"ref": "order_id"})
		self.assertEqual([(x["field"], x["source"]) for x in m], [("order_id", "saved"), ("awb", "auto")])

	def test_a_field_is_mapped_only_once(self):
		m = importer.build_mapping(["awb", "tracking number"], "Parcels")
		self.assertEqual([x["field"] for x in m], ["awb", None])

	def test_saved_mapping_accepts_json_list_and_ignores_garbage(self):
		self.assertEqual(importer._saved_mapping(None, "Parcels", '{"Ref": "order_id"}'), {"ref": "order_id"})
		self.assertEqual(
			importer._saved_mapping(None, "Parcels", [{"file_column": "Ref", "field": "order_id"}]),
			{"ref": "order_id"},
		)
		self.assertEqual(importer._saved_mapping(None, "Parcels", "not json"), {})


class TestRowChecks(IntegrationTestCase):
	def setUp(self):
		self.fx = Fixture("IMR")
		self.fx.make_courier()
		self.couriers = {}

	def tearDown(self):
		self.fx.cleanup()

	def parcel(self, **row):
		return importer.check_parcel_row({"order_id": "O1", "cod_amount": "1,000.50", **row}, None, self.couriers)

	def test_valid_parcel_row(self):
		v, errs = self.parcel(awb=" ab-1 ", status="delivered", payment_mode="Prepaid")
		self.assertEqual(errs, [])
		self.assertEqual((v["awb"], v["cod_amount"], v["status"], v["payment_mode"]), ("AB1", 1000.5, "Delivered", "Prepaid"))

	def test_order_id_falls_back_to_awb(self):
		v, errs = importer.check_parcel_row({"awb": "XY9"}, None, self.couriers)
		self.assertEqual((v["order_id"], errs), ("XY9", []))

	def test_row_without_order_id_or_awb_is_rejected(self):
		_v, errs = importer.check_parcel_row({"cod_amount": "5"}, None, self.couriers)
		self.assertEqual(errs, ["Order ID or AWB is required"])

	def test_bad_amount_date_status_and_courier(self):
		_v, errs = self.parcel(cod_amount="abc", delivered_date="not-a-date", status="Lost in space", courier="NoSuchCourier")
		joined = " | ".join(errs)
		for text in ("cod_amount is not a number", "delivered_date is not a valid date", "Status Lost in space", "Courier NoSuchCourier"):
			self.assertIn(text, joined)

	def test_negative_cod_amount_is_rejected(self):
		self.assertIn("cannot be negative", self.parcel(cod_amount="-5")[1][0])

	def test_courier_name_is_case_insensitive_and_default_applies(self):
		v, errs = self.parcel(courier=self.fx.courier.lower())
		self.assertEqual((v["courier"], errs), (self.fx.courier, []))
		v, _ = importer.check_parcel_row({"order_id": "O2", "cod_amount": "1"}, "DefaultC", self.couriers)
		self.assertEqual(v["courier"], "DefaultC")

	def test_blank_or_text_weight_is_not_an_error(self):
		v, errs = self.parcel(declared_weight="heavy", charged_weight="")
		self.assertEqual((errs, v["declared_weight"], v["charged_weight"]), ([], None, None))

	def test_line_row_valid_and_invalid(self):
		line, errs = importer.check_line_row({"awb": "ab 1", "net_paid": "900", "freight_charge": "-3"}, 4)
		self.assertEqual((errs, line["awb"], line["net_paid"], line["row_no"]), ([], "AB1", 900, 4))
		self.assertEqual(importer.check_line_row({"net_paid": "1"}, 2)[1], ["AWB is required"])
		self.assertEqual(importer.check_line_row({"awb": "A"}, 2)[1], ["net_paid is required"])
		self.assertIn("cannot be negative", importer.check_line_row({"awb": "A", "net_paid": "-1"}, 2)[1][0])
		self.assertIn("is not a number", importer.check_line_row({"awb": "A", "net_paid": "x"}, 2)[1][0])


class TestReadingFiles(ImporterCase):
	prefix = "IMF"

	def test_csv_rows_skip_blank_lines_and_start_at_row_two(self):
		url = self.make_file([["O1", "A1", "", 100], ["", "", "", ""], ["O2", "A2", "", 200]], ["Order ID", "AWB", "Courier", "COD Amount"])
		_mapping, rows = importer._load(url, "Parcels")
		self.assertEqual([i for i, _ in rows], [2, 4])
		self.assertEqual(rows[1][1]["order_id"], "O2")

	def test_unmapped_columns_are_dropped(self):
		url = self.make_file([["O1", "zzz"]], ["Order ID", "Mystery"])
		self.assertEqual(importer._load(url, "Parcels")[1][0][1], {"order_id": "O1"})

	def test_xlsx_is_read(self):
		from openpyxl import Workbook

		wb = Workbook()
		wb.active.append(["Order ID", "AWB", "COD Amount"])
		wb.active.append(["O1", 123456789012.0, 500])
		buf = io.BytesIO()
		wb.save(buf)
		url = self.make_file(None, name="sample.xlsx", raw=buf.getvalue())
		row = importer.read_rows(url)[0]
		self.assertEqual((row["order_id"], row["awb"], row["cod_amount"]), ("O1", "123456789012", "500"))

	def test_unsupported_extension_is_refused(self):
		url = self.make_file(None, name="notes.txt", raw=b"hello")
		with self.assertRaises(frappe.ValidationError):
			importer.file_headers(url)

	def test_file_with_only_a_header_has_no_rows(self):
		url = self.make_file([], ["Order ID", "AWB"])
		self.assertEqual(importer._load(url, "Parcels")[1], [])
		self.assertEqual(importer.preview_import(url, "Parcels")["message"], "The file has no data rows")


class TestPreview(ImporterCase):
	prefix = "IMV"

	def test_parcel_preview_counts_create_update_and_invalid(self):
		self.fx.make_parcel("EXIST")
		url = self.make_file(
			[self.parcel_row("EXIST"), self.parcel_row("NEW1"), self.parcel_row("NEW2", cod="abc")], PARCEL_HEAD
		)
		out = importer.preview_import(url, "Parcels", self.fx.courier)
		self.assertEqual((out["row_count"], out["valid_count"], out["invalid_count"]), (3, 2, 1))
		self.assertEqual((out["will_create"], out["will_update"]), (1, 1))
		self.assertEqual(out["invalid_rows"][0]["row"], 4)
		self.assertEqual(out["mapping_source"], "auto")
		self.assertFalse(out["background"])

	def test_preview_saves_nothing(self):
		url = self.make_file([self.parcel_row("P1")], PARCEL_HEAD)
		importer.preview_import(url, "Parcels", self.fx.courier)
		self.assertFalse(frappe.db.exists("COD Parcel", f"{self.prefix}-P1"))

	def test_large_file_is_flagged_for_background(self):
		rows = [[f"{self.prefix}-B{i}", f"{self.prefix}B{i}"] for i in range(importer.BACKGROUND_ROWS + 1)]
		url = self.make_file(rows, ["Order ID", "AWB"])
		self.assertTrue(importer.preview_import(url, "Parcels", self.fx.courier)["background"])

	def test_unknown_import_type_is_refused(self):
		url = self.make_file([["x"]], ["Order ID"])
		with self.assertRaises(frappe.ValidationError):
			importer.preview_import(url, "Nonsense")

	def test_remittance_preview_labels_each_line(self):
		ok, settled, prepaid = self.fx.make_parcel("OK"), self.fx.make_parcel("SET"), self.fx.make_parcel("PRE", payment_mode="Prepaid")
		existing = self.fx.make_remittance("OLD", [{"awb": ok.awb, "cod_amount": 1000, "net_paid": 1}])
		rows = [
			self.remit_row("NEW", ok.awb),                       # matched
			self.remit_row("NEW", ok.awb),                       # same AWB twice in the file
			self.remit_row("NEW", f"{self.prefix}GHOST"),        # no such order
			self.remit_row("NEW", prepaid.awb),                  # prepaid order
			self.remit_row("NEW", settled.awb, net="abc"),       # invalid amount
			self.remit_row(None, settled.awb),                   # no remittance id
		]
		out = importer.preview_import(self.make_file(rows, REMIT_HEAD), "Remittance", self.fx.courier)
		labels = {r["row"]: r["validation"] for r in out["rows"]}
		self.assertEqual(
			labels,
			{2: "Matched", 3: "Duplicate AWB", 4: "AWB not found", 5: "Prepaid order", 6: "Invalid", 7: "Invalid"},
		)
		self.assertEqual(out["tiles"], {"matched": 1, "awb_not_found": 1, "duplicate": 1, "invalid": 2, "other": 1})
		self.assertEqual(out["rows"][0]["validation"], "Invalid")  # problems sort first
		self.assertEqual(out["duplicate_batches"], [])

		again = importer.preview_import(
			self.make_file([[existing.name, str(datetime.date.today()), "U", ok.awb, 1000, NET_1KG]], REMIT_HEAD),
			"Remittance",
			self.fx.courier,
		)
		self.assertEqual(again["rows"][0]["validation"], "Already imported")
		self.assertEqual(again["duplicate_batches"], [existing.name])

	def test_remittance_preview_flags_already_settled_parcel(self):
		p = self.fx.make_parcel("S1")
		first = self.fx.make_remittance("FIRST", [{"awb": p.awb, "cod_amount": 1000, "net_paid": NET_1KG}], submit=True)
		out = importer.preview_import(self.make_file([self.remit_row("SECOND", p.awb)], REMIT_HEAD), "Remittance", self.fx.courier)
		self.assertEqual(out["rows"][0]["validation"], "Already settled")
		self.assertIn(first.name, out["rows"][0]["detail"])
		self.assertEqual(out["tiles"]["duplicate"], 1)


class TestImportParcels(ImporterCase):
	prefix = "IMP"

	def test_creates_parcels_with_file_values(self):
		url = self.make_file([self.parcel_row("1"), self.parcel_row("2", status="in transit", delivered="")], PARCEL_HEAD)
		res = importer.import_parcels(url, self.fx.courier)
		self.assertEqual((res["created"], res["updated"], res["skipped"]), (2, 0, 0))
		p = frappe.get_doc("COD Parcel", "IMP-1")
		self.assertEqual((p.platform, p.courier, p.status, p.payment_mode, p.cod_amount), ("Excel", self.fx.courier, "Delivered", "COD", 1000))
		self.assertEqual(frappe.db.get_value("COD Parcel", "IMP-2", "status"), "In Transit")

	def test_default_courier_used_when_file_has_none(self):
		url = self.make_file([["IMP-3", "IMPAWB3", 500]], ["Order ID", "AWB", "COD Amount"])
		importer.import_parcels(url, self.fx.courier)
		self.assertEqual(frappe.db.get_value("COD Parcel", "IMP-3", "courier"), self.fx.courier)

	def test_bad_rows_are_reported_and_good_rows_still_import(self):
		url = self.make_file([self.parcel_row("4"), self.parcel_row("5", cod="oops"), self.parcel_row("6")], PARCEL_HEAD)
		res = importer.import_parcels(url, self.fx.courier)
		self.assertEqual((res["created"], res["skipped"]), (2, 1))
		self.assertEqual(res["errors"][0]["row"], 3)
		self.assertFalse(frappe.db.exists("COD Parcel", "IMP-5"))

	def test_awb_owned_by_another_order_is_rejected_for_that_row_only(self):
		self.fx.make_parcel("7")
		clash = ["IMP-8", "IMPAWB7", self.fx.courier, 1000, "Delivered", str(datetime.date.today()), 1]
		res = importer.import_parcels(self.make_file([clash, self.parcel_row("9")], PARCEL_HEAD), self.fx.courier)
		self.assertEqual((res["created"], res["skipped"]), (1, 1))
		self.assertIn("already belongs to order IMP-7", res["errors"][0]["reason"])
		self.assertFalse(frappe.db.exists("COD Parcel", "IMP-8"))

	def test_reimport_only_backfills_empty_weights(self):
		self.fx.make_parcel("10", declared_weight=0, cod=1000)
		row = self.parcel_row("10", cod=9999, weight=2.5)
		res = importer.import_parcels(self.make_file([row], PARCEL_HEAD), self.fx.courier)
		self.assertEqual((res["created"], res["updated"]), (0, 1))
		p = frappe.get_doc("COD Parcel", "IMP-10")
		self.assertEqual((p.cod_amount, p.declared_weight), (1000, 2.5))  # amount untouched, weight filled

	def test_import_writes_a_sync_log(self):
		importer.import_parcels(self.make_file([self.parcel_row("11")], PARCEL_HEAD), self.fx.courier)
		log = frappe.get_all("Sync Log", filters={"operation": "Excel Import", "reference_name": self.fx.courier}, fields=["status"])
		self.assertEqual([x.status for x in log], ["Success"])


class TestImportRemittance(ImporterCase):
	prefix = "IMM"

	def test_creates_submits_and_matches(self):
		p = self.fx.make_parcel("1")
		res = importer.import_remittance(self.make_file([self.remit_row("R1", p.awb)], REMIT_HEAD), self.fx.courier)
		self.assertEqual((res["remittances"], res["lines"], res["skipped"]), (["IMM-R1"], 1, 0))
		self.assertEqual(res["matching"]["matched"], 1)
		rem = frappe.get_doc("Courier Remittance", "IMM-R1")
		self.assertEqual((rem.docstatus, rem.source, rem.utr_number), (1, "Excel", "UTR1"))
		self.assertEqual(rem.batch_status, "Reconciled")
		self.assertEqual(frappe.db.get_value("COD Parcel", p.name, "payout_status"), "Paid")

	def test_one_remittance_per_remittance_id(self):
		a, b = self.fx.make_parcel("2"), self.fx.make_parcel("3")
		rows = [self.remit_row("RA", a.awb), self.remit_row("RB", b.awb)]
		res = importer.import_remittance(self.make_file(rows, REMIT_HEAD), self.fx.courier)
		self.assertEqual(sorted(res["remittances"]), ["IMM-RA", "IMM-RB"])
		self.assertEqual(res["matching"]["matched"], 2)

	def test_short_paid_and_unknown_lines_are_counted(self):
		p = self.fx.make_parcel("4")
		rows = [self.remit_row("R2", p.awb, net=NET_1KG - 60), self.remit_row("R2", "IMMGHOST", net=300)]
		res = importer.import_remittance(self.make_file(rows, REMIT_HEAD), self.fx.courier)
		self.assertEqual((res["matching"]["short-paid"], res["matching"]["unknown"]), (1, 1))

	def test_importing_the_same_remittance_twice_creates_nothing(self):
		p = self.fx.make_parcel("5")
		url = self.make_file([self.remit_row("R3", p.awb)], REMIT_HEAD)
		importer.import_remittance(url, self.fx.courier)
		again = importer.import_remittance(url, self.fx.courier)
		self.assertEqual((again["remittances"], again["duplicates"]), ([], ["IMM-R3"]))
		self.assertIn("already imported", again["message"])
		self.assertEqual(frappe.db.count("Courier Remittance", {"courier": self.fx.courier}), 1)

	def test_invalid_lines_are_skipped_but_valid_ones_import(self):
		p = self.fx.make_parcel("6")
		rows = [self.remit_row("R4", p.awb), self.remit_row("R4", "", net=5)]
		res = importer.import_remittance(self.make_file(rows, REMIT_HEAD), self.fx.courier)
		self.assertEqual((res["lines"], res["skipped"]), (1, 1))
		self.assertEqual(res["errors"][0]["row"], 3)

	def test_remittance_with_no_valid_lines_is_not_created(self):
		res = importer.import_remittance(self.make_file([self.remit_row("R5", "", net=5)], REMIT_HEAD), self.fx.courier)
		self.assertEqual(res["remittances"], [])
		self.assertIn("no valid lines", res["errors"][-1]["reason"])
		self.assertFalse(frappe.db.exists("Courier Remittance", "IMM-R5"))

	def test_utr_is_used_as_the_batch_id_when_remittance_id_is_blank(self):
		p = self.fx.make_parcel("10")
		row = ["", str(datetime.date.today()), "IMM-UTR-ONLY", p.awb, 1000, NET_1KG]
		res = importer.import_remittance(self.make_file([row], REMIT_HEAD), self.fx.courier)
		self.assertEqual(res["remittances"], ["IMM-UTR-ONLY"])

	def test_rows_without_a_remittance_id_are_reported(self):
		p = self.fx.make_parcel("7")
		res = importer.import_remittance(self.make_file([self.remit_row(None, p.awb)], REMIT_HEAD), self.fx.courier)
		self.assertEqual(res["remittances"], [])
		self.assertEqual(res["errors"][0]["reason"], "Remittance ID (or UTR) is required")

	def test_courier_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			importer.import_remittance(self.make_file([self.remit_row("R6", "A")], REMIT_HEAD), "")

	def test_future_remittance_date_fails_that_batch_only(self):
		p, q = self.fx.make_parcel("8"), self.fx.make_parcel("9")
		future = str(datetime.date.today() + datetime.timedelta(days=5))
		rows = [self.remit_row("R7", p.awb, date=future), self.remit_row("R8", q.awb)]
		res = importer.import_remittance(self.make_file(rows, REMIT_HEAD), self.fx.courier)
		self.assertEqual(res["remittances"], ["IMM-R8"])
		self.assertFalse(frappe.db.exists("Courier Remittance", "IMM-R7"))
		self.assertTrue(any("IMM-R7" in e["reason"] for e in res["errors"]))


class TestRunImportAndPermissions(ImporterCase):
	prefix = "IMX"

	def test_unknown_type_and_missing_courier_are_refused(self):
		url = self.make_file([["x"]], ["Order ID"])
		with self.assertRaises(frappe.ValidationError):
			importer.run_import("Nonsense", url)
		with self.assertRaises(frappe.ValidationError):
			importer.run_import("Remittance", url)

	def test_small_file_runs_inline(self):
		res = importer.run_import("Parcels", self.make_file([self.parcel_row("1")], PARCEL_HEAD), self.fx.courier)
		self.assertEqual(res["created"], 1)

	def test_large_file_is_queued_not_run(self):
		rows = [[f"{self.prefix}-Q{i}", f"{self.prefix}Q{i}"] for i in range(importer.BACKGROUND_ROWS + 1)]
		url = self.make_file(rows, ["Order ID", "AWB"])
		with patch("codsync.codsync.importer.frappe.enqueue") as enqueue:
			res = importer.run_import("Parcels", url, self.fx.courier)
		self.assertEqual(res, {"queued": True, "rows": importer.BACKGROUND_ROWS + 1})
		enqueue.assert_called_once()
		self.assertFalse(frappe.db.exists("COD Parcel", f"{self.prefix}-Q0"))

	def test_save_mapping_back_stores_it_on_the_courier(self):
		url = self.make_file([["O1", "A1"]], ["Ref No", "Tracking"])
		importer.run_import("Parcels", url, self.fx.courier, {"ref no": "order_id", "tracking": "awb"}, save_mapping_back=1)
		saved = frappe.parse_json(frappe.db.get_value("Courier", self.fx.courier, "parcels_mapping"))
		self.assertEqual(saved, {"ref no": "order_id", "tracking": "awb"})

	def test_saved_mapping_is_used_on_the_next_import(self):
		importer.save_mapping(self.fx.courier, "Parcels", {"Ref No": "order_id", "Total": "cod_amount"})
		url = self.make_file([["IMX-M1", 750]], ["Ref No", "Total"])
		res = importer.import_parcels(url, self.fx.courier)
		self.assertEqual(res["created"], 1)
		self.assertEqual(frappe.db.get_value("COD Parcel", "IMX-M1", "cod_amount"), 750)

	def test_users_without_a_codsync_role_cannot_import(self):
		url = self.make_file([self.parcel_row("2")], PARCEL_HEAD)
		frappe.set_user("Guest")
		for call in (
			lambda: importer.preview_import(url, "Parcels"),
			lambda: importer.import_parcels(url, self.fx.courier),
			lambda: importer.import_remittance(url, self.fx.courier),
			lambda: importer.run_import("Parcels", url, self.fx.courier),
			lambda: importer.save_mapping(self.fx.courier, "Parcels", {}),
		):
			with self.assertRaises(frappe.PermissionError):
				call()
