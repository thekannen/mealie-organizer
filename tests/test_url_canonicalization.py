from cookdex.recipe_deduplicator import canonicalize_url as dedup_canonicalize_url
from cookdex.recipe_dredger.url_utils import canonicalize_url


def test_deduplicator_uses_shared_canonicalization_policy() -> None:
    raw = "https://www2.example.com/recipe/?utm_source=news&b=2&a=1"

    assert canonicalize_url(raw) == "https://www2.example.com/recipe?a=1&b=2"
    assert dedup_canonicalize_url(raw) == canonicalize_url(raw)


def test_canonicalize_url_encodes_paths_sorts_query_and_removes_tracking() -> None:
    raw = "HTTPS://www.Example.COM/a b/?b=2&utm_source=x&a=hello%20world&fbclid=abc#frag"

    assert canonicalize_url(raw) == "https://example.com/a%20b?a=hello+world&b=2"
