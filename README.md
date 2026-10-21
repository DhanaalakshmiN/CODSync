# CODSync

CODSync is a Frappe app that reconciles Cash-on-Delivery (COD) payouts from courier companies with the orders and shipments recorded in your store. It highlights payments that are paid, short-paid, awaiting payout, missing or unknown, so finance teams can follow up on the right orders.

## Features

- **Store connections** for Shopify, WooCommerce and Odoo to fetch orders.
- **Courier settlements** imported from Excel files or through the API, with remittance batches and per-order lines.
- **Automatic matching** of settlement lines to orders, with a tolerance for small differences.
- **Reconciliation statuses**: Paid, Short-paid, Awaiting payout, Missing and Unknown.
- **Exceptions queue** for orders and payouts that need manual review.
- **Shipment tracking** events per parcel.
- **Reports**: COD Aging, Courier Outstanding, Payout Reconciliation and Unmatched Payout Lines.
- **Dashboard** with number cards and charts, plus a single-page web interface at `/cod-ledger`.

## Requirements

- Python 3.14 or later
- Frappe Framework, branch `version-16`
- Node.js and Yarn (only to rebuild the web interface)

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/DhanaalakshmiN/CODSync --branch main
bench --site your-site install-app codsync
bench --site your-site migrate
```

Then log in to your site and open `/cod-ledger`.

## Frontend development

The web interface is a Vue app in `frontend/`. A production build is written to `codsync/public/frontend`.

```bash
cd apps/codsync/frontend
yarn install
yarn dev      # dev server at http://codsync.localhost:5173/cod-ledger
yarn build    # production build
```

For the dev server, log in at `http://codsync.localhost:8000/login` first so the session cookie is available.

## Project structure

```
codsync/
├── codsync/
│   ├── doctype/       # DocTypes and their validations
│   ├── platforms/     # Shopify, WooCommerce and Odoo connectors
│   ├── report/        # Script reports
│   ├── api.py         # Whitelisted API methods
│   ├── ui_api.py      # API used by the web interface
│   ├── importer.py    # Settlement import
│   ├── matching.py    # Order-to-payout matching
│   ├── engine.py      # Reconciliation engine
│   └── tasks.py       # Scheduled jobs
├── public/            # Static assets and the built frontend
├── www/               # Web page served at /cod-ledger
└── hooks.py
frontend/              # Vue source for the web interface
```

## Contributing

Work happens on feature branches that open pull requests into `develop`. Changes are released by merging `develop` into `main`.

This app uses `pre-commit` for formatting and linting:

```bash
cd apps/codsync
pre-commit install
```

Tools used: ruff, eslint, prettier and pyupgrade.

## CI

- **CI** installs the app and runs unit tests on every push to `develop`.
- **Linters** run [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.

## License

MIT. See [license.txt](license.txt).
