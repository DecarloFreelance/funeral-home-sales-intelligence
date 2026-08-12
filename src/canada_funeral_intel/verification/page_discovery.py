from __future__ import annotations

import heapq
import sqlite3
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from canada_funeral_intel.normalization.scalars import normalize_domain, normalize_url
from canada_funeral_intel.storage.database import transaction
from canada_funeral_intel.verification.content_analysis import analyze_website_content
from canada_funeral_intel.verification.probe import probe_http


class PageDiscoveryError(RuntimeError):
    """Raised when bounded website page discovery cannot complete safely."""


@dataclass(frozen=True, slots=True)
class DiscoveredPage:
    website_id: int
    url: str
    normalized_url: str
    path: str
    page_kind: str
    priority_score: int
    depth: int
    discovered_from_url: str | None = None
    link_text: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    identity_score: float | None = None
    identity_observable: bool = False


@dataclass(frozen=True, slots=True)
class PageDiscoveryRun:
    website_id: int
    pages_requested: int
    pages_persisted: int
    links_seen: int
    links_queued: int
    excluded_links: int
    offsite_links: int
    max_pages: int
    max_depth: int


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "a":
            return

        href = next(
            (value for name, value in attrs if name.casefold() == "href" and value),
            None,
        )
        self._href = href
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None and data.strip():
            self._text.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return

        self.links.append(
            (
                self._href,
                " ".join(self._text).strip(),
            )
        )
        self._href = None
        self._text = []


_PRIORITY_RULES: tuple[tuple[str, str, int], ...] = (
    ("funeral-director", "directors", 100),
    ("funeral_director", "directors", 100),
    ("funeral director", "directors", 100),
    ("directors", "directors", 96),
    ("our-team", "team", 95),
    ("our_team", "team", 95),
    ("our team", "team", 95),
    ("team", "team", 92),
    ("staff", "staff", 92),
    ("people", "people", 88),
    ("professionals", "professionals", 88),
    ("management", "management", 86),
    ("personnel", "personnel", 86),
    ("équipe", "team", 92),
    ("equipe", "team", 92),
    ("à-propos", "about", 84),
    ("a-propos", "about", 84),
    ("about-us", "about", 84),
    ("about_us", "about", 84),
    ("about", "about", 80),
    ("contact-us", "contact", 82),
    ("contact_us", "contact", 82),
    ("contact", "contact", 78),
    ("locations", "locations", 76),
    ("location", "locations", 72),
    ("history", "history", 68),
)

_EXCLUDED_TOKENS = (
    "obituary",
    "obituaries",
    "obits",
    "tribute",
    "tributes",
    "memorials",
    "death-notice",
    "death_notice",
    "deathnotice",
    "checkout",
    "shopping-cart",
    "shopping_cart",
    "/cart",
    "/login",
    "/signin",
    "/sign-in",
    "/account",
    "/register",
    "/privacy",
    "/terms",
    "/cookie",
    "/wp-admin",
    "/wp-login",
)

_IGNORED_SCHEMES = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
)


def classify_page(
    url: str,
    link_text: str | None = None,
) -> tuple[str, int]:
    parsed = urlsplit(url)
    path = parsed.path.casefold()
    text = "" if link_text is None else link_text.casefold()
    haystack = f"{path} {text}"

    if path in {"", "/"}:
        return "root", 50

    for token, kind, score in _PRIORITY_RULES:
        if token in haystack:
            return kind, score

    return "other", 10


def is_excluded_page(url: str) -> bool:
    value = url.casefold()
    return any(token in value for token in _EXCLUDED_TOKENS)


def extract_links(
    body: bytes,
    *,
    base_url: str,
    content_type: str | None,
) -> tuple[tuple[str, str], ...]:
    if content_type is None or "html" not in content_type.casefold():
        return ()

    parser = _LinkParser()
    parser.feed(body.decode("utf-8", errors="replace"))

    output: list[tuple[str, str]] = []
    seen: set[str] = set()

    for href, text in parser.links:
        href = href.strip()
        if not href or href.startswith("#"):
            continue
        if href.casefold().startswith(_IGNORED_SCHEMES):
            continue

        absolute = urljoin(base_url, href)
        normalized = normalize_url(absolute)
        if normalized.value is None:
            continue

        if normalized.value in seen:
            continue

        seen.add(normalized.value)
        output.append((normalized.value, text))

    return tuple(output)


def _normalized_domain(url: str) -> str | None:
    result = normalize_domain(url)
    return result.value


def _same_site(
    url: str,
    *,
    expected_domain: str,
) -> bool:
    return _normalized_domain(url) == expected_domain


