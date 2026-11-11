from tools.build_local_items import drops, item_page


def test_drops_read_names_from_alt_text_or_the_label_after_the_icon():
    page = ('<img src="https://cdn.meowdb.com/icons/4000005.png" alt="Tree Branch" width="32"/>'
            '<img src="https://cdn.meowdb.com/icons/4010001.png" alt="" width="32" class="w-8"/><span class="min-w-0">Iron Ore</span>'
            '<img src="https://cdn.meowdb.com/icons/4000005.png" alt="" width="32"/><span>Tree Branch</span>'
            '<img src="https://cdn.meowdb.com/icons/9999999.png" alt="" width="32"/>')
    assert drops(page) == {4000005: 'Tree Branch', 4010001: 'Iron Ore'}


def test_item_pages_count_only_monster_drops():
    image = ('<meta property="og:image" content="https://og.example/og?title=Animal+Fur+Bundle&amp;subtitle=Etc+%C2%B7+Monster+Drop'
             '&amp;hero=https%3A%2F%2Fexample%2Fapi%2Fassets%2Ficons%2F4000062&amp;sig=x"/>')
    page = image + '<meta name="description" content="Where to get Animal Fur Bundle: dropped by Fire Boar, Stirge and 2 other monsters. Used to craft Cloth."/>'
    assert item_page(page) == [4000062, 'Animal Fur Bundle', ['Fire Boar', 'Stirge']]
    quests = image + '<meta name="description" content="Where to get it: dropped by Mano, 2 other monsters or a reward from 2 quests."/>'
    assert item_page(quests)[2] == ['Mano']
    scroll = ('<meta property="og:image" content="https://og.example/og?title=Axe+Scroll&amp;eyebrow=Item+%C2%B7+Use+%C2%B7+Scroll'
              '&amp;hero=https%3A%2F%2Fexample%2Fapi%2Fassets%2Ficons%2F2043103"/><meta name="description" content="Success rate: 10%."/>')
    assert item_page(scroll) is None


def test_fetch_waits_the_minimum_gap_and_stops_at_a_refusal(monkeypatch):
    import pytest
    from urllib.error import HTTPError
    import tools.build_local_items as b
    waits = []
    monkeypatch.setattr(b.time, 'sleep', waits.append)
    def refuse(request, timeout):
        raise HTTPError(request.full_url, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(b, 'urlopen', refuse)
    with pytest.raises(SystemExit):
        b.fetch('https://example.invalid/item-db/1', 2)
    assert waits == [b.MIN_GAP]


def test_fetch_asks_for_gzip_and_unpacks_it(monkeypatch):
    import gzip
    import tools.build_local_items as b
    monkeypatch.setattr(b.time, 'sleep', lambda s: None)
    class Response:
        headers = {'Content-Encoding': 'gzip'}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return gzip.compress(b'<html>page</html>')
    asked = []
    monkeypatch.setattr(b, 'urlopen', lambda request, timeout: (asked.append(request.get_header('Accept-encoding')), Response())[1])
    assert b.fetch('https://example.invalid/item-db/1', 0) == b'<html>page</html>'
    assert asked == ['gzip']
