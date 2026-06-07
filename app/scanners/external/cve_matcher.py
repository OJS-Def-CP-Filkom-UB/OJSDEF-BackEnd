import json
import redis.asyncio as aioredis
from app.scanners.models import FindingResult, make_finding

try:
    from app.config import get_settings
    _settings = get_settings()
except Exception:
    # Fallback for environments where pydantic-settings is not configured
    class _FallbackSettings:
        redis_url: str = "redis://localhost:6379/0"
        cve_api_key: str = ""
    _settings = _FallbackSettings()


async def lookup_cves(software: str, version: str) -> list[str]:
    """
    Look up CVEs for a given software+version combination.
    Results are cached in Redis with TTL of 86400 seconds (24 hours).
    Cache key format: cve_cache:{software}:{version}
    Returns list of CVE IDs (empty list on any error).
    """
    key = f"cve_cache:{software}:{version}"
    cve_ids: list[str] = []

    r = aioredis.from_url(_settings.redis_url, decode_responses=True)
    try:
        cached = await r.get(key)
        if cached is not None:
            return json.loads(cached)

        # Attempt NVD lookup via nvdlib
        try:
            import nvdlib
            results = nvdlib.searchCVE(
                keywordSearch=f"{software} {version}",
                apiKey=_settings.cve_api_key or None,
            )
            cve_ids = [r_item.id for r_item in results[:10]]
        except Exception:
            cve_ids = []

        await r.setex(key, 86400, json.dumps(cve_ids))
    except Exception:
        cve_ids = []
    finally:
        await r.aclose()

    return cve_ids


async def scan_cve(ojs_version: str | None) -> list[FindingResult]:
    """
    Match known CVEs for the detected OJS version.
    Returns empty list if ojs_version is None or on any error.
    """
    if not ojs_version:
        return []

    cve_ids = await lookup_cves("OJS Open Journal Systems", ojs_version)

    return [
        make_finding(
            "cve_ojs",
            category="external",
            title=f"OJS {ojs_version} Rentan terhadap {cve_id}",
            description=(
                f"Versi OJS {ojs_version} yang terinstal memiliki kerentanan yang "
                f"tercatat di National Vulnerability Database (NVD): {cve_id}."
            ),
            affected_path="/",
            evidence=f"ojs_version={ojs_version}, cve={cve_id}",
            remediation=(
                f"Update OJS ke versi terbaru yang telah memperbaiki kerentanan ini. "
                f"Tinjau advisory keamanan untuk {cve_id}."
            ),
            references=[
                f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                "https://pkp.sfu.ca/category/news/announcements/releases/",
                "https://forum.pkp.sfu.ca/c/questions-and-answers/security/",
                "https://docs.pkp.sfu.ca/dev/upgrade-guide/",
            ],
            cve_id=cve_id,
        )
        for cve_id in cve_ids
    ]