def _load_website(
    connection: sqlite3.Connection,
    website_id: int,
) -> tuple[str, str, str]:
    if website_id < 1:
        raise PageDiscoveryError("website_id must be a positive integer")

    try:
        row = connection.execute(
            """
            SELECT
                websites.normalized_url,
                websites.domain,
                entities.canonical_name
            FROM websites
            JOIN entities ON entities.id = websites.entity_id
            WHERE websites.id = ?
            """,
            (website_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise PageDiscoveryError(f"Website lookup failed: {exc}") from exc

    if row is None:
        raise PageDiscoveryError(f"Website not found: {website_id}")

    return (
        str(row["normalized_url"]),
        str(row["domain"]),
        str(row["canonical_name"]),
    )


def upsert_website_page(
    connection: sqlite3.Connection,
    page: DiscoveredPage,
) -> int:
    try:
        with transaction(connection):
            existing = connection.execute(
                """
                SELECT id
                FROM website_pages
                WHERE website_id = ?
                  AND normalized_url = ?
                """,
                (
                    page.website_id,
                    page.normalized_url,
                ),
            ).fetchone()

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO website_pages (
                        website_id,
                        url,
                        normalized_url,
                        path,
                        page_kind,
                        priority_score,
                        depth,
                        discovered_from_url,
                        link_text,
                        status_code,
                        content_type,
                        identity_score,
                        identity_observable
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        page.website_id,
                        page.url,
                        page.normalized_url,
                        page.path,
                        page.page_kind,
                        page.priority_score,
                        page.depth,
                        page.discovered_from_url,
                        page.link_text,
                        page.status_code,
                        page.content_type,
                        page.identity_score,
                        int(page.identity_observable),
                    ),
                )
                if cursor.lastrowid is None:
                    raise PageDiscoveryError("Website page insert returned no row ID")
                return int(cursor.lastrowid)

            page_id = int(existing["id"])
            connection.execute(
                """
                UPDATE website_pages
                SET priority_score = MAX(priority_score, ?),
                    depth = MIN(depth, ?),
                    discovered_from_url =
                        COALESCE(discovered_from_url, ?),
                    link_text =
                        CASE
                            WHEN link_text IS NULL OR link_text = ''
                            THEN ?
                            ELSE link_text
                        END,
                    status_code = ?,
                    content_type = ?,
                    identity_score = ?,
                    identity_observable = ?,
                    updated_at =
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (
                    page.priority_score,
                    page.depth,
                    page.discovered_from_url,
                    page.link_text,
                    page.status_code,
                    page.content_type,
                    page.identity_score,
                    int(page.identity_observable),
                    page_id,
                ),
            )
            return page_id
    except sqlite3.Error as exc:
        raise PageDiscoveryError(f"Website page persistence failed: {exc}") from exc


def list_website_pages(
    connection: sqlite3.Connection,
    *,
    website_id: int | None,
) -> tuple[dict[str, object], ...]:
    if website_id is not None and website_id < 1:
        raise PageDiscoveryError("website_id must be a positive integer")

    query = """
        SELECT
            id,
            website_id,
            url,
            normalized_url,
            path,
            page_kind,
            priority_score,
            depth,
            discovered_from_url,
            link_text,
            status_code,
            content_type,
            identity_score,
            identity_observable,
            created_at,
            updated_at
        FROM website_pages
    """
    parameters: tuple[object, ...] = ()

    if website_id is not None:
        query += " WHERE website_id = ?"
        parameters = (website_id,)

    query += """
        ORDER BY
            website_id,
            priority_score DESC,
            depth,
            id
    """

    try:
        rows = connection.execute(
            query,
            parameters,
        ).fetchall()
    except sqlite3.Error as exc:
        raise PageDiscoveryError(f"Website page listing failed: {exc}") from exc

    return tuple(
        {
            "page_id": int(row["id"]),
            "website_id": int(row["website_id"]),
            "url": str(row["url"]),
            "normalized_url": str(row["normalized_url"]),
            "path": str(row["path"]),
            "page_kind": str(row["page_kind"]),
            "priority_score": int(row["priority_score"]),
            "depth": int(row["depth"]),
            "discovered_from_url": (
                None
                if row["discovered_from_url"] is None
                else str(row["discovered_from_url"])
            ),
            "link_text": (None if row["link_text"] is None else str(row["link_text"])),
            "status_code": (
                None if row["status_code"] is None else int(row["status_code"])
            ),
            "content_type": (
                None if row["content_type"] is None else str(row["content_type"])
            ),
            "identity_score": (
                None
                if row["identity_score"] is None
                else float(row["identity_score"])
            ),
            "identity_observable": bool(row["identity_observable"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    )


def discover_website_pages(
    connection: sqlite3.Connection,
    *,
    website_id: int,
    user_agent: str,
    timeout_seconds: int,
    max_redirects: int,
    max_pages: int,
    max_depth: int,
) -> PageDiscoveryRun:
    if max_pages < 1:
        raise PageDiscoveryError("max_pages must be at least 1")
    if max_pages > 100:
        raise PageDiscoveryError("max_pages must not exceed 100")
    if max_depth < 0:
        raise PageDiscoveryError("max_depth must not be negative")
    if max_depth > 5:
        raise PageDiscoveryError("max_depth must not exceed 5")
    if timeout_seconds < 1:
        raise PageDiscoveryError("timeout_seconds must be at least 1")
    if max_redirects < 0:
        raise PageDiscoveryError("max_redirects must not be negative")
    if not user_agent.strip():
        raise PageDiscoveryError("user_agent must not be empty")

    start_url, expected_domain, expected_business_name = _load_website(
        connection,
        website_id,
    )

    normalized_start = normalize_url(start_url)
    if normalized_start.value is None:
        raise PageDiscoveryError("Website start URL could not be normalized")

    queue: list[
        tuple[
            int,
            int,
            str,
            str | None,
            str | None,
        ]
    ] = []

    heapq.heappush(
        queue,
        (
            -50,
            0,
            normalized_start.value,
            None,
            None,
        ),
    )

    queued: set[str] = {normalized_start.value}
    visited: set[str] = set()

    pages_requested = 0
    pages_persisted = 0
    links_seen = 0
    links_queued = 0
    excluded_links = 0
    offsite_links = 0

    while queue and pages_requested < max_pages:
        (
            _negative_priority,
            depth,
            current_url,
            discovered_from,
            link_text,
        ) = heapq.heappop(queue)

        if current_url in visited:
            continue

        visited.add(current_url)
        pages_requested += 1

        result = probe_http(
            current_url,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
        )

        effective_url = result.final_url or current_url
        effective_normalized = normalize_url(effective_url)

        if effective_normalized.value is None:
            effective_normalized_value = current_url
        else:
            effective_normalized_value = effective_normalized.value

        kind, priority = classify_page(
            effective_normalized_value,
            link_text,
        )

        analysis = analyze_website_content(
            result.body,
            content_type=result.content_type,
            status_code=result.status_code,
            expected_business_name=expected_business_name,
        )
        identity_observable = (
            result.status_code is not None
            and 200 <= result.status_code < 300
            and result.content_type is not None
            and "html" in result.content_type.casefold()
            and not analysis.soft_404
            and not analysis.parked_or_for_sale
        )

        page = DiscoveredPage(
            website_id=website_id,
            url=effective_normalized_value,
            normalized_url=effective_normalized_value,
            path=urlsplit(effective_normalized_value).path or "/",
            page_kind=kind,
            priority_score=priority,
            depth=depth,
            discovered_from_url=discovered_from,
            link_text=link_text,
            status_code=result.status_code,
            content_type=result.content_type,
            identity_score=(analysis.identity_score if identity_observable else None),
            identity_observable=identity_observable,
        )

        upsert_website_page(connection, page)
        pages_persisted += 1

        if depth >= max_depth:
            continue

        if result.status_code is None:
            continue

        if not 200 <= result.status_code < 400:
            continue

        links = extract_links(
            result.body,
            base_url=effective_normalized_value,
            content_type=result.content_type,
        )

        for target_url, target_text in links:
            links_seen += 1

            if is_excluded_page(target_url):
                excluded_links += 1
                continue

            if not _same_site(
                target_url,
                expected_domain=expected_domain,
            ):
                offsite_links += 1
                continue

            if target_url in visited or target_url in queued:
                continue

            _page_kind, score = classify_page(
                target_url,
                target_text,
            )

            # Low-value generic pages are still discoverable, but the
            # crawler gives relevant Phase 7 targets queue precedence.
            heapq.heappush(
                queue,
                (
                    -score,
                    depth + 1,
                    target_url,
                    effective_normalized_value,
                    target_text or None,
                ),
            )
            queued.add(target_url)
            links_queued += 1

    return PageDiscoveryRun(
        website_id=website_id,
        pages_requested=pages_requested,
        pages_persisted=pages_persisted,
        links_seen=links_seen,
        links_queued=links_queued,
        excluded_links=excluded_links,
        offsite_links=offsite_links,
        max_pages=max_pages,
        max_depth=max_depth,
    )
