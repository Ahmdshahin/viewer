import { RequestLedger } from "./Requests";

/**
 * The Mudryia (طلبات المديريات) request ledger. Reuses the shared ledger UI
 * because this record shape is a deliberate full mirror of the company
 * Requests ledger, including the shared governorate / center / village /
 * area-unit lookups. Only the API prefix, the heading and the map layer it
 * deep-links to differ.
 */
export default function MudryiaRequests() {
  return (
    <RequestLedger
      base="/api/v1/mudryia-requests"
      title="طلبات المديريات"
      mapLayer="mudryia"
      emptyText="No mudryia requests match the filters"
    />
  );
}
