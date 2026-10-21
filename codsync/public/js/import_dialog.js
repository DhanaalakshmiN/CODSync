// Excel / CSV import dialog shared by the COD Parcel and Courier Remittance lists.
// Steps: pick file (+ courier) -> Preview (nothing saved) -> Confirm.
frappe.provide("codsync");

codsync.import_dialog = function (import_type, listview) {
	const remittance = import_type === "Remittance";
	const api = "codsync.codsync.importer.";
	let preview = null;

	const fields = [
		{
			fieldname: "courier",
			fieldtype: "Link",
			options: "Courier",
			label: __("Courier"),
			reqd: remittance ? 1 : 0,
			description: remittance ? "" : __("Optional: used for rows without a Courier column"),
			onchange: () => reset(),
		},
		{
			fieldname: "file",
			fieldtype: "Attach",
			label: __("File (xlsx, xls or csv)"),
			reqd: 1,
			options: { restrictions: { allowed_file_types: [".xlsx", ".xls", ".csv"] } },
			onchange: () => reset(),
		},
		{ fieldname: "result", fieldtype: "HTML" },
		{
			fieldname: "save_mapping",
			fieldtype: "Check",
			hidden: 1,
			label: __("Save this mapping on the Courier for next time"),
		},
	];
	const d = new frappe.ui.Dialog({
		title: remittance ? __("Import Remittance") : __("Import Parcels"),
		size: "extra-large",
		fields,
		primary_action_label: __("Preview"),
		primary_action: () => (preview ? confirm() : run_preview()),
		secondary_action_label: __("Close"),
		secondary_action: () => d.hide(),
	});

	function reset() {
		preview = null;
		d.set_primary_action(__("Preview"), () => run_preview());
		d.get_field("save_mapping").toggle(false);
		d.get_field("result").$wrapper.empty();
	}
	const esc = frappe.utils.escape_html;
	const args = () => ({
		file_url: d.get_value("file"),
		import_type,
		courier: d.get_value("courier") || null,
	});

	function table(head, rows) {
		return `<div style="overflow-x:auto"><table class="table table-bordered table-sm" style="font-size:12px">
			<thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
			<tbody>${rows
				.map((r) => `<tr>${r.map((c) => `<td>${esc(c ?? "")}</td>`).join("")}</tr>`)
				.join("")}</tbody></table></div>`;
	}

	function run_preview() {
		const v = d.get_values();
		if (!v) return;
		frappe.call({
			method: api + "preview_import",
			args: args(),
			freeze: true,
			freeze_message: __("Reading file..."),
			callback(r) {
				preview = r.message;
				render(preview);
			},
		});
	}

	function render(p) {
		const mapped = p.mapping.filter((m) => m.field);
		const unmapped = p.mapping.filter((m) => !m.field).map((m) => m.header);
		let html = `<p><b>${__("Detected headers")}:</b> ${p.headers
			.map((h) => `<code>${esc(h)}</code>`)
			.join(" ")}</p>`;
		html += `<p><b>${__("Mapping")}</b> (${esc(
			p.mapping_source === "saved" ? __("saved on Courier") : __("auto-detected")
		)}):</p>`;
		html += table(
			[__("File column"), __("Field"), __("Source")],
			mapped.map((m) => [m.header, m.field, m.source])
		);
		if (unmapped.length)
			html += `<p class="text-muted">${__("Ignored columns")}: ${unmapped
				.map(esc)
				.join(", ")}</p>`;
		if (p.preview.length) {
			html += `<p><b>${__("First {0} rows", [p.preview.length])}</b></p>`;
			html += table(
				["#", ...p.fields],
				p.preview.map((r) => [r.row, ...p.fields.map((f) => r[f])])
			);
		}
		html += `<p><b>${__("Rows")}:</b> ${p.row_count} &nbsp; <span class="text-success"><b>${__(
			"Valid"
		)}:</b> ${p.valid_count}</span>
			&nbsp; <span class="text-danger"><b>${__("Invalid")}:</b> ${p.invalid_count}</span>`;
		if (!remittance)
			html += ` &nbsp; ${__("Will create")}: ${p.will_create} &nbsp; ${__("Will update")}: ${
				p.will_update
			}`;
		html += `</p>`;
		if (p.invalid_rows.length) {
			html += table(
				[__("Row"), __("Reason")],
				p.invalid_rows.map((r) => [r.row, r.reason])
			);
			if (p.invalid_count > p.invalid_rows.length)
				html += `<p class="text-muted">${__("Showing the first {0} invalid rows", [
					p.invalid_rows.length,
				])}</p>`;
			html += `<p class="text-muted">${__("Invalid rows are skipped on import.")}</p>`;
		}
		if (remittance && p.duplicate_batches.length) {
			html += `<div class="alert alert-warning">${__(
				"Remittance {0} is already imported. Nothing will be created for it.",
				[p.duplicate_batches.map(esc).join(", ")]
			)}</div>`;
		}
		if (p.background)
			html += `<p class="text-muted">${__(
				"Large file: the import will run in the background."
			)}</p>`;
		d.get_field("result").$wrapper.html(html);

		const can =
			p.valid_count > 0 &&
			!(remittance && p.duplicate_batches.length === p.batches.length && p.batches.length);
		d.get_field("save_mapping").toggle(
			!!d.get_value("courier") && p.mapping_source !== "saved"
		);
		if (can) d.set_primary_action(__("Confirm import"), () => confirm());
		else d.set_primary_action(__("Preview again"), () => run_preview());
	}

	function confirm() {
		const a = args();
		a.save_mapping_back = d.get_value("save_mapping") ? 1 : 0;
		d.hide();
		frappe.call({
			method: api + "run_import",
			args: a,
			freeze: true,
			freeze_message: __("Importing..."),
			callback(r) {
				const res = r.message;
				if (res.queued) {
					frappe.show_alert({
						message: __(
							"Importing {0} rows in the background. You will be notified.",
							[res.rows]
						),
						indicator: "blue",
					});
					frappe.realtime.on("codsync_import_done", function once(result) {
						frappe.realtime.off("codsync_import_done", once);
						summary(result);
					});
				} else {
					summary(res);
				}
			},
		});
	}

	function summary(res) {
		const m = res.matching || {};
		let html;
		if (res.import_type === "Remittance") {
			html = `<p>${__("Remittances created")}: <b>${(res.remittances || []).length}</b> ${(
				res.remittances || []
			)
				.map(esc)
				.join(", ")}<br>
				${__("Lines")}: <b>${res.lines}</b></p>
				<p>${__("Matching")}: ${__("matched")} <b>${m.matched || 0}</b>, ${__("short-paid")} <b>${
				m["short-paid"] || 0
			}</b>,
				${__("unknown")} <b>${m.unknown || 0}</b>, ${__("exceptions")} <b>${m.exceptions || 0}</b></p>`;
			if (res.message) html = `<p>${esc(res.message)}</p>` + html;
		} else {
			html = `<p>${__("Created")}: <b>${res.created}</b> &nbsp; ${__("Updated")}: <b>${
				res.updated
			}</b> &nbsp; ${__("Skipped")}: <b>${res.skipped}</b></p>`;
		}
		if (res.errors && res.errors.length) {
			html += table(
				[__("Row"), __("Reason")],
				res.errors.map((e) => [e.row, e.reason])
			);
		}
		frappe.msgprint({
			title: __("Import finished"),
			message: html,
			wide: true,
			indicator: res.errors && res.errors.length ? "orange" : "green",
		});
		if (listview) listview.refresh();
	}

	d.show();
	return d;
};
