from engine.pipeline.items import clean_url, item_id, make_item


def test_clean_url_strips_tracking_params_and_trailing_slash():
    a = clean_url("https://Example.com/path/?utm_source=x&b=2&a=1")
    b = clean_url("https://example.com/path?b=2&a=1")
    assert a == b


def test_item_id_prefers_doi_over_url_over_title():
    by_doi = item_id(doi="10.1/abc", url="https://a.com/x", title="Something")
    by_doi_again = item_id(doi="10.1/abc", url="https://different.com/y", title="Different title")
    assert by_doi == by_doi_again

    by_url = item_id(url="https://a.com/x", title="Something")
    by_url_again = item_id(url="https://a.com/x", title="Unrelated title")
    assert by_url == by_url_again

    by_title = item_id(title="Only a title")
    by_title_again = item_id(title="Only A Title")
    assert by_title == by_title_again


def test_make_item_rejects_unknown_source_type():
    try:
        make_item(title="x", source_type="blog_post", connector="test")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown source_type")


def test_make_item_normalises_doi_case():
    item = make_item(title="x", source_type="article", connector="test", doi="10.1/ABC")
    assert item["doi"] == "10.1/abc"
