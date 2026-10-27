from wm_staff_agents.doctrine.corpus import DEFAULT_CORPUS


def test_corpus_has_16_conventions():
    assert len(DEFAULT_CORPUS.conventions) == 16


def test_matching_finds_targeting():
    results = DEFAULT_CORPUS.matching("we need targeting and weaponeering for this strike")
    ids = [c.id for c in results]
    assert any("targeting" in i for i in ids)


def test_for_role_filters():
    results = DEFAULT_CORPUS.for_role(("AFDP 3-60 Targeting",))
    assert len(results) > 0
    assert all("targeting" in " ".join(c.tags).lower() or "AFDP 3-60" in c.source.document for c in results)


def test_no_empty_descriptions():
    for c in DEFAULT_CORPUS.conventions:
        assert c.description.strip()
        assert c.source.document.strip()
