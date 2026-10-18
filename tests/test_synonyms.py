from fooddb import synonyms


def test_expand_rewrites_an_austrian_word_for_at():
    assert synonyms.expand("Erdäpfel", "at") == ["Erdäpfel", "Kartoffel"]
    assert synonyms.expand("Paradeiser", "at") == ["Paradeiser", "Tomate"]
    assert synonyms.expand("Topfen", "at") == ["Topfen", "Quark"]


def test_expand_keeps_the_query_first_and_adds_one_rewrite_per_replacement():
    assert synonyms.expand("Schwammerl", "at") == ["Schwammerl", "Champignons", "Pilze"]


def test_expand_matches_a_stem_inside_a_compound():
    assert synonyms.expand("Erdäpfelsalat", "at") == ["Erdäpfelsalat", "kartoffelsalat"]
    # A listed word overrides the stem inside it.
    assert synonyms.expand("Schlagobers", "at") == ["Schlagobers", "Schlagsahne"]


def test_expand_matches_a_phrase():
    # "gelbe Rüben" are carrots, not beets: the phrase wins over the "rüben" stem.
    assert synonyms.expand("gelbe Rüben", "at") == ["gelbe Rüben", "Karotten"]
    assert synonyms.expand("Rote Rüben", "at") == ["Rote Rüben", "Rote Bete"]


def test_expand_leaves_other_countries_and_unlisted_words_alone():
    assert synonyms.expand("Erdäpfel", "de") == ["Erdäpfel"]
    assert synonyms.expand("Erdäpfel", None) == ["Erdäpfel"]
    assert synonyms.expand("Schnitzel", "at") == ["Schnitzel"]
    # The list maps Austrian -> German, never the reverse.
    assert synonyms.expand("Kartoffel", "at") == ["Kartoffel"]
