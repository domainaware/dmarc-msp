"""One-shot data migrations for existing OpenSearch indices.

These commands exist to repair data written by older parsedmarc versions:

* ``rename_asn_fields`` — the old ``source_asn_name`` / ``source_asn_domain``
  fields were renamed upstream to ``source_as_name`` / ``source_as_domain``.
  Existing documents still use the old names.
* ``refill_enrichment_fields`` — parsedmarc's IP-based enrichment has improved
  (GeoIP swap ipdb → ipinfo, better source-name/type classification). Old
  documents carry stale values. We call ``parsedmarc.utils.get_ip_address_info``
  inside the parsedmarc container so old docs get the exact same enrichment
  new docs get.

``DashboardService.refresh_index_pattern_fields`` handles the third piece
(refreshing the cached field list inside each tenant's index-pattern saved
objects) and is invoked by the CLI alongside these two.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field

from opensearchpy import NotFoundError, OpenSearch

from dmarc_msp.config import OpenSearchConfig

logger = logging.getLogger(__name__)

# Indices that carry source_ip_address / source_country / ASN / source_name /
# source_type. smtp_tls reports have a different shape and are excluded.
DMARC_INDEX_PATTERN = "*_dmarc_aggregate*,*_dmarc_fo*"

# Map OpenSearch doc field names (prefixed with source_) to the keys returned
# by parsedmarc.utils.get_ip_address_info. Only fields listed here are allowed
# via --fields; unknown names would have no lookup source.
FIELD_TO_PARSEDMARC_KEY: dict[str, str] = {
    "source_country": "country",
    "source_name": "name",
    "source_type": "type",
    "source_as_name": "as_name",
    "source_as_domain": "as_domain",
}
DEFAULT_ENRICHMENT_FIELDS: tuple[str, ...] = tuple(FIELD_TO_PARSEDMARC_KEY.keys())

# Painless move-field script: if the old field exists, copy to the new name
# and remove the old one. ctx.op='noop' when neither field is present keeps
# the cluster from touching docs that are already on the new schema.
_RENAME_ASN_SCRIPT = """
boolean changed = false;
if (ctx._source.containsKey('source_asn_name')) {
    ctx._source.source_as_name = ctx._source.remove('source_asn_name');
    changed = true;
}
if (ctx._source.containsKey('source_asn_domain')) {
    ctx._source.source_as_domain = ctx._source.remove('source_asn_domain');
    changed = true;
}
if (!changed) { ctx.op = 'noop'; }
""".strip()

# Painless patch script: for each doc, look up its source_ip_address in the
# caller-supplied map; if there's an entry, overwrite any target fields that
# differ. Uses ctx.op='noop' when there's nothing to do so the cluster skips
# writing the doc entirely.
_ENRICHMENT_PATCH_SCRIPT = """
if (ctx._source.source_ip_address == null) { ctx.op = 'noop'; return; }
String ip = ctx._source.source_ip_address;
if (!params.ip_to_enrichment.containsKey(ip)) { ctx.op = 'noop'; return; }
Map enrichment = params.ip_to_enrichment.get(ip);
boolean changed = false;
for (entry in enrichment.entrySet()) {
    String f = entry.getKey();
    def v = entry.getValue();
    if (v == null) { continue; }
    def existing = ctx._source.get(f);
    if (existing == null || !v.equals(existing)) {
        ctx._source.put(f, v);
        changed = true;
    }
}
if (!changed) { ctx.op = 'noop'; }
""".strip()

# Script run inside the parsedmarc container. Reads a JSON list of IPs from
# stdin and writes a JSON dict {ip: info_dict_or_null} to stdout. offline=True
# skips DNS/WHOIS so we only hit the local GeoIP DB and name/type classifier.
_PARSEDMARC_LOOKUP_SCRIPT = r"""
import json, sys
from parsedmarc.utils import get_ip_address_info

ips = json.load(sys.stdin)
out = {}
for ip in ips:
    try:
        info = get_ip_address_info(ip, offline=True, parallel=False)
        out[ip] = info
    except Exception as exc:
        out[ip] = None
        print(f"lookup-failed {ip}: {exc}", file=sys.stderr)
