import os
from unittest.mock import patch

from engine.connectors.google_alerts import strip_markup, transform, unwrap_redirect
from engine.pipeline.profile import alert_sources_for_topic

REAL_SHAPE_LINK = (
    "https://www.google.com/url?rct=j&sa=t&url=https://www.centralbanking.com/"
    "fintech/cbdc/7961234/bank-of-x-launches-pilot&ct=ga&cd=CAIyGjY&usg=AOvVaw0abc"
)


def test_unwrap_redirect_recovers_the_real_article_url():
    assert unwrap_redirect(REAL_SHAPE_LINK) == (
        "https://www.centralbanking.com/fintech/cbdc/7961234/bank-of-x-launches-pilot"
    )


def test_unwrap_redirect_leaves_non_google_urls_alone():
    direct = "https://www.bis.org/review/r260101a.htm"
    assert unwrap_redirect(direct) == direct


def test_unwrap_redirect_leaves_google_urls_without_a_target_alone():
    # A google.com link that isn't a redirect wrapper shouldn't be mangled
    # into something empty — better to keep a usable-if-ugly URL than to
    # drop the item (make_item would reject a blank url).
    plain = "https://www.google.com/search?q=cbdc"
    assert unwrap_redirect(plain) == plain


def test_strip_markup_removes_bold_tags_and_entities():
    raw = "Bank of X launches <b>central bank digital currency</b> pilot &amp; trial"
    assert strip_markup(raw) == "Bank of X launches central bank digital currency pilot & trial"


def test_transform_cleans_title_url_and_summary_together():
    title, url, summary = transform(
        "<b>CBDC</b> pilot", REAL_SHAPE_LINK, "The <b>central bank</b> said&nbsp;today"
    )
    assert title == "CBDC pilot"
    assert url.startswith("https://www.centralbanking.com/")
    assert "<b>" not in summary
    assert summary.startswith("The central bank said")


def test_transform_output_feeds_a_stable_item_id():
    # The whole point of unwrapping: the same article arriving via a Google
    # Alert and via an outlet feed must collapse to one item. item_id is
    # derived from the URL, so the alert's redirect wrapper has to be gone
    # before make_item sees it.
    from engine.pipeline.items import make_item

    _title, url, _summary = transform("<b>CBDC</b> pilot", REAL_SHAPE_LINK, "")
    via_alert = make_item(title="CBDC pilot", source_type="news", connector="google_alerts", url=url)
    via_outlet = make_item(
        title="Bank of X launches pilot",
        source_type="news",
        connector="outlet_rss",
        url="https://www.centralbanking.com/fintech/cbdc/7961234/bank-of-x-launches-pilot",
    )
    assert via_alert["id"] == via_outlet["id"]


def test_alert_sources_resolve_a_literal_feed_url():
    profile = {"alerts": [{"id": "cbdc-core", "feed_url": "https://example.com/f", "status": "tested"}]}
    sources = alert_sources_for_topic(profile)
    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.com/f"
    assert sources[0]["connector"] == "google_alerts"
    assert sources[0]["empty_ok"] is True  # a quiet alert isn't a broken source


def test_alert_sources_resolve_a_feed_url_from_the_environment():
    # Keeps the URL (which embeds a Google account id) out of a public repo.
    profile = {"alerts": [{"id": "cbdc-core", "feed_url_env": "TEST_ALERT_FEED", "status": "tested"}]}
    with patch.dict(os.environ, {"TEST_ALERT_FEED": "https://example.com/from-env"}):
        sources = alert_sources_for_topic(profile)
    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.com/from-env"


def test_alert_sources_skip_unset_env_var_rather_than_failing_the_run():
    profile = {"alerts": [{"id": "cbdc-core", "feed_url_env": "DEFINITELY_NOT_SET_12345", "status": "tested"}]}
    assert alert_sources_for_topic(profile) == []


def test_alert_sources_respect_the_tested_status_gate():
    # Ground rule 4: nothing enters a run until a live request confirmed it.
    profile = {"alerts": [{"id": "x", "feed_url": "https://example.com/f", "status": "untested"}]}
    assert alert_sources_for_topic(profile) == []
