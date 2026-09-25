# Reading the Coupa data

| Result | Where the colleague finds it | Key fields |
|---|---|---|
| `get_servicenow_coupa_flow` | `data/coupa/get_servicenow_coupa_flow.json` → `flows[]` | `service-now-request`, `employee`, `blocked-reason`, `requisition`, `purchase_order`, `receipts[]`, `invoices[]`, `supplier` |
| `list_approvals` | `data/coupa/list_approvals.json` → `results[]` | `id` (APR-…), `type` (Requisition, Invoice, Purchase Order), `title`, `total`, `submitted-at`, `risk`, `service-now-request` |
| `get_category_manager_dashboard` | `data/coupa/get_category_manager_dashboard.json` | `as_of`, `alerts[]`, `demand[]`, `supplier_performance[]` |
| `get_item_demand` | `data/coupa/get_item_demand.json` → `items[]` | `id`, `unit-price`, `supplier-id`, `lead-time-days`, `contracted`, `stock`, `monthly-demand`, `open_quantity`, `risk` |
| `list_suppliers` | `data/coupa/list_suppliers.json` → `results[]` | `id`, `tier`, `risk`, `preferred`, `contract.expires`, `metrics.on_time_rate`, `metrics.defect_rate` |

Purchase-order fields inside a flow:

- `lines[]` — `item-id`, `quantity` ordered, `received` quantity, `unit-price`.
- `received-value` / `open-value` — value received and still open.
- `expected-delivery`, `days-to-delivery` (negative means late), `delivery-risk` (`late`, `at_risk`, `on_track`).
- `status` — `issued`, `pending_supplier_ack`, `supplier_acknowledged`, `partially_received`, `closed`.

Invoice fields: `invoice-number` (use it as `invoice_id`), `status` (`pending_approval`, `approved`, `paid`),
`total`, `payment-status` (`Not Paid`, `Scheduled`, `Paid`), `due-date`.

Receipts: `received-by` is an email address; compare its local part with the requester's name for
segregation of duties.

`open_quantity` in item demand is quantity still open on existing POs. Those units are already allocated to
the requests that ordered them, so stock cover is measured on stock alone.

Amounts are strings with thousands separators ("24,642.00"); the scripts convert them.
