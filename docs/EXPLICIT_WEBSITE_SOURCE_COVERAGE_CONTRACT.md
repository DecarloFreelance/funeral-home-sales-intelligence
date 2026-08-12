# Explicit Website Source Coverage Contract

Version: `explicit-website-source-v1`

This contract makes local source imports capable of preserving explicit
business website fields for stronger offline candidate ranking. It does not
acquire data, make network requests, approve websites, or select primary sites.

Recognized explicit URL fields are `official_website`,
`official_website_url`, `homepage`, `home_page`, `organization_website`,
`organization_url`, and `contact_url`. Explicit domain fields are
`official_domain` and `organization_domain`.

Generic `website`, `website_url`, and `url` remain generic URL signals, while
`domain` remains a generic domain signal. Explicit URL fields normalize to
`explicit_website_url`; explicit domain fields normalize to
`explicit_website_domain`. Original values, warnings, and source-record
provenance remain preserved.

Explicit source fields rank above generic URLs/domains and email inference, but
still do not prove ownership, branch membership, reachability, approval, or
primary status. Shared domains remain reviewable.

This is a local import/normalization boundary only. It deliberately does not
add a collector, public-network request, web search, source completeness claim,
or source-specific interpretation beyond these field aliases.