json.dump(out, sys.stdout)
"""


@dataclass
class RenameAsnResult:
    total: int
    updated: int
    failures: int


@dataclass
class EnrichmentFixResult:
    unique_ips: int
    resolved_ips: int
    updated_docs: int
    fields_requested: list[str] = field(default_factory=list)


class MigrationService:
    """One-shot data-repair operations against existing OpenSearch data."""

    def __init__(
        self,
        opensearch_config: OpenSearchConfig,
        parsedmarc_container: str = "parsedmarc",
    ):
        self.client = OpenSearch(
            hosts=[opensearch_config.hosts],
            http_auth=(
                opensearch_config.username,
                opensearch_config.resolved_password,
            ),
            use_ssl=opensearch_config.ssl,
            verify_certs=opensearch_config.verify_certs,
            ssl_show_warn=False,
        )
        self.parsedmarc_container = parsedmarc_container

    # ── 1. Rename source_asn_* → source_as_* ──────────────────────────

    def rename_asn_fields(
        self,
        index_pattern: str = DMARC_INDEX_PATTERN,
        poll_interval: float = 2.0,
    ) -> RenameAsnResult:
        """Rewrite docs where source_asn_{name,domain} exist to use
        source_as_{name,domain}. Safe to re-run; no-op on clean docs."""
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"exists": {"field": "source_asn_name"}},
                        {"exists": {"field": "source_asn_domain"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "script": {"source": _RENAME_ASN_SCRIPT, "lang": "painless"},
        }
        logger.info("Starting ASN rename update_by_query on '%s'", index_pattern)
        response = self.client.transport.perform_request(
            "POST",
            f"/{index_pattern}/_update_by_query",
            params={
                "conflicts": "proceed",
                "wait_for_completion": "false",
                "refresh": "true",
                "slices": "auto",
            },
            body=body,
        )
        task_id = response["task"]
        status = self._wait_for_task(task_id, poll_interval)
        return RenameAsnResult(
            total=status.get("total", 0),
            updated=status.get("updated", 0),
            failures=len(status.get("failures", [])),
        )

    # ── 2. Re-enrich source_country / source_name / source_type ───────

    def refill_enrichment_fields(
        self,
        index_pattern: str = DMARC_INDEX_PATTERN,
        fields: list[str] | tuple[str, ...] = DEFAULT_ENRICHMENT_FIELDS,
        lookup_batch: int = 500,
        update_batch: int = 500,
        poll_interval: float = 2.0,
    ) -> EnrichmentFixResult:
        """Collect every unique source_ip_address in ``index_pattern``,
        look up each IP via ``parsedmarc.utils.get_ip_address_info`` inside
        the parsedmarc container, and update_by_query to overwrite the
        requested doc fields where they differ.

        ``fields`` must be doc-side names (e.g. ``source_country``); unknown
        names raise ValueError.
        """
        unknown = [f for f in fields if f not in FIELD_TO_PARSEDMARC_KEY]
        if unknown:
            raise ValueError(
                f"Unknown enrichment field(s): {unknown}. "
                f"Supported: {sorted(FIELD_TO_PARSEDMARC_KEY)}"
            )
        if not fields:
            raise ValueError("At least one enrichment field must be specified")

        ips = sorted(self._collect_source_ips(index_pattern))
        if not ips:
            logger.info("No source_ip_address values found in '%s'", index_pattern)
            return EnrichmentFixResult(0, 0, 0, list(fields))
        logger.info(
            "Collected %d unique source IPs from '%s' for fields %s",
            len(ips),
            index_pattern,
            list(fields),
        )

        ip_to_enrichment: dict[str, dict[str, str]] = {}
        for start in range(0, len(ips), lookup_batch):
            chunk = ips[start : start + lookup_batch]
            results = self._lookup_enrichment(chunk)
            for ip, info in results.items():
                if not info:
                    continue
                patch = {}
                for doc_field in fields:
                    pm_key = FIELD_TO_PARSEDMARC_KEY[doc_field]
                    val = info.get(pm_key)
                    if val:
                        patch[doc_field] = val
                if patch:
                    ip_to_enrichment[ip] = patch
            logger.info(
                "Looked up %d/%d IPs (resolved %d so far)",
                min(start + lookup_batch, len(ips)),
                len(ips),
                len(ip_to_enrichment),
            )

        if not ip_to_enrichment:
            logger.warning(
                "No enrichment values resolved for fields %s; nothing to patch",
                list(fields),
            )
            return EnrichmentFixResult(len(ips), 0, 0, list(fields))

        updated_docs = 0
        resolved_ips = sorted(ip_to_enrichment.keys())
        for start in range(0, len(resolved_ips), update_batch):
            chunk = resolved_ips[start : start + update_batch]
            chunk_map = {ip: ip_to_enrichment[ip] for ip in chunk}
            updated_docs += self._apply_enrichment_patch(
                index_pattern, chunk_map, poll_interval
            )
            logger.info(
                "Patched %d/%d IP buckets (docs updated so far: %d)",
                min(start + update_batch, len(resolved_ips)),
                len(resolved_ips),
                updated_docs,
            )

        return EnrichmentFixResult(
            unique_ips=len(ips),
            resolved_ips=len(ip_to_enrichment),
            updated_docs=updated_docs,
            fields_requested=list(fields),
        )

    # ── Internals ─────────────────────────────────────────────────────

    def _collect_source_ips(self, index_pattern: str) -> set[str]:
        """Return the set of unique source_ip_address values across the
        matching indices. Uses a composite terms aggregation so it scales
        past the 10k terms-agg default without loading every doc.

        parsedmarc's dynamic mapping gives every string field a ``.keyword``
        subfield; aggregations and terms filters on the text field fail with
        a fielddata error, so we always target ``<field>.keyword``.
        """
        ips: set[str] = set()
        after: dict | None = None
        while True:
            body: dict = {
                "size": 0,
                "aggs": {
                    "ips": {
                        "composite": {
                            "size": 1000,
                            "sources": [
                                {
                                    "ip": {
                                        "terms": {"field": "source_ip_address.keyword"}
                                    }
                                }
                            ],
                        }
                    }
                },
            }
            if after is not None:
                body["aggs"]["ips"]["composite"]["after"] = after
            try:
                resp = self.client.transport.perform_request(
                    "POST",
                    f"/{index_pattern}/_search",
                    body=body,
                )
            except NotFoundError:
                logger.warning("Index pattern '%s' matched nothing", index_pattern)
                return ips
            buckets = resp.get("aggregations", {}).get("ips", {}).get("buckets", [])
            if not buckets:
                break
            for b in buckets:
                ip = b["key"].get("ip")
                if ip:
                    ips.add(ip)
            after = resp["aggregations"]["ips"].get("after_key")
            if after is None:
                break
        return ips

    def _lookup_enrichment(self, ips: list[str]) -> dict[str, dict | None]:
        """Run the parsedmarc geoip helper inside the parsedmarc container
        and return {ip: info_dict_or_None}."""
        try:
            proc = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    self.parsedmarc_container,
                    "python3",
                    "-c",
                    _PARSEDMARC_LOOKUP_SCRIPT,
                ],
                input=json.dumps(ips),
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "Docker CLI not found. The migrate command must run where "
                "the parsedmarc container is reachable via 'docker exec'."
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"parsedmarc enrichment lookup failed (exit {e.returncode}): "
                f"{e.stderr.strip() or e.stdout.strip()}"
            ) from e
        if proc.stderr.strip():
            logger.debug("parsedmarc lookup stderr: %s", proc.stderr.strip())
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Could not parse parsedmarc lookup output: {e}\n"
                f"stdout: {proc.stdout[:500]}"
            ) from e

    def _apply_enrichment_patch(
        self,
        index_pattern: str,
        ip_to_enrichment: dict[str, dict[str, str]],
        poll_interval: float,
    ) -> int:
        body = {
            "query": {
                "terms": {"source_ip_address.keyword": list(ip_to_enrichment.keys())}
            },
            "script": {
                "source": _ENRICHMENT_PATCH_SCRIPT,
                "lang": "painless",
                "params": {"ip_to_enrichment": ip_to_enrichment},
            },
        }
        response = self.client.transport.perform_request(
            "POST",
            f"/{index_pattern}/_update_by_query",
            params={
                "conflicts": "proceed",
                "wait_for_completion": "false",
                "refresh": "true",
                "slices": "auto",
            },
            body=body,
        )
        status = self._wait_for_task(response["task"], poll_interval)
        return status.get("updated", 0)

    def _wait_for_task(self, task_id: str, poll_interval: float) -> dict:
        while True:
            resp = self.client.transport.perform_request("GET", f"/_tasks/{task_id}")
            if resp.get("completed"):
                response = resp.get("response", {})
                failures = response.get("failures", [])
                if failures:
                    logger.warning(
                        "update_by_query completed with %d failure(s): %s",
                        len(failures),
                        failures[:3],
                    )
                return response
            time.sleep(poll_interval)
